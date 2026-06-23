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
        # 待机时输出极低音量提示音，避免“完全静音”。
        # idle_tone_hz 主要影响待机底噪的音色，不是决定起播延迟的主变量。值越大声音越尖锐，值越小声音越低沉，过高过低都可能更容易被人耳察觉。440Hz是常见的A4音高，通常不算刺耳。可以根据实际听感调整。
        self.idle_tone_hz = 440.0
        # idle_tone_amplitude 越大，空闲时越容易听到底噪，也越可能维持音频链路"已唤醒"状态。
        self.idle_tone_amplitude = 0.0 # 改为0，避免句子间的底噪
        # warmup_tone_seconds 直接影响首句前的额外等待时长；越长，越不容易吞字，但延迟越明显。
        self.warmup_tone_seconds = 0.0 # 改为0，去掉句子间的预热音
        # warmup_tone_hz 主要影响预热音的听感和频谱分布，不是决定延迟的主变量。
        # 频率越高通常越容易被人耳察觉，频率较低通常更不刺耳。
        self.warmup_tone_hz = 330.0
        # warmup_tone_amplitude 决定预热唤醒强度；越大越容易把链路"叫醒"，但预热声也越明显。
        self.warmup_tone_amplitude = 0.0 # 改为0
        # warmup_guard_seconds 是预热结束后、正式语音开始前额外插入的保护静默。
        # 它几乎只增加延迟，用来给设备/缓冲留出最后一点稳定时间。
        self.warmup_guard_seconds = 0.0 # 改为0
        # 正常音频切块时长（秒）：块越小越容易被打断，但调度开销会略增加
        self.play_chunk_seconds = 0.04

        self.output_sample_rate = self._select_output_sample_rate(sample_rate)
        self.output_channels = self._select_output_channels(channels)
        self.output_sample_width = sample_width

        # Map sample width/format to PyAudio format
        self.format = self._get_pyaudio_format(self.output_sample_width, audio_format)

        self.stream_lock = threading.Lock()
        self.playing_stream = self.open_stream()

        self.stop_event = threading.Event()
        self.playback_state_lock = threading.Lock()
        self.playback_deadline = 0.0
        # 播音结束后的额外静默窗口（秒），用于屏蔽回声在管道中的传播延迟：
        # mic → socket → VAD → FunASR识别 → topic发布，合计约 1~2s
        self.post_speaking_mute_seconds = 2.0
        self.post_speech_mute_deadline = 0.0
        self.output_latency_seconds = self._get_output_latency_seconds()
        self.stream_was_idle = True
        self.idle_chunk = self._build_tone_chunk(
            tone_hz=self.idle_tone_hz,
            amplitude=self.idle_tone_amplitude,
            duration_seconds=self.frames_per_buffer / float(self.output_sample_rate),
        )
        self.warmup_chunk = self._build_tone_chunk(
            tone_hz=self.warmup_tone_hz,
            amplitude=self.warmup_tone_amplitude,
            duration_seconds=self.warmup_tone_seconds,
            fade_edges=True,
        )
        self.warmup_guard_chunk = bytes(
            max(1, int(round(self.output_sample_rate * self.warmup_guard_seconds)))
            * self.output_channels
            * self.output_sample_width
        )

        self.playing_thread = threading.Thread(target=self.keep_playing_audio, daemon=True)
        self.playing_thread.start()
        logging.info(
            f"音频播放线程已启用 - 输入:{self.sample_rate}Hz/{self.channels}ch/{self.sample_width*8}bit, "
            f"输出:{self.output_sample_rate}Hz/{self.output_channels}ch/{self.output_sample_width*8}bit"
        )

    def is_speaking(self) -> bool:
        """Check if audio is currently playing or has pending chunks to play."""
        # 1. Check if there's pending audio in the queue
        current_audioid = self.get_audioid()
        if self._has_pending_audio(current_audioid):
            return True

        # 2. Check if audio is still being played from hardware buffer
        with self.playback_state_lock:
            return time.monotonic() < self.playback_deadline

    def is_in_post_speech_mute(self) -> bool:
        """Check if we are in the post-speech echo suppression window.

        After TTS finishes playing, the speaker echo travels through:
        mic → socket → VAD buffer → FunASR (0.5~1s) → topic publish.
        During this window the ASR result is echo, not real user speech.
        This returns True only after is_speaking() is already False.
        """
        if self.is_speaking():
            return False
        with self.playback_state_lock:
            return time.monotonic() < self.post_speech_mute_deadline
    
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

    def _select_output_sample_rate(self, preferred_rate: int) -> int:
        return preferred_rate

    def _select_output_channels(self, preferred_channels: int) -> int:
        max_output_channels = int(self.device_info.get('maxOutputChannels', preferred_channels) or preferred_channels)
        if preferred_channels == 1 and max_output_channels >= 2:
            logging.info("输出声道提升为 2 声道，以贴近常见 USB 声卡原生播放格式")
            return 2
        return max(1, min(preferred_channels, max_output_channels))

    def _pcm_dtype(self):
        if self.sample_width == 1:
            return np.uint8
        if self.sample_width == 2:
            return np.int16
        raise ValueError(f"暂不支持的 sample_width: {self.sample_width}")

    def _normalize_pcm(self, samples: np.ndarray) -> np.ndarray:
        if self.sample_width == 1:
            return (samples.astype(np.float32) - 128.0) / 128.0
        if self.sample_width == 2:
            return samples.astype(np.float32) / 32768.0
        raise ValueError(f"暂不支持的 sample_width: {self.sample_width}")

    def _denormalize_pcm(self, samples: np.ndarray) -> bytes:
        clipped = np.clip(samples, -1.0, 1.0)
        if self.output_sample_width == 1:
            return (clipped * 127.0 + 128.0).astype(np.uint8).tobytes()
        if self.output_sample_width == 2:
            return (clipped * 32767.0).astype(np.int16).tobytes()
        raise ValueError(f"暂不支持的 output sample_width: {self.output_sample_width}")

    def _resample_audio(self, samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if source_rate <= 0 or target_rate <= 0 or source_rate == target_rate:
            return samples

        source_frames = samples.shape[0]
        if source_frames <= 1:
            return np.repeat(samples, max(1, int(round(target_rate / max(source_rate, 1)))), axis=0)

        target_frames = max(1, int(round(source_frames * target_rate / float(source_rate))))
        source_positions = np.arange(source_frames, dtype=np.float32)
        target_positions = np.linspace(0, source_frames - 1, target_frames, dtype=np.float32)
        channels = []
        for channel_index in range(samples.shape[1]):
            channels.append(np.interp(target_positions, source_positions, samples[:, channel_index]))
        return np.stack(channels, axis=1).astype(np.float32)

    def _convert_audio_for_output(self, audio_data: bytes) -> bytes:
        input_frame_size = self.channels * self.sample_width
        if input_frame_size <= 0 or not audio_data:
            return b''

        valid_length = len(audio_data) - (len(audio_data) % input_frame_size)
        if valid_length <= 0:
            return b''
        if valid_length != len(audio_data):
            audio_data = audio_data[:valid_length]

        dtype = self._pcm_dtype()
        samples = np.frombuffer(audio_data, dtype=dtype)
        if self.channels > 1:
            samples = samples.reshape(-1, self.channels)
        else:
            samples = samples.reshape(-1, 1)

        normalized = self._normalize_pcm(samples)

        if self.channels == 1 and self.output_channels == 2:
            normalized = np.repeat(normalized, 2, axis=1)
        elif self.channels == 2 and self.output_channels == 1:
            normalized = normalized.mean(axis=1, keepdims=True)
        elif self.channels != self.output_channels:
            if self.output_channels > self.channels:
                normalized = np.tile(normalized, (1, self.output_channels))[:, :self.output_channels]
            else:
                normalized = normalized[:, :self.output_channels]

        resampled = self._resample_audio(normalized, self.sample_rate, self.output_sample_rate)
        return self._denormalize_pcm(resampled.reshape(-1))

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
        bytes_per_second = self.output_sample_rate * self.output_channels * self.output_sample_width
        if bytes_per_second <= 0:
            return

        chunk_duration = len(audio_data) / bytes_per_second
        with self.playback_state_lock:
            now = time.monotonic()
            if now >= self.playback_deadline:
                # 没有正在播放的音频，从当前时间开始，计一次硬件输出延迟
                self.playback_deadline = now + chunk_duration + self.output_latency_seconds
            else:
                # 音频已在播放管道中，只追加本块时长，不重复累加硬件延迟
                self.playback_deadline += chunk_duration
            # 每次推送音频块都同步更新回声静默窗口截止时间
            self.post_speech_mute_deadline = self.playback_deadline + self.post_speaking_mute_seconds
        
    def open_stream(self):
        with self.stream_lock:
            last_exc = None
            # Find pipewire device if available
            pw_idx = None
            for i in range(self.audio.get_device_count()):
                name = self.audio.get_device_info_by_index(i).get('name', '').lower()
                if 'pipewire' in name:
                    pw_idx = i
                    break
            devices_to_try = [(self.device_info['index'], self.device_info['name'])]
            if pw_idx is not None and pw_idx != self.device_info['index']:
                devices_to_try.append((pw_idx, 'pipewire'))
            for dev_idx, dev_name in devices_to_try:
                try:
                    logging.info(f'尝试音频输出设备: [{dev_idx}] {dev_name}')
                    stream = self.audio.open(
                        format=self.format,
                        rate=self.output_sample_rate,
                        channels=self.output_channels,
                        output=True,
                        output_device_index=dev_idx,
                        frames_per_buffer=self.frames_per_buffer
                    )
                    logging.info(f'使用音频输出设备: [{dev_idx}] {dev_name}')
                    return stream
                except OSError as e:
                    logging.info(f'设备 [{dev_idx}] {dev_name} 打开失败: {e}')
                    last_exc = e
                    time.sleep(1)
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
            # 用户主动打断时立即清除回声静默窗口，确保新问题能被立刻接受
            self.post_speech_mute_deadline = 0.0

    def close(self):
        self.stop_event.set()
        self.playing_thread.join(timeout=2)
        with self.playback_state_lock:
            self.playback_deadline = 0.0
            self.post_speech_mute_deadline = 0.0

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

        output_audio_data = self._convert_audio_for_output(audio_data)
        if not output_audio_data:
            return

        frame_size = self.output_channels * self.output_sample_width
        if frame_size <= 0:
            return

        # 按小块入队，降低单次 write 的阻塞时长，提升切换/打断响应
        chunk_frames = max(1, int(self.output_sample_rate * self.play_chunk_seconds))
        chunk_bytes = chunk_frames * frame_size
        target_audioid = audioid if audioid is not None else self.get_audioid()

        valid_length = len(output_audio_data) - (len(output_audio_data) % frame_size)
        if valid_length <= 0:
            return

        for offset in range(0, valid_length, chunk_bytes):
            self.try_put(target_audioid, output_audio_data[offset: offset + chunk_bytes])

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

    def _build_tone_chunk(self, tone_hz: float, amplitude: float, duration_seconds: float, fade_edges: bool = False) -> bytes:
        """Generate a low-volume tone chunk used for idle keepalive or short stream warmup."""
        n_frames = max(1, int(round(self.output_sample_rate * duration_seconds)))
        n_samples = n_frames * self.output_channels
        
        if amplitude <= 0:
            return bytes(n_samples * self.output_sample_width)
        
        envelope = 1.0
        if fade_edges and n_frames > 8:
            envelope = np.hanning(n_frames).astype(np.float32)

        if self.output_sample_width == 2:
            peak = int(32767 * amplitude)
            if peak <= 0:
                peak = 1
            t = np.arange(n_frames, dtype=np.float32) / float(self.output_sample_rate)
            wave = (np.sin(2 * np.pi * tone_hz * t) * envelope * peak).astype(np.int16)
            if self.output_channels > 1:
                wave = np.repeat(wave, self.output_channels)
            return wave.tobytes()

        if self.output_sample_width == 1:
            peak = int(127 * amplitude)
            if peak <= 0:
                peak = 1
            t = np.arange(n_frames, dtype=np.float32) / float(self.output_sample_rate)
            wave = (128 + np.sin(2 * np.pi * tone_hz * t) * envelope * peak).astype(np.uint8)
            if self.output_channels > 1:
                wave = np.repeat(wave, self.output_channels)
            return wave.tobytes()

        return bytes(n_samples * self.output_sample_width)

    def keep_playing_audio(self):
        while not self.stop_event.is_set():
            if not self.playing_stream.is_active():
                self.playing_stream.start_stream()
                continue
            queue = None
            try:
                q_text = self.get_audioid()
                if q_text not in self.audio_queues_map:
                    with self.stream_lock:
                        self.playing_stream.write(self.idle_chunk)
                    self.stream_was_idle = True
                    continue
                queue = self.audio_queues_map.get(q_text)
                if queue is None:
                    with self.stream_lock:
                        self.playing_stream.write(self.idle_chunk)
                    self.stream_was_idle = True
                    continue
                audio_data = queue.get_nowait()
            except Empty:
                with self.stream_lock:
                    self.playing_stream.write(self.idle_chunk)
                self.stream_was_idle = True
                continue

            try:
                if audio_data is None:
                    with self.stream_lock:
                        self.playing_stream.write(self.idle_chunk)
                    break
                if self.stream_was_idle and self.warmup_chunk:
                    self._mark_audio_playing(self.warmup_chunk)
                    with self.stream_lock:
                        self.playing_stream.write(self.warmup_chunk)
                    if self.warmup_guard_chunk:
                        self._mark_audio_playing(self.warmup_guard_chunk)
                        with self.stream_lock:
                            self.playing_stream.write(self.warmup_guard_chunk)
                self._mark_audio_playing(audio_data)
                with self.stream_lock:
                    self.playing_stream.write(audio_data)
                self.stream_was_idle = False

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
