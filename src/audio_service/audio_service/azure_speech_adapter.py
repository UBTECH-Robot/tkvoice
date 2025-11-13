import azure.cognitiveservices.speech as speechsdk
# pip install azure-cognitiveservices-speech
import threading
import time
import wave
from typing import Optional
import os
from pydub import AudioSegment
import io
from audio_service.log_config import setup_logger
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
            return pcm_data
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            logging.info("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                logging.info("Error details: {}".format(cancellation_details.error_details))
            return b""
