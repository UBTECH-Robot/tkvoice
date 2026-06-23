import os
import sys as _sys
import time
import numpy as np
import torch
import pyaudio
from pathlib import Path
from audio_service.audio_file_saver import AudioFileSaverMixin
from audio_service.utils import AudioPlayer

from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

COSYVOICE_DIR = os.environ.get("COSYVOICE_DIR", os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))
COSYVOICE_MODEL_DIR = os.environ.get("COSYVOICE_MODEL_DIR", "/home/nvidia/CosyVoice2-0.5B")
COSYVOICE_SPEAKER = os.environ.get("COSYVOICE_SPEAKER", "default_speaker")
MATCHA_DIR = os.environ.get("MATCHA_DIR", os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'matcha')))
TTS_GAIN = float(os.environ.get("TTS_GAIN", "2.5"))
TTS_NORMALIZE = os.environ.get("TTS_NORMALIZE", "1") == "1"
COSYVOICE_FP16 = os.environ.get("COSYVOICE_FP16", "1") == "1"


class CosyVoiceProvider(AudioFileSaverMixin):
    def __init__(self, model_path=None, init_player=False):
        _sys.path.insert(0, os.path.normpath(os.path.join(MATCHA_DIR, '..')))
        _sys.path.insert(0, COSYVOICE_DIR)

        self.model_dir = os.path.join(COSYVOICE_DIR, COSYVOICE_MODEL_DIR)
        if not os.path.exists(self.model_dir):
            self.model_dir = os.path.join(os.getcwd(), COSYVOICE_MODEL_DIR)

        self.audio_files_dir = str(Path('audio_files'))
        self.set_audio_params(sample_rate=24000, channels=1, sample_width=2)

        os.chdir(COSYVOICE_DIR)
        from cosyvoice.cli.cosyvoice import CosyVoice2

        start_time = time.time()
        try:
            self.cosyvoice = CosyVoice2(self.model_dir, fp16=COSYVOICE_FP16, load_jit=COSYVOICE_FP16)
            self.sample_rate = self.cosyvoice.sample_rate
            sample_rate, channels, sample_width = self.get_audio_param()
            self.set_audio_params(sample_rate=sample_rate, channels=channels, sample_width=sample_width)
            elapsed = time.time() - start_time
            logging.info(f"[TTS] CosyVoice2 模型加载完成，用时 {elapsed:.2f} 秒")
        except Exception as e:
            logging.error(f"[TTS] 模型加载失败: {e}")
            raise

        self.spk_id = COSYVOICE_SPEAKER
        spk_list = self.cosyvoice.list_available_spks()
        if self.spk_id not in spk_list:
            if spk_list:
                self.spk_id = spk_list[0]
                logging.info(f"[TTS] 使用已有说话人: {self.spk_id}")
            else:
                self._create_default_speaker()
                logging.info(f"[TTS] 创建默认说话人: {self.spk_id}")

        self.init_player = init_player
        self.pyaudio_instance = None
        self.audio_stream = None

        if self.init_player:
            self.pyaudio_instance = pyaudio.PyAudio()
            device_info = self.pyaudio_instance.get_default_output_device_info()
            self.audio_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                output_device_index=device_info['index']
            )

    def _create_default_speaker(self):
        prompt_speech_16k = torch.zeros(1, 16000)
        embedding = self.cosyvoice.frontend._extract_spk_embedding(prompt_speech_16k)
        self.cosyvoice.frontend.spk2info[self.spk_id] = {'embedding': embedding}
        self.cosyvoice.save_spkinfo()

    def get_audio_param(self) -> tuple:
        return self.sample_rate, self.channels, self.sample_width

    def tts(self, text: str) -> bytes:
        if not text or not text.strip():
            return b''
        _t0 = time.time()
        try:
            audio_bytes_list = []
            for result in self.cosyvoice.inference_sft(text, self.spk_id, stream=False):
                speech = result['tts_speech']
                audio_np = speech.squeeze().cpu().numpy()
                if TTS_NORMALIZE:
                    _rms = np.sqrt(np.mean(audio_np ** 2) + 1e-8)
                    _target_rms = 0.12
                    if _rms > 1e-6:
                        audio_np = audio_np * (_target_rms / _rms)
                audio_int16 = np.clip(audio_np * TTS_GAIN * 32767, -32768, 32767).astype(np.int16)
                audio_bytes_list.append(audio_int16.tobytes())
            _dt = time.time() - _t0
            _dur = len(b''.join(audio_bytes_list)) / 2 / self.sample_rate if audio_bytes_list else 0
            logging.info(f'[TTS] 耗时: {_dt:.2f}s, 语音: {_dur:.1f}s, RTF: {_dt/_dur:.2f}')
            return b''.join(audio_bytes_list)
        except Exception as e:
            logging.error(f"[TTS] 生成音频失败: {e}")
            return b''

    def play(self, waveform: bytes):
        try:
            self.audio_stream.write(waveform)
        except Exception as e:
            logging.error(f"音频播放失败: {e}")

    def close(self):
        if self.audio_stream:
            self.audio_stream.stop_stream()
            self.audio_stream.close()
        if self.pyaudio_instance is not None:
            self.pyaudio_instance.terminate()
            self.pyaudio_instance = None


def main(args=None):
    tts_service = None
    audio_player = None
    try:
        tts_service = CosyVoiceProvider(init_player=True)
        sample_rate, channels, sample_width = tts_service.sample_rate, tts_service.channels, tts_service.sample_width
        audio_player = AudioPlayer(sample_rate=sample_rate, channels=channels, sample_width=sample_width)
        text = "你需要我给你讲个笑话让你放松一下吗,或者喝一杯咖啡怎么样"
        wavs = tts_service.tts(text)
        tts_service.save_wav_file(
            wavs,
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width,
        )
        tts_service.save_pcm_file(wavs)
        audio_player.play(wavs)

        while tts_service.is_speaking():
            time.sleep(1)

    except KeyboardInterrupt:
        print("Ctrl C stop the programe, exit.")
    except Exception as e:
        print(f"[TTS] 服务报错：{e}")
    finally:
        if tts_service:
            tts_service.close()
        if audio_player:
            audio_player.close()


if __name__ == '__main__':
    main()
