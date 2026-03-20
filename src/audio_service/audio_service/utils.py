import threading
import time
import traceback
from pathlib import Path
import pyaudio
import numpy as np
from queue import Queue, Empty, Full
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

def wait_for_audio_ready(max_wait=5):
    for i in range(max_wait * 10):
        try:
            p = pyaudio.PyAudio()
            info = p.get_default_output_device_info()
            if info and info.get('defaultSampleRate'):
                logging.info(f"音频设备已就绪，默认采样率: {info['defaultSampleRate']}")
                p.terminate()
                return
        except Exception as e:
            pass
        time.sleep(0.5)
    logging.info("警告：音频设备可能未准备就绪，继续执行...")

class AudioPlayer:
    def __init__(self,
                 sample_rate: int = 21000,
                 channels: int = 1,
                 sample_width: int = 2,
                 audio_format: int = None,
                 frames_per_buffer: int = 256):
        """
        Initialize AudioPlayer with configurable PCM audio format parameters.

        Args:
            sample_rate: Audio sample rate in Hz (default: 21000, matches piper-tts)
            channels: Number of audio channels, 1=mono, 2=stereo (default: 1)
            sample_width: Sample width in bytes, 1=8bit, 2=16bit, 4=32bit (default: 2 for 16-bit PCM)
            audio_format: PyAudio format constant (e.g., pyaudio.paInt16, pyaudio.paFloat32).
                          If None, inferred from sample_width.
            frames_per_buffer: Buffer size in frames (default: 256)
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
        # 待机时输出极低音量提示音，避免“完全静音”
        self.idle_tone_hz = 440.0
        self.idle_tone_amplitude = 0.0025 # 这个数值的表现是，第一次播放还是会有吞第一个字的情况，后续再播放没出现吞字情况，这个值的声音几乎听不到
        # 正常音频切块时长（秒）：块越小越容易被打断，但调度开销会略增加
        self.play_chunk_seconds = 0.04

        # Map sample width/format to PyAudio format
        self.format = self._get_pyaudio_format(sample_width, audio_format)

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
        
    def _get_pyaudio_format(self, sample_width: int, audio_format: int = None):
        """
        Convert sample width (in bytes) to PyAudio format.

        Args:
            sample_width: Sample width in bytes (1, 2, 3, or 4)
            audio_format: Optional PyAudio format constant. If provided, use directly.
                          If None, inferred from sample_width.

        Returns:
            PyAudio format constant
        """
        if audio_format is not None:
            return audio_format

        format_map = {
            1: pyaudio.paInt8,    # 8-bit
            2: pyaudio.paInt16,   # 16-bit
            3: pyaudio.paInt24,   # 24-bit
            4: pyaudio.paFloat32, # 32-bit float
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
        if audioid is None:
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

        # 打断后不要长时间沿用旧请求累计的播放截止时间，
        # 否则 is_speaking() 会继续返回 True，导致新语音输入被误忽略。
        # 这里不直接清零，保留一个很小的硬件排空保护窗，避免误判为立刻静默。
        now = time.monotonic()
        interrupt_grace = min(0.12, max(0.02, self.output_latency_seconds))
        with self.playback_state_lock:
            self.playback_deadline = min(self.playback_deadline, now + interrupt_grace)

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

    def play(self, audio_data: bytes, audioid: str = None):
        if not audio_data:
            return

        frame_size = self.channels * self.sample_width
        if frame_size <= 0:
            return

        # 按小块入队，降低单次 write 的阻塞时长，提升切换/打断响应
        chunk_frames = max(1, int(self.sample_rate * self.play_chunk_seconds))
        chunk_bytes = chunk_frames * frame_size
        target_audioid = audioid if audioid is not None else self.get_audioid()

        valid_length = len(audio_data) - (len(audio_data) % frame_size)
        if valid_length <= 0:
            return

        for offset in range(0, valid_length, chunk_bytes):
            self.try_put(target_audioid, audio_data[offset: offset + chunk_bytes])

    def _load_pcm(self, file_path: Path) -> bytes:
        file_path = Path(file_path)
        with file_path.open('rb') as pcm_file:
            audio_data = pcm_file.read()

        if not audio_data:
            logging.warning(f"PCM文件为空，跳过播放: {file_path}")
            return b''

        frame_size = self.channels * self.sample_width
        if frame_size > 0 and len(audio_data) % frame_size != 0:
            valid_length = len(audio_data) - (len(audio_data) % frame_size)
            logging.warning(
                f"PCM文件长度不是完整帧大小的整数倍，将截断尾部残留字节: {file_path}, "
                f"原始长度={len(audio_data)}, 截断后长度={valid_length}"
            )
            audio_data = audio_data[:valid_length]

        return audio_data

    def _build_idle_chunk(self) -> bytes:
        """Generate a very low-volume idle tone chunk that is audible but unobtrusive."""
        n_frames = self.frames_per_buffer
        n_samples = n_frames * self.channels

        if self.sample_width == 2:
            peak = int(32767 * self.idle_tone_amplitude)
            if peak <= 0:
                peak = 1
            t = np.arange(n_frames, dtype=np.float32) / float(self.sample_rate)
            wave = (np.sin(2 * np.pi * self.idle_tone_hz * t) * peak).astype(np.int16)
            if self.channels > 1:
                wave = np.repeat(wave, self.channels)
            return wave.tobytes()

        if self.sample_width == 1:
            peak = int(127 * self.idle_tone_amplitude)
            if peak <= 0:
                peak = 1
            t = np.arange(n_frames, dtype=np.float32) / float(self.sample_rate)
            wave = (128 + np.sin(2 * np.pi * self.idle_tone_hz * t) * peak).astype(np.uint8)
            if self.channels > 1:
                wave = np.repeat(wave, self.channels)
            return wave.tobytes()

        return bytes(n_samples * self.sample_width)

    def keep_playing_audio(self):
        # 使用极低音量待机音代替“完全静音”，保持设备活跃且可被人耳轻微感知
        silence_chunk = self._build_idle_chunk()

        while not self.stop_event.is_set():
            if not self.playing_stream.is_active():
                self.playing_stream.start_stream()
                continue
            queue = None
            try:
                q_text = self.get_audioid()
                if q_text not in self.audio_queues_map:
                    with self.stream_lock:
                        self.playing_stream.write(silence_chunk)
                    continue
                queue = self.audio_queues_map.get(q_text)
                if queue is None:
                    with self.stream_lock:
                        self.playing_stream.write(silence_chunk)
                    continue
                audio_data = queue.get_nowait()
            except Empty:
                with self.stream_lock:
                    self.playing_stream.write(silence_chunk)
                continue

            try:
                if audio_data is None:
                    with self.stream_lock:
                        self.playing_stream.write(silence_chunk)
                    break
                self._mark_audio_playing(audio_data)
                with self.stream_lock:
                    self.playing_stream.write(audio_data)

            except Exception as e:
                logging.error(f"播放音频时发生错误: {e}")
                traceback.print_exc()

def main(args=None):
    audio_player = AudioPlayer(sample_rate=16000, channels=1, sample_width=2, frames_per_buffer=1024)
    audio_files_dir = Path('audio_files')

    def stop_handle():
        logging.info("接收到终止信号，准备终止程序...")
        audio_player.close()
        logging.info("AudioPlayer已销毁，正在退出...")
        
    try:
        if not audio_files_dir.exists():
            logging.error(f"音频目录不存在: {audio_files_dir}")
            return

        pcm_files = sorted(audio_files_dir.glob('*.pcm'))
        if not pcm_files:
            logging.info(f"未找到可播放的PCM文件: {audio_files_dir}")
            return

        logging.info(f"开始按顺序播放PCM文件，共 {len(pcm_files)} 个: {audio_files_dir}")
        for pcm_file in pcm_files:
            time.sleep(3)
            audio_data = audio_player._load_pcm(pcm_file)
            if not audio_data:
                continue

            logging.info(f"开始播放PCM文件: {pcm_file.name}, 字节数: {len(audio_data)}")
            audio_player.play(audio_data)
            while audio_player.is_speaking():
                time.sleep(0.3)

    except KeyboardInterrupt:
        logging.error("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()

# for development and testing, ref tk_audio_publisher.py to save .pcm files, then run the following command in terminal:
# cd /home/nvidia/tkvoice/src/audio_service
# python -m audio_service.utils

# Or run compiled version with:
# cd /home/nvidia/tkvoice/
# colcon build --packages-select audio_message audio_service
# source install/setup.bash
# python -m audio_service.utils
