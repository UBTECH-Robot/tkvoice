from datetime import datetime
from pathlib import Path
import os
import wave


class AudioFileSaverMixin:
    def set_audio_params(self, sample_rate: int, channels: int, sample_width: int = None, bit_depth: int = None):
        if sample_width is None and bit_depth is None:
            raise ValueError('sample_width 和 bit_depth 不能同时为空')

        if sample_width is None:
            sample_width = int(bit_depth) // 8

        if bit_depth is None:
            bit_depth = int(sample_width) * 8

        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_width = int(sample_width)
        self.bit_depth = int(bit_depth)

    def _audio_file_logger(self):
        if hasattr(self, 'get_logger') and callable(self.get_logger):
            return self.get_logger()
        return getattr(self, 'logger', None)

    def _log_audio_file_info(self, message: str):
        logger = self._audio_file_logger()
        if logger is not None and hasattr(logger, 'info'):
            logger.info(message)

    def _resolve_audio_params(self, sample_rate=None, channels=None, sample_width=None, bit_depth=None):
        resolved_sample_rate = sample_rate if sample_rate is not None else getattr(self, 'sample_rate', None)
        resolved_channels = channels if channels is not None else getattr(self, 'channels', None)

        resolved_sample_width = sample_width if sample_width is not None else getattr(self, 'sample_width', None)
        resolved_bit_depth = bit_depth if bit_depth is not None else getattr(self, 'bit_depth', None)

        if resolved_sample_width is None and resolved_bit_depth is not None:
            resolved_sample_width = int(resolved_bit_depth) // 8

        if resolved_bit_depth is None and resolved_sample_width is not None:
            resolved_bit_depth = int(resolved_sample_width) * 8

        if resolved_sample_rate is None or resolved_channels is None or resolved_sample_width is None:
            raise ValueError('缺少音频参数，无法保存音频文件')

        return int(resolved_sample_rate), int(resolved_channels), int(resolved_sample_width), int(resolved_bit_depth)

    def ensure_directories(self):
        """确保音频文件目录存在"""
        os.makedirs(self.audio_files_dir, exist_ok=True)

    def clear_old_files(self):
        """清理旧的音频文件"""
        self.ensure_directories()

        for file_name in os.listdir(self.audio_files_dir):
            file_path = os.path.join(self.audio_files_dir, file_name)
            try:
                os.remove(file_path)
            except Exception as error:
                self._log_audio_file_info(f"删除文件失败: {error}")

    def get_new_name(self, dir_name):
        """生成新的音频文件名"""
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]
        base_name = os.path.join(dir_name, f"audio_{timestamp}")
        self.pcm_file = f"{base_name}.pcm"
        self.wav_file = f"{base_name}.wav"
        return self.wav_file, self.pcm_file

    def save_wav_file(self, audio_data, sample_rate=None, channels=None, sample_width=None, bit_depth=None):
        """保存音频数据为WAV文件"""
        if not audio_data:
            self._log_audio_file_info("没有音频数据可保存")
            return

        resolved_sample_rate, resolved_channels, resolved_sample_width, _ = self._resolve_audio_params(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
            bit_depth=bit_depth,
        )

        self.get_new_name(self.audio_files_dir)

        try:
            with wave.open(self.wav_file, 'wb') as wav_file:
                wav_file.setnchannels(resolved_channels)
                wav_file.setsampwidth(resolved_sample_width)
                wav_file.setframerate(resolved_sample_rate)
                wav_file.writeframes(audio_data)
            self._log_audio_file_info(f"已转换为WAV格式: {self.wav_file}")
            return self.wav_file
        except Exception as error:
            self._log_audio_file_info(f"保存WAV文件失败: {error}")
            return None

    def save_pcm_file(self, audio_data):
        """保存音频数据为PCM文件"""
        if not audio_data:
            self._log_audio_file_info("没有音频数据可保存")
            return

        if not getattr(self, 'pcm_file', None):
            self.get_new_name(self.audio_files_dir)

        try:
            with Path(self.pcm_file).open('ab') as pcm_file:
                pcm_file.write(audio_data)
            self._log_audio_file_info(f"已保存PCM文件: {self.pcm_file}")
        except Exception as error:
            self._log_audio_file_info(f"保存PCM文件失败: {error}")