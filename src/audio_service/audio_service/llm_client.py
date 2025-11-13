import subprocess
import httpx
import os
import json
import multiprocessing
import time
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

        self.api_key = os.environ.get("LLM_KEY")
        self.llm_endpoint = os.environ.get("LLM_ENDPOINT")
        self.llm_model = os.environ.get("LLM_MODEL")
        self.sys_message = os.environ.get("SYS_MESSAGE", '你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量100个字以内，用中文回答。')
        if not self.api_key or not self.llm_endpoint or not self.llm_model:
            raise ValueError("LLM_ENDPOINT, LLM_MODEL, and LLM_KEY must be set in the .env file in the project root directory, and the corresponding LLM service needs to support invocation using the OpenAI SDK.")

        # 句子切分配置
        self.sentence_endings = "。！？.!?"
        self.soft_endings = "，、;；,"
        self.max_len = 70

        # 控制字段
        self.process = None
        self.queue = None

        self.set_system_message(self.sys_message)
        self.load_model()

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
                        logging.info(f"总计 Tokens: {chunk.usage.total_tokens}")

        except Exception as e:
            logging.info(f'[子进程] 出错: {e}', exc_info=True)
        finally:
            queue.put(None)  # 表示结束
            logging.info("[子进程] 结束。放入 None 标志流式输出结束。")

    def stream_sentence(self, user_input):
        """在子进程发起请求并通过Queue流式返回结果（主进程负责拼句）"""
        # 若存在上一个子进程，则先终止
        self.set_interrupted(True)

        messages_payload = self.get_messages_payload(user_input)
        q = multiprocessing.Queue()
        p = multiprocessing.Process(
            target=self._stream_worker,
            args=(self.llm_endpoint, self.llm_model, messages_payload, q, self.api_key),
            daemon=True,
        )
        self.process = p
        self.queue = q
        p.start()
        logging.info(f'[主进程] 启动子进程 PID={p.pid}，[{user_input}] 的流式输出开始')

        assistant_response = ""
        buffer = ""

        while True:
            try:
                chunk = q.get(timeout=0.5)
                if chunk is None:
                    logging.info("[主进程] 队列里拿出NONE, 流式输出正常完成。")
                    break  # 子进程结束
                assistant_response += chunk
                buffer += chunk

                # 句号断句
                while any(punc in buffer for punc in self.sentence_endings):
                    idx = min(
                        [buffer.find(punc) for punc in self.sentence_endings if punc in buffer]
                    )
                    sentence = buffer[: idx + 1].strip()
                    logging.info(sentence)

                    yield sentence
                    buffer = buffer[idx + 1:]

                # 软分割（超过 max_len）
                if len(buffer) >= self.max_len:
                    for punc in self.soft_endings:
                        if punc in buffer:
                            idx = buffer.find(punc)
                            sentence = buffer[: idx + 1].strip()
                            
                            logging.info(sentence)

                            yield sentence
                            buffer = buffer[idx + 1:]
                            break

            except multiprocessing.queues.Empty:
                if not p.is_alive():
                    logging.info("[主进程] 子进程已 not alive, 流式输出将结束")
                    break
                continue
            except KeyboardInterrupt:
                logging.info("[主进程] 捕获 KeyboardInterrupt, 准备终止子进程。")
                self.set_interrupted(True)
                break

        # 若还有残留的文本
        if buffer.strip():
            yield buffer.strip()

        # 记录历史
        self.add_message("user", user_input)
        self.add_message("assistant", assistant_response)

        # 确保子进程退出
        if p.is_alive():
            p.join(timeout=1)
        if p.exitcode is not None:
            logging.info(f'[主进程] [{user_input}] 已退出，exitcode={p.exitcode}.')

    def set_interrupted(self, interrupted=True):
        """终止子进程"""
        if interrupted and getattr(self, "process", None):
            if self.process.is_alive():
                logging.debug(f"[主进程] 强制结束子进程 PID={self.process.pid}")
                self.process.terminate()
                self.process.join(timeout=1)
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
