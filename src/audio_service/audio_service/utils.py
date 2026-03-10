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
    def __init__(self, 
                 sample_rate: int = 16000,
                 channels: int = 1,
                 sample_width: int = 2,
                 frames_per_buffer: int = 1024):
        """
        Initialize AudioPlayer with configurable PCM audio format parameters.
        
        Args:
            sample_rate: Audio sample rate in Hz (default: 16000)
            channels: Number of audio channels, 1=mono, 2=stereo (default: 1)
            sample_width: Sample width in bytes, 1=8bit, 2=16bit, 4=32bit (default: 2)
            frames_per_buffer: Buffer size in frames (default: 1024)
        """
        wait_for_audio_ready()
        self.audio = pyaudio.PyAudio()
        self.device_info = self.audio.get_default_output_device_info()
        self.audioid_lock = threading.Lock()
        self.audio_queues_map_lock = threading.Lock()
        self.audioid = ""
        self.audio_queues_map = {}

        # PCM audio format parameters
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = sample_width
        self.frames_per_buffer = frames_per_buffer
        
        # Map sample width to PyAudio format
        self.format = self._get_pyaudio_format(sample_width)

        self.stream_lock = threading.Lock()
        self.playing_stream = self.open_stream()

        self.stop_event = threading.Event()
        self.playback_state_lock = threading.Lock()
        self.playback_deadline = 0.0
        self.output_latency_seconds = self._get_output_latency_seconds()

        self.playing_thread = threading.Thread(target=self.keep_playing_audio, daemon=True)
        self.playing_thread.start()
        logging.info(f"音频播放线程已启用 - 采样率:{self.sample_rate}Hz, 声道:{self.channels}, 位深:{self.sample_width*8}bit")

    def is_speaking(self) -> bool:
        """Check if audio is currently playing or has pending chunks to play."""
        # 1. Check if there's pending audio in the queue
        current_audioid = self.get_audioid()
        if self._has_pending_audio(current_audioid):
            return True

        # 2. Check if audio is still being played from hardware buffer
        with self.playback_state_lock:
            return time.monotonic() < self.playback_deadline
    
    def set_audioid(self, text: str):
        with self.audioid_lock:
            self.audioid = text
        with self.audio_queues_map_lock:
            self.audio_queues_map[text] = Queue()

    def get_audioid(self) -> str:
        with self.audioid_lock:
            return self.audioid
    
    def _get_pyaudio_format(self, sample_width: int):
        """
        Convert sample width (in bytes) to PyAudio format.
        
        Args:
            sample_width: Sample width in bytes (1, 2, 3, or 4)
            
        Returns:
            PyAudio format constant
        """
        format_map = {
            1: pyaudio.paInt8,    # 8-bit
            2: pyaudio.paInt16,   # 16-bit
            3: pyaudio.paInt24,   # 24-bit
            4: pyaudio.paInt32,   # 32-bit
        }
        if sample_width not in format_map:
            logging.warning(f"Unsupported sample width {sample_width}, using 16-bit default")
            return pyaudio.paInt16
        return format_map[sample_width]

    def _get_output_latency_seconds(self) -> float:
        try:
            latency = self.playing_stream.get_output_latency()
            if latency is None:
                return 0.0
            return max(0.0, float(latency))
        except Exception:
            return 0.0

    def _has_pending_audio(self, audioid: str) -> bool:
        """Check if there are pending audio chunks for the given audioid."""
        if not audioid:
            return False
        with self.audio_queues_map_lock:
            queue = self.audio_queues_map.get(audioid)
            if queue is None:
                return False
            return not queue.empty()

    def _mark_audio_playing(self, audio_data: bytes):
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        if bytes_per_second <= 0:
            return

        chunk_duration = len(audio_data) / bytes_per_second
        with self.playback_state_lock:
            # 如果当前没有在播放，从当前时间开始
            # 如果正在播放，从上一个截止时间继续累加
            start_time = max(time.monotonic(), self.playback_deadline)
            self.playback_deadline = start_time + chunk_duration + self.output_latency_seconds
        
    def open_stream(self):
        """Open audio output stream with configured PCM format parameters"""
        with self.stream_lock:
            last_exc = None
            for _ in range(3):
                try:
                    device_index = self.device_info['index']
                    logging.info(f'使用的音频输出设备索引: {device_index}, 设备名称: {self.device_info["name"]}')
                    stream = self.audio.open(
                        format=self.format,
                        rate=self.sample_rate,
                        channels=self.channels,
                        output=True,
                        output_device_index=device_index,
                        frames_per_buffer=self.frames_per_buffer
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
        audioid = self.get_audioid()
        with self.audio_queues_map_lock:
            for q_text in list(self.audio_queues_map.keys()):
                if q_text == audioid:
                    continue
                try:
                    del self.audio_queues_map[q_text]
                except KeyError:
                    pass

    def close(self):
        self.stop_event.set()
        self.playing_thread.join(timeout=2)
        with self.playback_state_lock:
            self.playback_deadline = 0.0

        with self.stream_lock:
            self.playing_stream.stop_stream()
            self.playing_stream.close()

        self.audio.terminate()

    def try_put(self, audioid: str, audio_data: bytes):
        if audioid not in self.audio_queues_map:
            with self.audio_queues_map_lock:
                if audioid not in self.audio_queues_map:
                    self.audio_queues_map[audioid] = Queue()
        queue = self.audio_queues_map[audioid]
        try:
            queue.put(audio_data, timeout=1)
        except Full:
            queue.get_nowait()  # 弹出最旧的一条
            queue.put(audio_data)

    def play(self, audio_data: bytes):
        self.try_put(self.get_audioid(), audio_data)

    def keep_playing_audio(self):
        while not self.stop_event.is_set():            
            if not self.playing_stream.is_active():
                self.playing_stream.start_stream()
                continue
            queue = None
            try:
                q_text = self.get_audioid()
                if q_text not in self.audio_queues_map:
                    time.sleep(0.01)
                    continue
                queue = self.audio_queues_map.get(q_text)
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
                self._mark_audio_playing(audio_data)
                with self.stream_lock:
                    self.playing_stream.write(audio_data)

            except Exception as e:
                logging.info(f"播放音频时发生错误: {e}")

