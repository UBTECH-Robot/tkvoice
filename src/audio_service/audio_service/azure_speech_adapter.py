from datetime import datetime
import azure.cognitiveservices.speech as speechsdk
# pip install azure-cognitiveservices-speech pydub python-dotenv pyaudio
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
    """
    Convert audio bytes to 16kHz, mono, 16-bit PCM format.
    
    Supports multiple audio formats (WAV, MP3, FLAC, OGG, etc.)
    Requires: ffmpeg or libav installed on the system
    
    Args:
        audio_bytes: Raw audio file bytes (any format supported by pydub/ffmpeg)
        
    Returns:
        bytes: Pure PCM audio data (no headers) in 16kHz, mono, 16-bit format
        
    Raises:
        ValueError: If audio cannot be parsed or converted
    """
    try:
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        return audio.raw_data
    except FileNotFoundError as e:
        raise ValueError(f"ffmpeg not found. Please install ffmpeg: sudo apt install ffmpeg") from e
    except Exception as e:
        raise ValueError(f"Failed to parse/convert audio data: {e}") from e
    
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
            logging.info(f"endpoint loaded: {endpoint}")
            logging.info(f"LANGUAGE loaded: {LANGUAGE}")
            logging.info(f"VOICE_NAME loaded: {VOICE_NAME}")

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
        Execute speech recognition on audio bytes and return recognized text.
        
        This method can be safely called repeatedly in a while True loop.
        
        Args:
            audio_bytes: Raw PCM audio bytes in the following format:
                        - Sample rate: 16kHz
                        - Channels: 1 (mono)
                        - Bit depth: 16-bit
                        - Encoding: PCM (little-endian)
                        
        Returns:
            str: Recognized text, or empty string if no speech detected
            
        Note:
            If your audio is in WAV format or has different parameters,
            use _ensure_pcm16k() to convert it first:
                pcm_data = _ensure_pcm16k(wav_bytes)
                text = adapter.to_text(pcm_data)
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

    def tts(self, text: str, save_audio: bool = False):
        """
        Synthesize text to speech and return PCM bytes and WAV data.
        
        Args:
            text: The text to synthesize
            save_audio: Whether to save the synthesized audio as PCM file (default: False)
        
        Returns:
            Tuple of (pcm_data, wav_data):
            - pcm_data: Raw PCM audio bytes (16kHz 16bit mono format) for playback
            - wav_data: Complete WAV format data (with header) for file storage
        """
        if not hasattr(self, 'synthesizer'):
            logging.info("Speech synthesis not initialized yet.")
            return b"", b"", None
        
        logging.info(f'[{threading.current_thread().name}] [{text}] Starting TTS synthesis - {datetime.now().strftime("%H:%M:%S")}')
        result = self.synthesizer.speak_text_async(text).get()

        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # audio_data is complete WAV format data (including WAV header)
            wav_data = result.audio_data
            wav_header_size = 44
            pcm_data = wav_data[wav_header_size:]  # Extract raw PCM data by removing WAV header
            
            
            # Save PCM audio file if requested
            if save_audio:
                logging.info(f"Saving synthesized audio to file (text: '{text}')")
                self.get_new_name()

                self.save_pcm_file(pcm_data)
                self.save_wav_file(wav_data)
            
            return pcm_data, wav_data, None # self.extract_wav_params(wav_data)
        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            logging.info("Speech synthesis canceled: {}".format(cancellation_details.reason))
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                logging.info("Error details: {}".format(cancellation_details.error_details))
            return b"", b"", None

    def get_new_name(self):
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]  # 时分秒+毫秒（保留3位）
        filename = os.path.join(self.saved_audio_dir, f"audio_{timestamp}")
        self.pcm_file = f"{filename}.pcm"
        self.wav_file = f"{filename}.wav"


    def save_wav_file(self, wav_data=None):
        """
        Save WAV format audio data directly to file.
        
        Args:
            wav_data: Complete WAV format data (with header). If None, uses the last synthesized WAV data.
        """
        data_to_save = wav_data
        
        if not data_to_save:
            logging.warning("No WAV audio data available to save")
            return
                
        try:
            # Write WAV data directly to file (no need to set metadata - header already included)
            with open(self.wav_file, 'wb') as wf:
                wf.write(data_to_save)
            logging.info(f"WAV audio file saved: {self.wav_file} (size: {len(data_to_save)} bytes)")
        except Exception as e:
            logging.error(f"Failed to save WAV file {self.wav_file}: {e}")

    def save_pcm_file(self, audio_data):
        """
        Save PCM audio data to a file.
        
        Args:
            audio_data: PCM audio bytes to save
        """
        if not audio_data:
            logging.warning("No audio data to save")
            return        
        
        try:
            with open(self.pcm_file, 'ab') as pcm_file:
                pcm_file.write(audio_data)
            logging.info(f"PCM audio file saved: {self.pcm_file} (size: {len(audio_data)} bytes)")
        except Exception as e:
            logging.error(f"Failed to save PCM file {self.pcm_file}: {e}")
    
    @staticmethod
    def extract_wav_params(wav_data: bytes) -> dict:
        """
        Extract audio parameters from WAV format data.
        
        Args:
            wav_data: Complete WAV format data (with header)
            
        Returns:
            Dictionary containing:
            - sample_rate: Audio sample rate (Hz)
            - channels: Number of audio channels
            - sample_width: Sample width in bytes
            - frames_per_buffer: Suggested buffer size (calculated from sample rate)
        """
        try:
            with wave.open(io.BytesIO(wav_data), 'rb') as wf:
                params = {
                    'sample_rate': wf.getframerate(),
                    'channels': wf.getnchannels(),
                    'sample_width': wf.getsampwidth(),
                    'frames_per_buffer': wf.getframerate() // 16  # Adaptive buffer size
                }
                logging.info(f"Extracted WAV parameters: {params['sample_rate']}Hz, "
                           f"{params['channels']}ch, {params['sample_width']*8}bit")
                return params
        except Exception as e:
            logging.error(f"Failed to extract WAV parameters: {e}")
            # Return default values on error
            return {
                'sample_rate': 16000,
                'channels': 1,
                'sample_width': 2,
                'frames_per_buffer': 1024
            }


