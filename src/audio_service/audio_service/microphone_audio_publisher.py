#!/usr/bin/env python3
"""
Microphone Audio Publisher for ROS2
Captures audio from local microphone and publishes to ROS2 topics
Cross-platform: Windows 10/11, Ubuntu 22.04
"""

from datetime import datetime
import os
import threading
import wave
from queue import Queue, Empty
import signal

import numpy as np
from collections import deque

import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from audio_message.msg import AudioFrame

try:
    import pyaudio
except ImportError:
    raise ImportError("PyAudio not installed. Run: pip install pyaudio")

try:
    import webrtcvad
except ImportError:
    raise ImportError("webrtcvad not installed. Run: pip install webrtcvad")


class MicrophoneAudioProvider:
    """Cross-platform microphone audio provider with VAD support"""
    
    def __init__(self, sample_rate=16000, channels=1, chunk_duration_ms=30):
        """
        Initialize microphone audio capture
        
        Args:
            sample_rate: Audio sample rate (Hz), must be 8000, 16000, 32000, or 48000 for VAD
            channels: Number of audio channels (1 for mono)
            chunk_duration_ms: Duration of each audio chunk in milliseconds (10, 20, or 30)
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        
        # Calculate chunk size in bytes
        # For 16-bit audio: bytes = (sample_rate * chunk_duration_ms / 1000) * 2 bytes per sample
        self.chunk_size = int(sample_rate * chunk_duration_ms / 1000)
        
        # Initialize PyAudio
        self.audio = pyaudio.PyAudio()
        
        # Initialize VAD (Voice Activity Detection)
        self.vad = webrtcvad.Vad()
        self.vad.set_mode(3)  # Aggressiveness mode: 0 (least) to 3 (most aggressive), using 3 for noise reduction
        
        # VAD state tracking
        self.is_speaking = False
        self.speech_frames = 0
        self.silence_frames = 0
        self.total_speech_frames = 0  # Total frames in current speech segment
        self.speech_threshold = 12  # Increased from 5 to 12 (360ms) to avoid false triggers
        self.silence_threshold = 35  # Increased from 20 to 35 (1050ms) for more stable end detection
        
        # Audio quality thresholds
        self.min_speech_duration_ms = 500  # Minimum 500ms audio duration
        self.min_audio_energy = 300  # Minimum RMS energy threshold to filter low volume audio
        
        # Pre-buffer to avoid losing audio at the beginning of speech
        # Store recent frames before speech detection triggers
        self.pre_buffer_size = 15  # Buffer 15 frames (450ms) to capture speech start
        self.pre_buffer = deque(maxlen=self.pre_buffer_size)
        self.buffered_frames = []  # Frames to return when speech starts
        
        # Audio stream
        self.stream = None
        self.stop_event = threading.Event()
        
        print(f"Microphone audio provider initialized: {sample_rate}Hz, {channels}ch, {chunk_duration_ms}ms chunks")
    
    def start(self):
        """Start audio capture from microphone"""
        try:
            self.stream = self.audio.open(
                format=pyaudio.paInt16,  # 16-bit audio
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                stream_callback=None
            )
            print("Microphone stream started successfully")
        except Exception as e:
            print(f"Error starting microphone: {e}")
            raise
    
    def read(self):
        """
        Read audio chunk from microphone with VAD
        
        Returns:
            Tuple of (audio_data: bytes, vad_state: int, pre_buffered_frames: list) or None
            - audio_data: Current audio frame bytes
            - vad_state: 1=speech start, 2=speech continue, 3=speech end, 0=silence
            - pre_buffered_frames: List of buffered frames when speech starts (empty otherwise)
        """
        if not self.stream or self.stop_event.is_set():
            return None
        
        try:
            # Read audio chunk
            audio_data = self.stream.read(self.chunk_size, exception_on_overflow=False)
            
            # Perform VAD detection
            is_speech = self.vad.is_speech(audio_data, self.sample_rate)
            
            # Calculate audio energy (RMS)
            audio_energy = self._calculate_audio_energy(audio_data)
            
            # Update state machine
            vad_state = self._update_vad_state(is_speech, audio_energy, audio_data)
            
            # Get buffered frames if speech just started
            buffered = self.buffered_frames.copy() if self.buffered_frames else []
            if self.buffered_frames:
                self.buffered_frames.clear()
            
            return audio_data, vad_state, buffered
            
        except Exception as e:
            print(f"Error reading audio: {e}")
            return None
    
    def _calculate_audio_energy(self, audio_data):
        """
        Calculate audio energy (RMS) to detect volume level
        
        Args:
            audio_data: Raw audio bytes (16-bit PCM)
            
        Returns:
            RMS energy value
        """
        try:
            # Convert bytes to numpy array (16-bit signed integers)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            # Calculate RMS (Root Mean Square)
            rms = np.sqrt(np.mean(audio_array.astype(np.float32) ** 2))
            return rms
        except Exception:
            return 0
    
    def _update_vad_state(self, is_speech, audio_energy=0, audio_data=None):
        """
        Update VAD state machine with audio energy validation and pre-buffering
        
        Args:
            is_speech: Boolean indicating if current frame contains speech
            audio_energy: RMS energy of current frame
            audio_data: Current audio frame bytes (for pre-buffering)
            
        Returns:
            vad_state: 1=start, 2=continue, 3=end, 0=silence
        """
        # Add current frame to pre-buffer (always, for potential speech start)
        if audio_data is not None and not self.is_speaking:
            self.pre_buffer.append(audio_data)
        
        # Consider speech only if both VAD detects it AND energy is above threshold
        is_valid_speech = is_speech and audio_energy >= self.min_audio_energy
        
        if is_valid_speech:
            self.speech_frames += 1
            self.silence_frames = 0
            
            if not self.is_speaking:
                # Check if we have enough speech frames to trigger start
                if self.speech_frames >= self.speech_threshold:
                    self.is_speaking = True
                    self.total_speech_frames = self.speech_frames
                    
                    # Copy pre-buffer frames to return with speech start
                    self.buffered_frames = list(self.pre_buffer)
                    self.pre_buffer.clear()
                    
                    return 1  # Speech start
            else:
                self.total_speech_frames += 1
                return 2  # Speech continue
        else:
            self.silence_frames += 1
            self.speech_frames = 0
            
            if self.is_speaking:
                # Check if we have enough silence frames to trigger end
                if self.silence_frames >= self.silence_threshold:
                    # Validate minimum duration before ending
                    speech_duration_ms = self.total_speech_frames * self.chunk_duration_ms
                    
                    if speech_duration_ms >= self.min_speech_duration_ms:
                        self.is_speaking = False
                        self.total_speech_frames = 0
                        return 3  # Speech end (valid)
                    else:
                        # Duration too short, discard and reset
                        print(f"Audio too short ({speech_duration_ms:.0f}ms), discarding")
                        self.is_speaking = False
                        self.total_speech_frames = 0
                        self.pre_buffer.clear()  # Clear pre-buffer on discard
                        return 0  # Return to silence, audio discarded
                else:
                    return 2  # Still in speech (allow brief silence)
        
        return 0  # Silence
    
    def close(self):
        """Stop audio capture and cleanup resources"""
        self.stop_event.set()
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        
        self.audio.terminate()
        print("Microphone audio provider closed")


class MicrophoneAudioPublisher(Node):
    """ROS2 node that publishes microphone audio to topics"""
    
    def __init__(self):
        super().__init__('microphone_audio_publisher')
        
        # Publishers (same topics as socket version for compatibility)
        self.publisher_ = self.create_publisher(AudioFrame, 'audio_frames', 10)
        self.sentence_publisher_ = self.create_publisher(AudioFrame, 'audio_sentence_frames', 10)
        
        # Parameter: save_audio
        self.declare_parameter('save_audio', False)
        self.save_audio = self.get_parameter('save_audio').get_parameter_value().bool_value
        
        # Audio parameters
        self.sample_rate = 16000
        self.channels = 1
        self.bit_depth = 16
        
        # Initialize microphone provider
        self.audio_provider = MicrophoneAudioProvider(
            sample_rate=self.sample_rate,
            channels=self.channels,
            chunk_duration_ms=30
        )
        
        self.stop_event = threading.Event()
        
        # Audio buffer for sentence accumulation
        self.audio_buffer = bytearray()
        
        # Audio file saving setup
        self.audio_files_dir = "audio_files"
        self.pcm_file = None
        self.wav_file = None
        
        if self.save_audio:
            self.audio_queue = Queue()
            self.clear_old_files()
            self.saving_thread = threading.Thread(target=self.keep_saving_wav_pcm_file, daemon=True)
            self.saving_thread.start()
            self.get_logger().info(f"Audio saving enabled, files will be saved in {self.audio_files_dir} directory")
        else:
            self.audio_queue = None
            self.saving_thread = None
            self.get_logger().info("Audio saving disabled, use -p save_audio:=true to enable")
        
        # Start microphone
        try:
            self.audio_provider.start()
            self.get_logger().info("Microphone initialized successfully")
        except Exception as e:
            self.get_logger().error(f"Microphone initialization failed: {e}")
            raise
        
        # Start audio processing thread
        self.receive_pub_thread = threading.Thread(target=self.keep_receiving_publish_audio, daemon=True)
        self.receive_pub_thread.start()
        
        self.get_logger().info("MicrophoneAudioPublisher node started successfully")
        self.get_logger().info("Listening to microphone input...")
    
    def ensure_directories(self):
        """Ensure audio file directory exists"""
        os.makedirs(self.audio_files_dir, exist_ok=True)
    
    def clear_old_files(self):
        """Clear old audio files"""
        self.ensure_directories()
        
        for file in os.listdir(self.audio_files_dir):
            try:
                file_path = os.path.join(self.audio_files_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                self.get_logger().warning(f"Failed to delete file: {e}")
    
    def get_new_name(self, dir_name):
        """Generate new audio file name with timestamp"""
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]
        filename = os.path.join(dir_name, f"mic_audio_{timestamp}")
        self.pcm_file = f"{filename}.pcm"
        self.wav_file = f"{filename}.wav"
    
    def save_wav_file(self, audio_data):
        """
        Save audio data as WAV file in Azure Speech SDK compatible format.
        
        Format: 16kHz, mono, 16-bit PCM (little-endian)
        This format is directly compatible with Azure Speech recognition service.
        
        Args:
            audio_data: Raw PCM audio bytes from microphone
        """
        if not audio_data:
            self.get_logger().warning("No audio data to save")
            return
        
        self.get_new_name(self.audio_files_dir)
        
        try:
            with wave.open(self.wav_file, 'wb') as wf:
                wf.setnchannels(self.channels)  # 1 (mono)
                wf.setsampwidth(self.bit_depth // 8)  # 2 bytes (16-bit)
                wf.setframerate(self.sample_rate)  # 16000 Hz
                wf.writeframes(audio_data)
            self.get_logger().info(f"Saved WAV file: {self.wav_file} [{self.sample_rate}Hz, {self.channels}ch, {self.bit_depth}bit]")
        except Exception as e:
            self.get_logger().error(f"Failed to save WAV file: {e}")
    
    def save_pcm_file(self, audio_data):
        """
        Save audio data as raw PCM file in Azure Speech SDK compatible format.
        
        Format: 16kHz, mono, 16-bit PCM (little-endian), no header
        This format is directly compatible with Azure Speech recognition service.
        Can be used directly with azure_speech_adapter.to_text() method.
        
        Args:
            audio_data: Raw PCM audio bytes from microphone
        """
        if not audio_data:
            self.get_logger().warning("No audio data to save")
            return
        
        try:
            with open(self.pcm_file, 'wb') as pcm_file:
                pcm_file.write(audio_data)
            self.get_logger().info(f"Saved PCM file: {self.pcm_file} [{self.sample_rate}Hz, {self.channels}ch, {self.bit_depth}bit]")
        except Exception as e:
            self.get_logger().error(f"Failed to save PCM file: {e}")
    
    def keep_saving_wav_pcm_file(self):
        """Worker thread: save audio files from queue"""
        while not self.stop_event.is_set():
            try:
                audio_data = self.audio_queue.get(timeout=2)
                
                if audio_data is None:
                    continue
                
                try:
                    self.ensure_directories()
                    self.save_wav_file(audio_data)
                    self.save_pcm_file(audio_data)
                except Exception as e:
                    self.get_logger().error(f"Error occurred while saving audio files: {e}")
                finally:
                    self.audio_queue.task_done()
                    
            except Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"keep_saving_wav_pcm_file loop error: {e}")
    
    def keep_receiving_publish_audio(self):
        """Worker thread: continuously receive audio from microphone and publish"""
        while not self.stop_event.is_set():
            try:
                audio_res = self.audio_provider.read()
                if audio_res is None:
                    continue
                
                audio_data, vad, pre_buffered = audio_res
                
                if vad == 1:
                    # Speech start
                    self.get_logger().info("Speech detected, start recording")
                    self.audio_buffer.clear()
                    
                    # Add pre-buffered frames (already includes current frame at the end)
                    # Note: current frame is already in pre_buffered, so we don't add it again
                    for buffered_frame in pre_buffered:
                        self.audio_buffer.extend(buffered_frame)
                    
                    self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
                    
                elif vad == 2:
                    # Speech continue
                    self.audio_buffer.extend(audio_data)
                    self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
                    
                elif vad == 3:
                    # Speech end
                    self.audio_buffer.extend(audio_data)
                    sentence_audio_data = bytes(self.audio_buffer)
                    
                    # Calculate audio duration
                    duration_sec = len(sentence_audio_data) / (self.sample_rate * self.channels * (self.bit_depth // 8))
                    
                    self.get_logger().info(f"Speech ended, duration: {duration_sec:.2f}s, size: {len(sentence_audio_data)} bytes")
                    
                    # Only process if duration is reasonable (already filtered by VAD, but double-check)
                    if duration_sec >= 0.3:  # At least 0.3 seconds
                        # Save complete sentence audio if enabled
                        if self.save_audio and self.audio_queue is not None:
                            self.audio_queue.put(sentence_audio_data)
                        
                        # Publish complete sentence
                        self.publish_sentence_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, sentence_audio_data)
                        self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
                        
                        self.get_logger().info(f"Published complete audio sentence")
                    else:
                        self.get_logger().warning(f"Audio too short ({duration_sec:.2f}s), discarded")
                    
            except Exception as e:
                self.get_logger().error(f"Error processing audio: {e}")
    
    def build_frame(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        """Build AudioFrame message"""
        msg = AudioFrame()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.vad = vad
        msg.frame_id = frame_id
        msg.sample_rate = sample_rate
        msg.channels = channels
        msg.bit_depth = bit_depth
        msg.data = list(audio_bytes)  # Must be List[int], not bytes
        return msg
    
    def publish_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        """Publish audio frame to audio_frames topic"""
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.publisher_.publish(msg)
    
    def publish_sentence_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        """Publish complete sentence audio to audio_sentence_frames topic"""
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.sentence_publisher_.publish(msg)
    
    def close(self):
        """Gracefully shutdown the node"""
        self.get_logger().info("Shutting down MicrophoneAudioPublisher...")
        
        self.stop_event.set()
        
        # Close audio provider
        if self.audio_provider:
            self.audio_provider.close()
        
        # Wait for threads
        if self.saving_thread and self.saving_thread.is_alive():
            self.saving_thread.join(timeout=2)
        
        if self.receive_pub_thread and self.receive_pub_thread.is_alive():
            self.receive_pub_thread.join(timeout=2)
        
        self.get_logger().info("MicrophoneAudioPublisher closed")


def main(args=None):
    rclpy.init(args=args)
    
    try:
        microphone_audio_publisher = MicrophoneAudioPublisher()
    except Exception as e:
        print(f"Failed to initialize node: {e}")
        rclpy.shutdown()
        return
    
    stop_called = False
    
    def stop_handle():
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True
        
        print("\nReceived termination signal, preparing to terminate program...")
        
        microphone_audio_publisher.close()
        microphone_audio_publisher.destroy_node()
        print("Node destroyed, shutting down rclpy...")
        if rclpy.ok():
            rclpy.shutdown()
    
    signal.signal(signal.SIGTERM, lambda *args: stop_handle())
    
    try:
        rclpy.spin(microphone_audio_publisher)
    except KeyboardInterrupt:
        print("\nReceived Ctrl+C, preparing to exit...")
    finally:
        stop_handle()


if __name__ == '__main__':
    main()


# Cross-platform usage:
# 
# Build (all platforms):
# colcon build --packages-select audio_message audio_service
# source install/setup.bash  # Linux/macOS
# install\setup.bat           # Windows
#
# Run without saving audio:
# ros2 run audio_service microphone_audio_publisher
#
# Run with audio saving enabled:
# ros2 run audio_service microphone_audio_publisher --ros-args -p save_audio:=true
#
# Dependencies (install before running):
# pip install pyaudio webrtcvad
#
# On Ubuntu, you may need:
# sudo apt-get install portaudio19-dev python3-pyaudio
