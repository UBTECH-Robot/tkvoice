# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file integrates or directly depends on Piper-TTS (GPL-3.0 license).
# Therefore, it is licensed under the GNU General Public License v3 or later.

import os
os.environ["TORCHDYNAMO_DISABLE"] = "1"
os.environ["DISABLE_TORCH_COMPILE"] = "1"
import time
import numpy as np
import onnxruntime as ort
ort.set_default_logger_severity(4)
import pyaudio
from piper import PiperVoice, SynthesisConfig
from audio_service.utils import AudioPlayer
testpint = print

from audio_service.log_config import setup_logger
logging = setup_logger(__name__)
testpint = logging.info

class PiperProvider:
    def __init__(self, model_path=None, init_player=False):
        MODEL_DIR = os.environ.get("MODEL_DIR", "/home/nvidia/")
        tts_model_path = os.path.join(MODEL_DIR, "piper_voices/zh/zh_CN-huayan-medium.onnx")
        tts_config_path = os.path.join(MODEL_DIR, "piper_voices/zh/zh_CN-huayan-medium.onnx.json")
    
        self.model_path = model_path if model_path else tts_model_path
        self.tts_config_path = tts_config_path

        # self.piper_syn_config = SynthesisConfig(
        #     volume=0.5,  # 音量：值 < 1.0 是降低音量，> 1.0 是提升音量
        #     length_scale=1.0,  # 语速：值 < 1.0 表示说话更快，> 1.0 表示说话更慢
        #     noise_scale=1.0,  # 随机性：值越大，语音表现越“丰富”但也可能更“模糊”或“虚”。通常在 0.3 到 1.0 之间调节，太高会损伤清晰度
        #     noise_w_scale=1.0,  # 音素宽度的变化程度（即发音时长的自然波动）：越高则表现越“自然”，但语音不确定性也会提升
        #     normalize_audio=False, # use raw audio from voice
        # )
        # 如果想让语音更自然：尝试调高 noise_w_scale 到 0.8~1.2。
        # 如果想让语音更清晰/标准：将 noise_scale 降到 0.3~0.6。
        # 如果遇到音频过小/爆音：调整 volume 和 normalize_audio 的组合。
        self.piper_syn_config = SynthesisConfig(
            length_scale=1.1,       # 稍慢一点，增加权威感
            noise_scale=0.4,         # 低噪声，语音更清晰
            noise_w_scale=0.5,       # 降低语调波动，更平和
            normalize_audio=True,    # 保持音量平稳
            volume=1.0               # 原始音量即可
        )

        self.piper_instance = None
        self.sample_rate = 21000
        
        start_time = time.time()
        try:
            self._load_model()
            elapsed = time.time() - start_time
            testpint(f"[TTS] Piper 模型加载完成，用时 {elapsed:.2f} 秒")
        except Exception as e:
            testpint(f"[TTS] 模型加载失败: {e}")
            raise

        self.init_player = init_player
        self.pyaudio_instance = None
        self.audio_stream = None
        
        if self.init_player:
            self.pyaudio_instance = pyaudio.PyAudio()
            device_info = self.pyaudio_instance.get_default_output_device_info()
            
            self.audio_stream = self.pyaudio_instance.open(
                format=pyaudio.paFloat32,
                channels=1,
                rate=self.sample_rate,
                output=True,
                output_device_index=device_info['index']
            )

    def _load_model(self):
        self.piper_instance = PiperVoice.load(self.model_path, config_path=self.tts_config_path, use_cuda=True)
        testpint(f"[TTS] Piper 模型采样率: {self.piper_instance.config.sample_rate}")

    def tts(self, text: str) -> bytes:
        """
        使用 piper 的 synthesize() 获取音频数组（float32），直接可播放。
        """
        try:
            chunks = self.piper_instance.synthesize(text, syn_config=self.piper_syn_config)
            audio_list = [chunk.audio_float_array for chunk in chunks]
            
            if not audio_list:
                return np.array([], dtype=np.float32)

            waveform = np.concatenate(audio_list).astype(np.float32).tobytes()
            return waveform
        except Exception as e:
            testpint(f"[TTS] 生成音频失败: {e}")
            return np.array([], dtype=np.float32)
        
    def play(self, waveform: bytes):
        try:
            self.audio_stream.write(waveform)
        except Exception as e:
            testpint(f"音频播放失败: {e}")

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
        tts_service = PiperProvider(init_player=True)
        audio_player = AudioPlayer()
        text = "你你需要我给你讲个笑话让你放松一下吗,或者喝一杯咖啡怎么样"
        # text = "今天的天气阳光明媚"
        wavs = tts_service.tts(text)
        # for wav in wavs:
        # tts_service.play(wavs)
        audio_player.play(wavs)
        time.sleep(6)
        
    except KeyboardInterrupt:
        testpint("Ctrl C stop the programe, exit.")
    except Exception as e:
        testpint(f"[TTS] 服务报错：{e}")
    finally:
        if tts_service:
            tts_service.close()
        if audio_player:
            audio_player.close()

if __name__ == '__main__':
    main()

# cd /home/nvidia/voicelocal/tkvoice_release/src/audio_service
# python -m audio_service.piper_provider

