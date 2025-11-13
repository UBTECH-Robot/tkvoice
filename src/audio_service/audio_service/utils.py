import threading
import time
import traceback
import pyaudio
from queue import Queue, Empty, Full
import wave
import os
import time
import argparse
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

def wait_for_audio_ready(max_wait=5):
    for i in range(max_wait * 10):
        try:
            p = pyaudio.PyAudio()
            info = p.get_default_output_device_info()
            if info and info.get('defaultSampleRate'):
                logging.info(f"audio device is ready: {info['defaultSampleRate']}")
                p.terminate()
                return
        except Exception as e:
            pass
        time.sleep(0.5)
    logging.info("警告：音频设备可能未准备就绪，继续执行...")

class AudioPlayer:
    def __init__(self):
        wait_for_audio_ready()
        self.audio = pyaudio.PyAudio()
        self.device_info = self.audio.get_default_output_device_info()
        self.question_lock = threading.Lock()
        self.question_audio_map_lock = threading.Lock()
        self.question_text = ""
        self.question_audio_map = {}

        self.stream_lock = threading.Lock()
        self.playing_stream = self.open_stream()
        self.chunk_size = 1024

        self.stop_event = threading.Event()
        self.is_speaking_event = threading.Event()

        self.playing_thread = threading.Thread(target=self.keep_playing_audio, daemon=True)
        self.playing_thread.start()
        logging.info(f"音频播放线程已启用，音频数据将自动按顺序播放")

    def is_speaking(self) -> bool:
        return self.is_speaking_event.is_set()
    
    def set_question_text(self, text: str):
        with self.question_lock:
            self.question_text = text
        with self.question_audio_map_lock:
            self.question_audio_map[text] = Queue()

    def get_question_text(self) -> str:
        with self.question_lock:
            return self.question_text
        
    def open_stream(self):
        with self.stream_lock:
            last_exc = None
            for _ in range(3):
                try:
                    device_index = self.device_info['index']
                    logging.info(f'使用的音频输出设备索引: {device_index}, 设备名称: {self.device_info["name"]}')
                    stream = self.audio.open(
                        # format=pyaudio.paFloat32,
                        # rate=22050,
                        format=pyaudio.paInt16,  # 16bit整数
                        rate=16000,             # 16kHz采样率
                        channels=1,
                        output=True,
                        output_device_index=device_index,
                        frames_per_buffer=1024
                    )
                    return stream
                except OSError as e:
                    logging.info(f'PyAudio open_stream报错了：{e}')
                    traceback.print_exc()
                    if e.errno == -9997:  # Invalid sample rate
                        last_exc = e
                        time.sleep(3)  # 等待一会再试
                    else:
                        raise  # 不是采样率的问题，直接抛出
            # 三次都失败，抛出最后一次的异常
        raise last_exc
    
    def stop_other_audio_and_clear_queue(self):
        question_text = self.get_question_text()
        with self.question_audio_map_lock:
            for q_text in list(self.question_audio_map.keys()):
                if q_text == question_text:
                    continue
                try:
                    del self.question_audio_map[q_text]
                except KeyError:
                    pass

        self.is_speaking_event.clear()

    def close(self):
        self.stop_event.set()
        self.playing_thread.join(timeout=2)

        with self.stream_lock:
            self.playing_stream.stop_stream()
            self.playing_stream.close()

        self.audio.terminate()

    def try_put(self, question_text: str, audio_data: bytes):
        if question_text not in self.question_audio_map:
            with self.question_audio_map_lock:
                if question_text not in self.question_audio_map:
                    self.question_audio_map[question_text] = Queue()
        queue = self.question_audio_map[question_text]
        try:
            queue.put(audio_data, timeout=1)
        except Full:
            queue.get_nowait()  # 弹出最旧的一条
            queue.put(audio_data)

    def play(self, audio_data: bytes):
        self.try_put(self.get_question_text(), audio_data)

    def keep_playing_audio(self):
        while not self.stop_event.is_set():            
            if not self.playing_stream.is_active():
                self.playing_stream.start_stream()
                continue
            queue = None
            try:
                q_text = self.get_question_text()
                if q_text not in self.question_audio_map:
                    time.sleep(0.01)
                    continue
                queue = self.question_audio_map.get(q_text)
                if queue is None:
                    time.sleep(0.01)
                    continue
                audio_data = queue.get_nowait()
            except Empty:
                time.sleep(0.01)
                continue

            try:
                if audio_data is None:
                    time.sleep(0.01)
                    break
                with self.stream_lock:
                    self.is_speaking_event.set()
                    self.playing_stream.write(audio_data)
                if queue and queue.empty():
                    self.is_speaking_event.clear()

            except Exception as e:
                logging.info(f"播放音频时发生错误: {e}")