def test_stt(adapter: AzureSpeechAdapter, audio_path: str):
    """
    Test speech-to-text (STT) functionality.
    
    Args:
        adapter: AzureSpeechAdapter instance
        audio_path: Path to audio file (PCM or WAV format)
    """
    print("=== Azure Speech STT Demo ===")
    print(f"Audio file: {audio_path}\n")
    
    if not os.path.exists(audio_path):
        print(f"✗ Error: Audio file not found: {audio_path}")
        return
    
    try:
        # Read audio file
        with open(audio_path, 'rb') as f:
            audio_bytes = f.read()
        
        print(f"Audio file loaded: {len(audio_bytes)} bytes")
        
        # Check if it's WAV format and convert to PCM if needed
        if audio_path.lower().endswith('.wav'):
            print("Detected WAV format, extracting PCM data...")
            try:
                pcm_data = _ensure_pcm16k(audio_bytes)
                audio_bytes = pcm_data
                print(f"Converted to PCM: {len(audio_bytes)} bytes")
            except Exception as e:
                print(f"⚠ Warning: Could not convert WAV to PCM: {e}")
                print("Attempting to use audio data as-is...")
        
        # Perform speech recognition
        print("\nRecognizing speech...")
        start_time = time.time()
        recognized_text = adapter.to_text(audio_bytes)
        elapsed_time = time.time() - start_time
        
        # Display results
        print(f"\n{'='*60}")
        if recognized_text:
            print(f"✓ Recognition successful (took {elapsed_time:.2f}s)")
            print(f"\nRecognized text:\n{recognized_text}")
        else:
            print(f"✗ No speech recognized (took {elapsed_time:.2f}s)")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n✗ Error during speech recognition: {e}")
        import traceback
        traceback.print_exc()


