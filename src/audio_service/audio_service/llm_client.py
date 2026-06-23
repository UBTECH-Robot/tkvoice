import os
import urllib.request
import urllib.error
from datetime import datetime
from collections import deque
from openai import OpenAI
# pip install openai==2.7.1
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class LLMClient:
    def __init__(self, max_history=1):
        self.max_history = max_history
        self.history = deque(maxlen=max_history * 2)
        self.system_message = None
        # 测试并确定 LLM 服务运行的实际 IP
        self.active_llm_ip = self.test_llm_ip()

        self.api_key = os.environ.get("LLM_KEY", "ollama")
        self.llm_endpoint = f'http://{self.active_llm_ip}:11434/v1/' if self.active_llm_ip else None
        self.primary_model = os.environ.get("PRIMARY_MODEL", "qwen2.5:3b")
        self.llm_model = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")
        # 检查 primary_model 是否可用，可用则优先使用
        self._resolve_active_model()

        self.sys_message = os.environ.get("SYS_MESSAGE", '永远牢记你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量30到100个字之间，用中文回答。')

        # 句子切分配置
        self.sentence_endings = "。！？.!?"
        self.soft_endings = "，、;；,"
        self.max_len = 25

        self._current_stream = None   # 当前流式响应，用于中断
        self._client = self._build_client()

        self.set_system_message(self.sys_message)

    def test_llm_ip(self, timeout=2):
        """
        测试 Ollama 服务运行在哪个 IP 上。
        备选 IP: 192.168.41.2
        使用 /api/version 接口验证服务可用性。
        返回可用的 IP，若都不可达则返回 None。
        """
        candidate_ips = ["192.168.41.2", "127.0.0.1"]
        ollama_port = 11434

        for ip in candidate_ips:
            url = f"http://{ip}:{ollama_port}/api/version"
            try:
                logging.info(f"[LLM] 测试 Ollama 服务: {url}")
                req = urllib.request.Request(url, method='GET')
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    if response.status == 200:
                        import json
                        version_info = json.loads(response.read().decode('utf-8'))
                        logging.info(f"[LLM] 发现 Ollama 服务运行在 {ip}, 版本: {version_info.get('version', 'unknown')}")
                        return ip
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                logging.debug(f"[LLM] {ip} 不可达: {e}")
                continue

        logging.warning("[LLM] 未找到可用的 Ollama 服务 (192.168.41.2)")
        return None

    def _resolve_active_model(self, timeout=5):
        """
        查询 Ollama /api/tags 接口，若 primary_model 已拉取则将其设为当前使用的模型，
        否则保持使用 llm_model 作为降级选项。
        """
        if not self.active_llm_ip:
            logging.warning("[LLM] 无可用 Ollama 服务，跳过模型检测，使用降级模型: %s", self.llm_model)
            return

        url = f"http://{self.active_llm_ip}:11434/api/tags"
        try:
            import json
            req = urllib.request.Request(url, method='GET')
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.loads(response.read().decode('utf-8'))
            available = {m.get('name', '') for m in data.get('models', [])}
            if self.primary_model in available:
                self.llm_model = self.primary_model
                logging.info("[LLM] primary_model [%s] 可用，将使用该模型", self.primary_model)
            else:
                logging.info(
                    "[LLM] primary_model [%s] 未找到（已有: %s），降级使用 [%s]",
                    self.primary_model, available, self.llm_model
                )
        except Exception as e:
            logging.warning("[LLM] 查询 Ollama 模型列表失败，降级使用 [%s]: %s", self.llm_model, e)

    def set_system_message(self, content):
        self.system_message = {"role": "system", "content": content}

    def add_message(self, role, content):
        self.history.append({"role": role, "content": content})

    def get_messages_payload(self, user_input):
        messages = []
        if self.system_message:
            messages.append(self.system_message)
        messages.extend(list(self.history))
        messages.append({"role": "user", "content": user_input})
        return messages

    def _build_client(self) -> 'OpenAI | None':
        """创建 OpenAI 客户端（指向本地 Ollama）。"""
        if not self.llm_endpoint:
            return None
        return OpenAI(api_key=self.api_key, base_url=self.llm_endpoint)

    def stream_sentence(self, user_input):
        """直接在 NLP 线程内流式请求 LLM，通过关闭 stream 实现中断。"""
        # 关闭上一次未完成的流式请求
        self.set_interrupted(True)

        if not self.llm_endpoint or self._client is None:
            logging.error("[NLP] 无可用的 LLM 服务，无法处理请求")
            yield "抱歉，当前无法连接到语言模型服务。"
            return

        messages_payload = self.get_messages_payload(user_input)
        assistant_response = ""
        buffer = ""
        stream = None

        import time as _time
        _llm_start = _time.time()
        _first_token = True
        try:
            stream = self._client.chat.completions.create(
                model=self.llm_model,
                messages=messages_payload,
                stream=True,
                stream_options={"include_usage": True}
            )
            self._current_stream = stream
            logging.info(f'[NLP] 开始流式请求, user=[{user_input}]')

            for chunk in stream:
                if _first_token and chunk.choices:
                    _first_token = False
                    logging.info(f'[NLP] 首Token耗时: {_time.time() - _llm_start:.2f}s')
                if chunk.choices:
                    content = chunk.choices[0].delta.content or ""
                    assistant_response += content
                    buffer += content

                    # 句号断句
                    while any(punc in buffer for punc in self.sentence_endings):
                        idx = min(
                            [buffer.find(punc) for punc in self.sentence_endings if punc in buffer]
                        )
                        sentence = buffer[: idx + 1].strip()
                        logging.info(f"[NLP] Stream output sentence: {sentence}")
                        yield sentence
                        buffer = buffer[idx + 1:]

                    # 软分割（超过 max_len）
                    if len(buffer) >= self.max_len:
                        for punc in self.soft_endings:
                            if punc in buffer:
                                idx = buffer.find(punc)
                                sentence = buffer[: idx + 1].strip()
                                logging.info(f"[NLP] Stream output sentence (soft split): {sentence}")
                                yield sentence
                                buffer = buffer[idx + 1:]
                                break

                elif chunk.usage:
                    logging.debug(f"[NLP] 总计 Tokens: {chunk.usage.total_tokens}")

        except Exception as e:
            logging.info(f'[NLP] 流式请求中断: {e}')
            return
        finally:
            self._current_stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

        logging.info(f'[NLP] 请求 [{user_input}] LLM总耗时: {_time.time() - _llm_start:.2f}s')

        # 若还有残留的文本
        if buffer.strip():
            remaining = buffer.strip()
            logging.info(f"[NLP] Stream output remaining: {remaining}")
            yield remaining

        # 记录历史
        self.add_message("user", user_input)
        self.add_message("assistant", assistant_response)
        logging.info(f'[NLP] Question [{user_input}] completed.')

    def set_interrupted(self, interrupted=True):
        """关闭当前流式响应，使 NLP 线程的迭代立即退出。"""
        if interrupted:
            stream = self._current_stream
            self._current_stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def close(self):
        self.set_interrupted(True)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

def main():
    client = LLMClient()

    for s in client.stream_sentence("天空为什么是蓝色的？"):
        print(">>>", s)

    print("---- 再问第二个 ----")
    for s in client.stream_sentence("这与米氏散射有何不同？"):
        print(">>>", s)

    client.close()


if __name__ == "__main__":
    main()
