from datetime import datetime
import azure.cognitiveservices.speech as speechsdk
# pip install azure-cognitiveservices-speech
import threading
import time
import wave
from typing import Optional
import os
import sys
from pydub import AudioSegment
import io

# 支持直接运行脚本：将父目录添加到sys.path以找到audio_service包
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from audio_service.log_config import setup_logger
from audio_service.utils import AudioPlayer

logging = setup_logger(__name__)

def _ensure_pcm16k(audio_bytes):
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        return audio.raw_data
    except Exception as e:
        raise ValueError(f"无法解析音频数据: {e}")
    
class AzureSpeechAdapter:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # 双重锁检查，保证线程安全且只创建一个实例
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    """
    封装 Azure Speech SDK，实现对 bytes 音频流的语音识别。
    支持多次调用 asr()，适用于持续识别循环场景。
    """

    def __init__(self, speech_key: Optional[str] = None, region: Optional[str] = None, endpoint: Optional[str] = None):
        SPEECH_KEY = os.environ.get("SPEECH_KEY")
        ENDPOINT = os.environ.get("ENDPOINT")
        LANGUAGE = os.environ.get("LANGUAGE", "en-US")
        VOICE_NAME = os.environ.get("VOICE_NAME", "en-US-AndrewMultilingualNeural")
        if hasattr(self, "_initialized") and self._initialized:
            return
        
        speech_key = SPEECH_KEY
        endpoint = ENDPOINT
        if not (speech_key and (region or endpoint)):
            raise ValueError("必须提供 speech_key 和 region 或 endpoint")

        if endpoint:
            self.speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=endpoint)
        else:
            self.speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=region)

        # self.speech_config.speech_recognition_language = "en-US"
        # self.speech_config.speech_synthesis_voice_name = "en-US-AndrewMultilingualNeural"

        self.speech_config.speech_recognition_language = LANGUAGE #"zh-CN"
        self.speech_config.speech_synthesis_voice_name = VOICE_NAME #"zh-CN-YunxiNeural"

        # self.speech_config.speech_recognition_language = "sl-SI"
        # self.speech_config.speech_synthesis_voice_name = "sl-SI-RokNeural"
        # https://learn.microsoft.com/zh-cn/azure/ai-services/speech-service/language-support?tabs=tts

        self.speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Riff16Khz16BitMonoPcm
        )

        # 控制识别流程的锁（防止并发）
        self._asr_lock = threading.Lock()
        self.synthesizer = speechsdk.SpeechSynthesizer(speech_config=self.speech_config, audio_config=None)
        self._initialized = True

        self.saved_audio_dir = "saved_audio"
        os.makedirs(self.saved_audio_dir, exist_ok=True)

    def to_text(self, audio_bytes: bytes) -> str:
        """
        执行语音识别。输入 PCM bytes，返回识别文本。
        该方法可以安全地在 while True 循环中持续调用。
        """
        with self._asr_lock:
            stream = speechsdk.audio.PushAudioInputStream()
            audio_config = speechsdk.audio.AudioConfig(stream=stream)
            recognizer = speechsdk.SpeechRecognizer(
                speech_config=self.speech_config, audio_config=audio_config
            )

            # 用于阻塞等待识别完成
            recognition_done = threading.Event()
            recognized_text = {"text": ""}

            def recognized_cb(evt):
                if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                    recognized_text["text"] = evt.result.text
                    # logging.info(f"[Recognized] {evt.result.text}")
                elif evt.result.reason == speechsdk.ResultReason.NoMatch:
                    logging.info("[NoMatch] 未识别到语音")

            def session_stopped_cb(evt):
                logging.info("[ASR session stopped]")
                recognition_done.set()

            # 绑定事件回调
            recognizer.recognized.connect(recognized_cb)
            recognizer.session_stopped.connect(session_stopped_cb)
            # recognizer.canceled.connect(lambda evt: logging.info(f"[Canceled] {evt}"))

            # 启动连续识别
            recognizer.start_continuous_recognition()

            # 写入音频数据
            stream.write(audio_bytes)
            stream.close()

            # 等待识别完成（最多 10 秒）
            recognition_done.wait(timeout=10)

            # 停止识别
            recognizer.stop_continuous_recognition()

            return recognized_text["text"]

    def tts(self, text: str) -> bytes:
        """
        合成文本为语音，返回可用 pyaudio 播放的 PCM bytes（16kHz 16bit 单声道）
        """
        if not hasattr(self, 'synthesizer'):
            logging.info("Speech synthesis not initialized yet.")
            return b""
        
        result = self.synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data  # bytes
            wav_header_size = 44
            pcm_data = audio_data[wav_header_size:]
            # self.save_pcm_file(pcm_data)
            return pcm_data
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            logging.info("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                logging.info("Error details: {}".format(cancellation_details.error_details))
            return b""

    def get_new_name(self):
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]  # 时分秒+毫秒（保留3位）
        filename = os.path.join(self.saved_audio_dir, f"audio_{timestamp}")
        self.pcm_file = f"{filename}.pcm"

    def save_pcm_file(self, audio_data):
        if not audio_data:
            logging.info("no audio data to save")
            return        
        
        self.get_new_name()
        try:
            with open(self.pcm_file, 'ab') as pcm_file:
                pcm_file.write(audio_data)
            # logging.info(f"saved PCM file: {self.pcm_file}")
        except Exception as e:
            logging.info(f"failed to save {self.pcm_file}: {e}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    
    print("=== Azure Speech TTS Demo ===")
    
    # Load the .env.example file from the project root directory
    project_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
    env_file = os.path.join(project_root, ".env")
    
    if os.path.exists(env_file):
        load_dotenv(env_file)
        print(f"✓ env var loaded: {env_file}")
    else:
        print(f"⚠ env file not found: {env_file}")
        print("Please ensure environment variables are set: SPEECH_KEY, ENDPOINT")
    
    print("Press Ctrl+C to exit\n")
    
    try:
        # Initialize Azure Speech Adapter
        adapter = AzureSpeechAdapter()
        print(f"Initialization successful! Language: {adapter.speech_config.speech_recognition_language}")
        print(f"Voice: {adapter.speech_config.speech_synthesis_voice_name}\n")
        
        audio_player = AudioPlayer()

        while True:
            try:
                # Prompt user input
                text = input("Please enter the text to synthesize: ").strip()
                
                if not text:
                    print("Input is empty, please try again\n")
                    continue
                
                # Call TTS to synthesize speech
                print(f"Synthesizing: {text}")
                pcm_data = adapter.tts(text)
                
                if pcm_data:
                    audio_player.play(pcm_data)
                    print(f"✓ Synthesis successful, generated {len(pcm_data)} bytes of PCM data")
                else:
                    print("✗ Synthesis failed\n")
                    
            except EOFError:
                # Handle end of input stream (e.g., pipe input)
                break
                
    except KeyboardInterrupt:
        print("\n\nProgram exited")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


# python azure_speech_adapter.py