def test_tts(adapter: AzureSpeechAdapter, save_audio: bool = False):
    """
    Test text-to-speech (TTS) functionality.
    
    Args:
        adapter: AzureSpeechAdapter instance
        save_audio: Whether to save synthesized audio to file
    """
    print("=== Azure Speech TTS Demo ===")
    print(f"Save audio mode: {save_audio}\n")
    
    # AudioPlayer will be initialized/reinitialized as needed based on audio format
    audio_player = None
    current_audio_params = None

    while True:
        try:
            # Prompt user input
            text = input("Please enter the text to synthesize: ").strip()
            
            if not text:
                print("Input is empty, please try again\n")
                continue
            
            # Call TTS to synthesize speech with save_audio parameter
            print(f"Synthesizing: {text}")
            pcm_data, wav_data, wav_params = adapter.tts(text, save_audio=save_audio)
            
            if pcm_data:
                # Check if audio format has changed (or first time initialization)
                if current_audio_params is None or current_audio_params != wav_params:
                    if current_audio_params is None:
                        print("Initializing AudioPlayer with audio format from synthesized data...")
                    else:
                        print(f"⚠ Audio format changed! Reinitializing AudioPlayer...")
                        print(f"  Previous: {current_audio_params['sample_rate']}Hz, "
                                f"{current_audio_params['channels']}ch, {current_audio_params['sample_width']*8}bit")
                        print(f"  Current:  {wav_params['sample_rate']}Hz, "
                                f"{wav_params['channels']}ch, {wav_params['sample_width']*8}bit")
                        # Close old player if exists
                        if audio_player:
                            audio_player.close()
                    
                    # Create new AudioPlayer with updated parameters
                    audio_player = AudioPlayer(**wav_params)
                    current_audio_params = wav_params.copy()
                    print(f"AudioPlayer initialized: {wav_params['sample_rate']}Hz, "
                            f"{wav_params['channels']}ch, {wav_params['sample_width']*8}bit\n")
                
                audio_player.play(pcm_data)
                print(f"✓ Synthesis successful, generated {len(pcm_data)} bytes of PCM data (WAV size: {len(wav_data)} bytes)")
            else:
                print("✗ Synthesis failed\n")
                
        except EOFError:
            # Handle end of input stream (e.g., pipe input)
            break
        
if __name__ == "__main__":
    from dotenv import load_dotenv
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Azure Speech SDK Demo - Test TTS and STT functionality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test TTS (text-to-speech)
  python3 azure_speech_adapter.py --mode tts --save-audio true
  
  # Test STT (speech-to-text) with audio file
  python3 azure_speech_adapter.py --mode stt --path audio.wav
  python3 azure_speech_adapter.py --mode stt --path /absolute/path/to/audio.pcm
        """
    )
    parser.add_argument('--mode', type=str, choices=['tts', 'stt'], default='tts',
                        help="Test mode: 'tts' for text-to-speech, 'stt' for speech-to-text (default: tts)")
    parser.add_argument('--save-audio', type=lambda x: x.lower() == 'true', default=False,
                        help="[TTS mode] Save synthesized audio to file (true/false, default: false)")
    parser.add_argument('--path', type=str, default=None,
                        help="[STT mode] Path to audio file for speech recognition (required for STT mode)")
    args = parser.parse_args()
    
    # Validate arguments based on mode
    if args.mode == 'stt' and not args.path:
        parser.error("--path is required when using --mode stt")
    
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
        print(f"Voice: {adapter.speech_config.speech_synthesis_voice_name}")
        print(f"Endpoint: {adapter.speech_config.endpoint_id}\n")
        
        # Run appropriate test based on mode
        if args.mode == 'tts':
            test_tts(adapter, save_audio=args.save_audio)
        elif args.mode == 'stt':
            test_stt(adapter, audio_path=args.path)
                
    except KeyboardInterrupt:
        print("\n\nProgram exited")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()


# sudo apt install portaudio19-dev python3-dev build-essential -y
# pip install azure-cognitiveservices-speech pydub python-dotenv pyaudio

# Usage examples:
# Test TTS (text-to-speech):
#   python3 azure_speech_adapter.py --mode tts
#   python3 azure_speech_adapter.py --mode tts --save-audio true
#
# Test STT (speech-to-text):
#   python3 azure_speech_adapter.py --mode stt --path audio.wav
#   python3 azure_speech_adapter.py --mode stt --path saved_audio/mic_audio_213630433.wav