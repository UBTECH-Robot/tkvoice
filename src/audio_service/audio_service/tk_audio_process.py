#!/usr/bin/env python3
import os
from queue import Queue, Empty, Full
import threading
from datetime import datetime
import time
import traceback
from rclpy.node import Node
import rclpy
from std_msgs.msg import String
from audio_service.utils import AudioPlayer
from audio_service.llm_client import LLMClient
from audio_service.azure_speech_adapter import AzureSpeechAdapter
import signal
import uuid

class AudioProcess(Node):
    def __init__(self):
        super().__init__('tk_audio_process')
        self.stop_event = threading.Event()
        self.asr_sentence_subscription = self.create_subscription(
            String,
            'asr_sentence',
            self.on_asr_sentence,
            10
        )
        self.asr_sentence_subscription  # prevent unused variable warning

        # Initialize queues and locks
        self.answer_text_queue = Queue()
        self.answer_text_queue_lock = threading.Lock()
        self.asr_sentence_queue = Queue(maxsize=1)
        
        # Current request ID for synchronization (using UUID instead of text to handle duplicate questions)
        self.current_request_id = None
        self.request_id_lock = threading.Lock()
        
        # CRITICAL: Initialize services BEFORE starting threads to avoid AttributeError
        # AudioPlayer uses default parameters (16kHz, mono, 16bit) which match Azure TTS output format
        # (configured as Riff16Khz16BitMonoPcm in AzureSpeechAdapter).
        # Note: If TTS output format changes at runtime, AudioPlayer would need to be reinitialized.
        # Current implementation assumes format is fixed throughout the node's lifetime.
        self.audio_player = AudioPlayer()
        self.current_audio_params = None  # To track current audio format
        self.llm_client = LLMClient()
        self.tts_service = AzureSpeechAdapter()
        
        # Parse interrupt words and filter out empty strings
        interrupt_words_raw = os.environ.get("INTERRUPT_WORDS", "").split(",")
        self.interrupt_words = [word.strip() for word in interrupt_words_raw if word.strip()]
        
        # Now start worker threads (they depend on the services initialized above)
        self.question_to_answer_thread = threading.Thread(target=self.keep_question_to_answer_by_ollama, name="NLP", daemon=True)
        self.question_to_answer_thread.start()

        self.answer_to_audio_thread = threading.Thread(target=self.keep_answer_to_audio_and_play, name="TTS", daemon=True)
        self.answer_to_audio_thread.start()

        self.get_logger().info("AudioProcess node started")
    
    def ensure_audio_player(self, wav_params):
        if not wav_params:
            self.audio_player = AudioPlayer()
            return
        if self.current_audio_params is None or self.current_audio_params != wav_params:
            if self.current_audio_params is None:
                print("Initializing AudioPlayer with audio format from synthesized data...")
            else:
                print(f"⚠ Audio format changed! Reinitializing AudioPlayer...")
                print(f"  Previous: {self.current_audio_params['sample_rate']}Hz, "
                        f"{self.current_audio_params['channels']}ch, {self.current_audio_params['sample_width']*8}bit")
                print(f"  Current:  {wav_params['sample_rate']}Hz, "
                        f"{wav_params['channels']}ch, {wav_params['sample_width']*8}bit")
                # Close old player if exists
                if self.audio_player:
                    self.audio_player.close()
            
            # Create new AudioPlayer with updated parameters
            self.audio_player = AudioPlayer(**wav_params)
            self.current_audio_params = wav_params.copy()
            print(f"AudioPlayer initialized: {wav_params['sample_rate']}Hz, "
                    f"{wav_params['channels']}ch, {wav_params['sample_width']*8}bit\n")
                

    def on_asr_sentence(self, msg: String):
        """Handle incoming ASR text with interrupt support"""
        if not msg.data:
            return

        # Check if this is an interrupt command
        interrupted = any(word in msg.data for word in self.interrupt_words)
        
        if self.audio_player and self.audio_player.is_speaking() and not interrupted:
            self.get_logger().info(f"Speaking, [{msg.data}] does not contain interrupt word, ignoring")
            return
            
        if self.audio_player and self.audio_player.is_speaking() and interrupted:
            self.get_logger().info(f"Received [{msg.data}] with interrupt word, stopping speech")
            # Generate new request ID for the interrupt
            request_id = str(uuid.uuid4())
            with self.request_id_lock:
                self.current_request_id = request_id
            
            self.audio_player.set_audioid(request_id)
            self.llm_client.set_interrupted(True)
            self.audio_player.stop_other_audio_and_clear_queue()
            return
        
        self.get_logger().info(f"Received valid question: [{msg.data}], queuing for processing")
        
        # Generate unique request ID to avoid confusion with duplicate questions
        request_id = str(uuid.uuid4())
        with self.request_id_lock:
            self.current_request_id = request_id
            
        if self.audio_player:
            self.audio_player.set_audioid(request_id)
        self.llm_client.set_interrupted(True)
        
        # Store request ID with message for tracking
        msg_with_id = (request_id, msg.data)
        try:
            self.asr_sentence_queue.put(msg_with_id, block=False)
        except Full:
            self.asr_sentence_queue.get_nowait()  # Discard oldest request
            self.asr_sentence_queue.put(msg_with_id)
        
        if self.audio_player:
            self.audio_player.stop_other_audio_and_clear_queue()

    def keep_question_to_answer_by_ollama(self):
        """Worker thread: Process ASR questions and stream LLM responses"""
        while not self.stop_event.is_set():
            try:
                # Wait for new question with timeout to check stop_event periodically
                msg_with_id = self.asr_sentence_queue.get(timeout=1)
                
                if msg_with_id is None:
                    continue
                
                request_id, question_text = msg_with_id
                if not question_text or not question_text.strip():
                    continue
                
                self.get_logger().info(f'[{threading.current_thread().name}] Question [{question_text}] starting stream output - {datetime.now().strftime("%H:%M:%S")}')
                
                try:
                    # Stream LLM response sentence by sentence
                    for chunk in self.llm_client.stream_sentence(question_text):
                        # Check if we should stop (node shutdown or new question arrived)
                        if self.stop_event.is_set():
                            self.get_logger().info(f'Node shutting down, stopping LLM output')
                            break
                            
                        if not chunk or not chunk.strip():
                            continue
                        
                        # Check if a new request has arrived (using UUID comparison)
                        if self.audio_player and request_id != self.audio_player.get_audioid():
                            self.get_logger().info(f'New question arrived, interrupting LLM output - {datetime.now().strftime("%H:%M:%S")}')
                            # Clear answer queue safely
                            with self.answer_text_queue_lock:
                                # Don't recreate Queue object - just drain it to avoid race condition
                                while not self.answer_text_queue.empty():
                                    try:
                                        self.answer_text_queue.get_nowait()
                                    except Empty:
                                        break
                            break
                        
                        # Thread-safe queue put operation
                        with self.answer_text_queue_lock:
                            self.answer_text_queue.put((request_id, chunk))
                        
                        self.get_logger().debug(f'[{threading.current_thread().name}] Queued sentence for TTS: {chunk}')
                        
                except Exception as e:
                    self.get_logger().error(f"[{threading.current_thread().name}] LLM streaming error: {e}")
                    traceback.print_exc()
                    
            except Empty:
                # Timeout - continue to check stop_event
                continue
            except Exception as e:
                self.get_logger().error(f'[{threading.current_thread().name}] keep_question_to_answer_by_ollama loop error: {e}')
                traceback.print_exc()

    def keep_answer_to_audio_and_play(self):
        """Worker thread: Convert LLM text responses to audio and play them"""
        while not self.stop_event.is_set():
            try:
                # Thread-safe queue get operation
                with self.answer_text_queue_lock:
                    request_id, answer_text = self.answer_text_queue.get(timeout=0.1)
                
                self.get_logger().debug(f'[{threading.current_thread().name}] Retrieved sentence from queue')
                
                try:
                    if answer_text is None:
                        continue

                    answer_text_str = answer_text if isinstance(answer_text, str) else answer_text.data
                    if not answer_text_str or not answer_text_str.strip():
                        continue
                    
                    pcm_bytes, wav_bytes, wav_params = self.tts_service.tts(answer_text_str)
                    
                    # self.ensure_audio_player(wav_params)

                    # Verify this response is still for the current request (not interrupted)
                    if self.audio_player.get_audioid() != request_id:
                        self.get_logger().debug(f'Response interrupted, discarding audio segment')
                        continue
                    
                    # Queue audio for playback
                    self.audio_player.play(pcm_bytes)
                    self.get_logger().info(f'[{threading.current_thread().name}] [{answer_text_str}] Queued for playback - {datetime.now().strftime("%H:%M:%S")}')

                except Exception as e:
                    self.get_logger().error(f"[{threading.current_thread().name}] TTS conversion or playback error: {e}")
                    traceback.print_exc()
                    
            except Empty:
                # Timeout - continue to check stop_event
                continue
            except Exception as e:
                self.get_logger().error(f'[{threading.current_thread().name}] keep_answer_to_audio_and_play loop error: {e}')
                traceback.print_exc()
                time.sleep(0.01)  # Brief pause before retry on unexpected error

    def close(self):
        """Gracefully shutdown worker threads and cleanup resources"""
        self.get_logger().info("Starting to close AudioProcess...")
        
        # Signal threads to stop
        self.stop_event.set()
        
        # Wait for threads to finish with timeout to avoid hanging
        if self.question_to_answer_thread and self.question_to_answer_thread.is_alive():
            self.get_logger().info("Waiting for NLP thread to finish...")
            self.question_to_answer_thread.join(timeout=3)
            if self.question_to_answer_thread.is_alive():
                self.get_logger().warning("NLP thread did not finish within 3 seconds")
                
        if self.answer_to_audio_thread and self.answer_to_audio_thread.is_alive():
            self.get_logger().info("Waiting for TTS thread to finish...")
            self.answer_to_audio_thread.join(timeout=2)
            if self.answer_to_audio_thread.is_alive():
                self.get_logger().warning("TTS thread did not finish within 2 seconds")
        
        # Cleanup audio player
        try:
            self.audio_player.close()
        except Exception as e:
            self.get_logger().error(f"Error closing audio player: {e}")
        
        self.get_logger().info("AudioProcess closed")

def main(args=None):
    rclpy.init(args=args)
    tk_audio_process = AudioProcess()
    stop_called = False

    def stop_handle():
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True

        print("Received termination signal, preparing to terminate program...")

        tk_audio_process.close()
        tk_audio_process.destroy_node()
        print("Node destroyed, shutting down rclpy...")
        if rclpy.ok():
            rclpy.shutdown()

    signal.signal(signal.SIGTERM, lambda *args: stop_handle())

    try:
        rclpy.spin(tk_audio_process)
    except KeyboardInterrupt:
        print("Received Ctrl+C, preparing to exit...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()


# rm -rf build install log && colcon build --packages-select audio_message audio_service
# source install/setup.bash
# ros2 launch audio_service asr_llm_tts_process_launch.py