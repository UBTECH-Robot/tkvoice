import asyncio
import threading
import json
import ssl
import os
import wave
import time
import websockets
import argparse
from datetime import datetime
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class GlobalAsyncLoop:
    """全局异步事件循环，运行在单独线程中"""
    _loop = None
    _thread = None

    @classmethod
    def get_loop(cls):
        if cls._loop is None:
            cls._loop = asyncio.new_event_loop()
            cls._thread = threading.Thread(target=cls._start_loop, daemon=True)
            cls._thread.start()

            # 等待 loop 启动
            start_time = time.time()
            while not cls._loop.is_running():
                time.sleep(0.01)
                if time.time() - start_time > 2:
                    raise RuntimeError("Async loop failed to start")
        return cls._loop

    @classmethod
    def _start_loop(cls):
        asyncio.set_event_loop(cls._loop)
        cls._loop.run_forever()


class FunASRClient:
    def __init__(self, host="localhost", port=10095, ssl_enabled=True,
                 chunk_size=[5, 10, 5], chunk_interval=10, sample_rate=16000,
                 hotword="", use_itn=True, mode="offline",
                 recv_timeout=2, connect_retries=3):
        """稳定版 FunASRClient"""
        self.host = host
        self.port = port
        self.ssl_enabled = ssl_enabled
        self.chunk_size = chunk_size
        self.chunk_interval = chunk_interval
        self.sample_rate = sample_rate
        self.hotword = hotword
        self.use_itn = use_itn
        self.mode = mode
        self.websocket = None
        self.recv_timeout = recv_timeout
        self.connect_retries = connect_retries
        self._ws_lock = threading.RLock()

        self.loop = GlobalAsyncLoop.get_loop()
        time.sleep(1)
        self.connect()

    async def _connect(self):
        """尝试建立 WebSocket 连接"""
        uri = f"wss://{self.host}:{self.port}" if self.ssl_enabled else f"ws://{self.host}:{self.port}"
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS) if self.ssl_enabled else None
        if self.ssl_enabled:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        logging.info(f"Connecting to {uri}")
        return await websockets.connect(uri, subprotocols=["binary"], ping_interval=None, ssl=ssl_context)

    async def try_init_connection(self):
        """初始化连接（含重试）"""
        with self._ws_lock:
            if self.websocket and self.websocket.state == websockets.State.OPEN:
                return self.websocket

            for attempt in range(1, self.connect_retries + 1):
                try:
                    self.websocket = await self._connect()
                    logging.info("FunASR connected successfully.")
                    return self.websocket
                except Exception as e:
                    logging.warning(f"Connect attempt {attempt}/{self.connect_retries} failed: {e}")
                    await asyncio.sleep(1)
            raise ConnectionError("Failed to connect after retries.")

    def connect(self):
        """同步连接接口"""
        if not self.loop.is_running():
            raise RuntimeError("Async loop not running")

        future = asyncio.run_coroutine_threadsafe(self.try_init_connection(), self.loop)
        return future.result(timeout=10)

    async def _send_audio(self, bytes_data, wav_name="audio"):
        """发送音频数据"""
        if not bytes_data:
            raise ValueError("Audio bytes cannot be empty")

        hotword_msg = self._load_hotwords()
        message = json.dumps({
            "mode": self.mode,
            "chunk_size": self.chunk_size,
            "chunk_interval": self.chunk_interval,
            "audio_fs": self.sample_rate,
            "wav_name": wav_name,
            "wav_format": "pcm",
            "is_speaking": True,
            "hotwords": hotword_msg,
            "itn": self.use_itn
        })
        await self.websocket.send(message)

        stride = int(60 * self.chunk_size[1] / self.chunk_interval / 1000 * self.sample_rate * 2)
        chunk_num = (len(bytes_data) - 1) // stride + 1

        for i in range(chunk_num):
            beg = i * stride
            data = bytes_data[beg:beg + stride]
            await self.websocket.send(data)
            sleep_duration = 0.001 if self.mode == "offline" else 60 * self.chunk_size[1] / self.chunk_interval / 1000
            await asyncio.sleep(sleep_duration)

        await self.websocket.send(json.dumps({"is_speaking": False}))

    async def _receive_text(self):
        """接收识别文本，带超时保护"""
        text_result = ""
        try:
            while True:
                logging.debug("等待asr进行")
                msg = await asyncio.wait_for(self.websocket.recv(), timeout=self.recv_timeout)
                logging.debug(f"接收到asr结果: {msg}")

                msg = json.loads(msg)
                logging.debug(f"接收到funasr结果: {msg}")
            
                text = msg.get("text", "")
                if not text:
                    continue
                text_result += text
                
                if msg.get("is_final", False):
                    break
        except asyncio.TimeoutError:
            logging.error("Receive timeout")
        except (websockets.exceptions.ConnectionClosed, json.JSONDecodeError) as e:
            logging.error(f"Receive error: {e}")
        return text_result

    async def to_text_async(self, bytes_data, wav_name="audio"):
        """异步识别"""
        try:
            await self.try_init_connection()
            send_task = asyncio.create_task(self._send_audio(bytes_data, wav_name))
            recv_task = asyncio.create_task(self._receive_text())

            done, pending = await asyncio.wait(
                [send_task, recv_task],
                timeout=self.recv_timeout + 5,
                return_when=asyncio.ALL_COMPLETED,
            )

            # 超时或异常处理
            for task in pending:
                task.cancel()
            for task in done:
                if task is recv_task:
                    res = task.result()
                    logging.debug(f'to_text_async 收到音频识别结果：{res}')
                    return res

            raise asyncio.TimeoutError("Recognition timed out")

        except Exception as e:
            logging.error(f"to_text_async failed: {e}")
            await self._safe_reconnect()
            return ""


    def to_text(self, bytes_data, wav_name="audio"):
        """同步封装（可安全调用）"""
        if not self.loop.is_running():
            raise RuntimeError("Async loop not running")

        try:
            future = asyncio.run_coroutine_threadsafe(self.to_text_async(bytes_data, wav_name), self.loop)
            res = future.result(timeout=self.recv_timeout + 10)
            logging.debug(f'to_text 返回识别结果：{res}')
            return res
        except Exception as e:
            logging.error(f"to_text failed: {e}")
            return ""

    async def _safe_reconnect(self):
        """自动重连"""
        try:
            if self.websocket:
                await self.websocket.close()
            self.websocket = await self._connect()
            logging.info("Reconnected successfully.")
        except Exception as e:
            logging.error(f"Reconnect failed: {e}")

    def _load_hotwords(self):
        """加载热词文件"""
        if not self.hotword or not os.path.exists(self.hotword):
            return ""
        fst_dict = {}
        try:
            with open(self.hotword, "r", encoding="utf-8") as f:
                for line in f:
                    words = line.strip().split()
                    if len(words) < 2:
                        continue
                    try:
                        fst_dict[" ".join(words[:-1])] = int(words[-1])
                    except ValueError:
                        continue
            return json.dumps(fst_dict)
        except Exception as e:
            logging.error(f"Failed to load hotwords: {e}")
            return ""

    def read_bytes(self, file_path):
        """读取 PCM 或 WAV 文件"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found.")
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".pcm":
            with open(file_path, "rb") as f:
                return f.read()
        elif ext == ".wav":
            with wave.open(file_path, "rb") as wav:
                return wav.readframes(wav.getnframes())
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def close(self):
        """关闭 WebSocket"""
        if self.websocket and self.websocket.state == websockets.State.OPEN:
            future = asyncio.run_coroutine_threadsafe(self.websocket.close(), self.loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
        self.websocket = None


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="FunASR Speech Recognition Client")
    parser.add_argument("audio_files", type=str, nargs="+", help="One or more path to the audio file (.wav or .pcm)")
    parser.add_argument("--host", type=str, default="localhost", help="ASR server host")
    parser.add_argument("--port", type=int, default=10095, help="ASR server port")
    parser.add_argument("--ssl", type=int, default=1, help="ssl")
    parser.add_argument("--hotword", type=str, default="", help="Path to hotword file")
    parser.add_argument("--mode", type=str, default="offline", choices=["online", "offline"], help="Recognition mode")
    return parser.parse_args()

def main():
    args = parse_args()

    client = FunASRClient(
        host=args.host,
        port=args.port,
        ssl_enabled=args.ssl,
        sample_rate=16000,
        hotword=args.hotword,
        mode=args.mode
    )

    for audio_file in args.audio_files:
        if not os.path.exists(audio_file):
            logging.error(f"PCM file {audio_file} does not exist")
            return

        try:
            audio_bytes = client.read_bytes(audio_file)
            start_time = time.perf_counter()
            text = client.to_text(audio_bytes)
            end_time = time.perf_counter()
            total_time = end_time - start_time
            logging.info(f"Recognized text: {text}, Time taken for recognition: {total_time:.6f} seconds")

        except Exception as e:
            logging.error(f"Recognition failed: {e}")

if __name__ == "__main__":
    main()

# python3 funasr_client.py test1.wav --host 192.168.41.1 --port 10097