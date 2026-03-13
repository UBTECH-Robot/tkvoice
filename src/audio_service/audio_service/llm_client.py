# import subprocess
# import httpx
import os
# import json
import multiprocessing
import queue
# import time
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
        self.llm_model = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")
        self.sys_message = os.environ.get("SYS_MESSAGE", '你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量100个字以内，用中文回答。')

        # 句子切分配置
        self.sentence_endings = "。！？.!?"
        self.soft_endings = "，、;；,"
        self.max_len = 25

        self.mp_context = multiprocessing.get_context("spawn")
        # 控制字段
        self.process = None
        self.queue = None

        self.set_system_message(self.sys_message)
        self.load_model()

    def test_llm_ip(self, timeout=2):
        """
        测试 Ollama 服务运行在哪个 IP 上。
        备选 IP: 192.168.41.3 和 192.168.41.2
        使用 /api/version 接口验证服务可用性。
        返回可用的 IP，若都不可达则返回 None。
        """
        candidate_ips = ["192.168.41.3", "192.168.41.2"]
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

        logging.warning("[LLM] 未找到可用的 Ollama 服务 (192.168.41.3, 192.168.41.2)")
        return None

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

    def load_model(self, model_name=None):
        return

    @staticmethod
    def _stream_worker(base_url, model, messages_payload, queue, api_key):
        """
        子进程执行 HTTP 请求，将 text 内容直接放入队列。
        主进程再负责拼接句子和分段逻辑。
        """
        try:
            logging.info(f'[子进程] 开始请求 {base_url}')
            with OpenAI(api_key=api_key, base_url=base_url) as client:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages_payload,
                    stream=True,
                    stream_options={"include_usage": True}
                )
                logging.info(f'[子进程] 请求已发起，等待输出')
                for chunk in completion:
                    if chunk.choices:
                        content = chunk.choices[0].delta.content or ""
                        queue.put(content)
                    elif chunk.usage:
                        logging.debug(f"[子进程] 总计 Tokens: {chunk.usage.total_tokens}")

        except Exception as e:
            logging.info(f'[子进程] 出错: {e}', exc_info=True)
        finally:
            queue.put(None)  # 表示结束
            logging.debug("[子进程] 数据发送完成，等待主进程处理。")

    def stream_sentence(self, user_input):
        """在子进程发起请求并通过Queue流式返回结果（主进程负责拼句）"""
        # 若存在上一个子进程，则先终止
        self.set_interrupted(True)

        if not self.llm_endpoint:
            logging.error("[NLP] 无可用的 LLM 服务，无法处理请求")
            yield "抱歉，当前无法连接到语言模型服务。"
            return

        messages_payload = self.get_messages_payload(user_input)
        q = self.mp_context.Queue()
        p = self.mp_context.Process(
            target=self._stream_worker,
            args=(self.llm_endpoint, self.llm_model, messages_payload, q, self.api_key),
            daemon=True,
        )
        self.process = p
        self.queue = q
        p.start()
        logging.info(f'[NLP] Started subprocess PID={p.pid}, streaming output for [{user_input}]')

        assistant_response = ""
        buffer = ""

        while True:
            try:
                chunk = q.get(timeout=0.5)
                if chunk is None:
                    logging.debug("[NLP] Received None from queue, stream complete")
                    break  # 子进程结束
                assistant_response += chunk
                buffer += chunk

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

            except queue.Empty:
                if not p.is_alive():
                    logging.debug("[NLP] Subprocess ended, stream output complete")
                    break
                continue
            except KeyboardInterrupt:
                logging.info("[NLP] Caught KeyboardInterrupt, terminating subprocess")
                self.set_interrupted(True)
                break

        # 若还有残留的文本
        if buffer.strip():
            remaining = buffer.strip()
            logging.info(f"[NLP] Stream output remaining: {remaining}")
            yield remaining

        # 记录历史
        self.add_message("user", user_input)
        self.add_message("assistant", assistant_response)

        # 确保子进程退出
        if p.is_alive():
            p.join(timeout=1)
        if p.exitcode is not None:
            logging.info(f'[NLP] Question [{user_input}] completed, exitcode={p.exitcode}.')

    def set_interrupted(self, interrupted=True):
        """终止子进程"""
        if interrupted:
            process = getattr(self, "process", None)
            stream_queue = getattr(self, "queue", None)
        
            if process is not None and process.is_alive():
                logging.debug(f"[主进程] 强制结束子进程 PID={process.pid}")
                process.terminate()
                process.join(timeout=1)
            if stream_queue is not None:
                try:
                    stream_queue.close()
                    stream_queue.join_thread()
                except Exception:
                    pass
            self.process = None
            self.queue = None

    def close(self):
        self.set_interrupted(True)

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
