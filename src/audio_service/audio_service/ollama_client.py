import subprocess
import httpx
import json
import multiprocessing
import time
from datetime import datetime
from collections import deque
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class OllamaChatClient:
    def __init__(self, base_url="http://localhost:11434", model="qwen2.5:1.5b", max_history=1):
        self.base_url = base_url
        self.chat_url = f"{self.base_url}/api/chat"
        self.model = model
        self.max_history = max_history
        self.history = deque(maxlen=max_history * 2)
        self.system_message = None

        # 句子切分配置
        self.sentence_endings = "。！？!?"
        self.soft_endings = "，,、;； "
        self.max_len = 25

        # 控制字段
        self.process = None
        self.queue = None

        self.set_system_message("你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量100个字以内，用中文。")
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
        """
        请求 Ollama 加载模型（预热）。
        """
        model_name = model_name or self.model
        url = f"{self.base_url}/api/chat"
        payload = {"model": model_name, "messages": []}

        try:
            with httpx.stream("POST", url, json=payload, timeout=None) as resp:
                logging.debug(f"加载模型 {model_name} 请求已发送")

                resp.raise_for_status()

                for line in resp.iter_text():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        logging.info(f"加载模型 {model_name} 的响应为: {data}")

                        if data.get("done"):
                            logging.debug(f"模型 {model_name} 已加载完成。")
                            break
                    except json.JSONDecodeError:
                        continue
        except httpx.HTTPError as e:
            logging.error(f"加载模型 {model_name} 时发生 HTTP 错误: {e}")
            
    # @staticmethod
    # def _stream_worker(chat_url, model, messages_payload, queue):
    #     """
    #     使用 subprocess 调用 curl 执行流式请求，将文本内容放入队列。
    #     """
    #     payload = {"model": model, "messages": messages_payload}

    #     # 构造 curl 命令
    #     curl_cmd = [
    #         "curl",
    #         "-s",                    # 静默输出（不显示进度条）
    #         "-X", "POST", chat_url,  # POST 请求
    #         "-H", "Content-Type: application/json",
    #         "-d", json.dumps(payload),
    #         "--no-buffer",           # 关闭输出缓冲，确保实时输出
    #         "--connect-timeout", "5",  # 连接超时
    #         "--max-time", "10",        # 整体请求超时
    #     ]

    #     logging.info(f"[子进程] 启动 curl 向 {chat_url} 发起请求-[{datetime.now().strftime('%H:%M:%S')}]")

    #     try:
    #         # 启动 curl 子进程
    #         proc = subprocess.Popen(
    #             curl_cmd,
    #             stdout=subprocess.PIPE,
    #             stderr=subprocess.PIPE,
    #             text=True,  # 自动解码为字符串
    #             bufsize=1,  # 行缓冲模式
    #         )

    #         # 实时读取输出
    #         for line in proc.stdout:
    #             line = line.strip()
    #             if not line:
    #                 continue
    #             try:
    #                 data = json.loads(line)
    #                 msg = data.get("message", {})
    #                 text = msg.get("content")
    #                 if text:
    #                     queue.put(text)
    #                 if data.get("done"):
    #                     break
    #             except json.JSONDecodeError:
    #                 continue

    #         # 等待 curl 进程结束
    #         proc.wait(timeout=3)

    #         # 检查返回码
    #         if proc.returncode != 0:
    #             err = proc.stderr.read().strip()
    #             logging.info(f"[子进程] curl 进程返回码 {proc.returncode}，错误信息: {err}")

    #     except subprocess.TimeoutExpired:
    #         logging.info("[子进程] curl 超时退出")
    #     except Exception as e:
    #         logging.info(f"[子进程] 出错: {e}")
    #     finally:
    #         queue.put(None)  # 表示结束
    #         logging.info("[子进程] 结束。放入 None 标志流式输出结束。")
    @staticmethod
    def _stream_worker(chat_url, model, messages_payload, queue):
        """
        子进程执行 HTTP 请求，将 text 内容直接放入队列。
        主进程再负责拼接句子和分段逻辑。
        """
        payload = {"model": model, "messages": messages_payload}

        try:
            logging.info(f'[子进程] 开始请求 {chat_url}')
            with httpx.stream(
                "POST",
                chat_url,
                json=payload,
                headers={"Connection": "close"},   # 禁用keep-alive
                verify=False,
            ) as resp:
                logging.info(f'[子进程] 等待检查状态')
                resp.raise_for_status()
                logging.info(f'[子进程] 请求 {chat_url} 的状态正常')
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "message" not in data:
                            continue
                        msg = data["message"]
                        if "content" not in msg:
                            continue
                        text = msg["content"]
                        queue.put(text)
                        if data.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
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
            args=(self.chat_url, self.model, messages_payload, q),
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
                    yield sentence
                    buffer = buffer[idx + 1:]

                # 软分割（超过 max_len）
                if len(buffer) >= self.max_len:
                    for punc in self.soft_endings:
                        if punc in buffer:
                            idx = buffer.find(punc)
                            sentence = buffer[: idx + 1].strip()
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
    client = OllamaChatClient()

    for s in client.stream_sentence("天空为什么是蓝色的？"):
        print(">>>", s)

    print("---- 再问第二个 ----")
    for s in client.stream_sentence("这与米氏散射有何不同？"):
        print(">>>", s)

    client.close()


if __name__ == "__main__":
    main()
