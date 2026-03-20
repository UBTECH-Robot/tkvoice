#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This file integrates or directly depends on Piper-TTS (GPL-3.0 license).
# Therefore, it is licensed under the GNU General Public License v3 or later.

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
from audio_service.piper_provider import PiperProvider
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

        self.answer_text_queue = Queue()
        self.audio_segment_queue = Queue()

        self.answer_text_queue_lock = threading.Lock()
        self.asr_sentence_queue = Queue(maxsize=1)
        self.tts_worker_count = max(1, int(os.environ.get("TTS_WORKERS", "5")))
        
        # Current request ID for synchronization (using UUID instead of text to handle duplicate questions)
        self.current_request_id = None
        self.request_id_lock = threading.Lock()

        # CRITICAL: Initialize TTS service first to get audio parameters
        self.tts_service = PiperProvider()
        sample_rate, channels, sample_width = self.tts_service.get_audio_param()
        self.get_logger().info(f"音频参数: 采样率={sample_rate}Hz, 声道={channels}, 位深={sample_width*8}bit")

        # Initialize AudioPlayer with actual audio parameters from TTS
        self.audio_player = AudioPlayer(
            sample_rate=sample_rate,
            channels=channels,
            sample_width=sample_width
        )
        self.llm_client = LLMClient()
        self.interrupt_words = ["天工", "天空", "天宫"]
        # Now start worker threads (they depend on the services initialized above)
        self.question_to_answer_thread = threading.Thread(target=self.keep_question_to_answer_by_ollama, name="NLP", daemon=True)
        self.question_to_answer_thread.start()

        self.tts_threads = []
        for index in range(self.tts_worker_count):
            thread = threading.Thread(target=self.keep_answer_to_audio, name=f"TTS-{index + 1}", daemon=True)
            thread.start()
            self.tts_threads.append(thread)

        self.audio_playback_thread = threading.Thread(target=self.keep_audio_segments_in_order, name="PLAYBACK", daemon=True)
        self.audio_playback_thread.start()

        self.get_logger().info(f"AudioProcess node started with {self.tts_worker_count} TTS worker(s)")

    def _drain_queue(self, queue_obj: Queue):
        while True:
            try:
                queue_obj.get_nowait()
            except Empty:
                break

    def _is_current_request(self, request_id: str) -> bool:
        return bool(self.audio_player) and self.audio_player.get_audioid() == request_id

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
            self._drain_queue(self.answer_text_queue)
            self._drain_queue(self.audio_segment_queue)
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
        self._drain_queue(self.answer_text_queue)
        self._drain_queue(self.audio_segment_queue)
        
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
                    sequence_index = 0
                    for chunk in self.llm_client.stream_sentence(question_text):
                        # Check if we should stop (node shutdown or new question arrived)
                        if self.stop_event.is_set():
                            self.get_logger().info(f'Node shutting down, stopping LLM output')
                            break
                            
                        if not chunk or not chunk.strip():
                            continue
                        
                        # Check if a new request has arrived (using UUID comparison)
                        if not self._is_current_request(request_id):
                            self.get_logger().info(f'New question arrived, interrupting LLM output - {datetime.now().strftime("%H:%M:%S")}')
                            self._drain_queue(self.answer_text_queue)
                            self._drain_queue(self.audio_segment_queue)
                            break
                        
                        self.answer_text_queue.put((request_id, sequence_index, chunk))
                        sequence_index += 1
                        
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

    def keep_answer_to_audio(self):
        """Worker thread: Convert LLM text responses to audio segments"""
        while not self.stop_event.is_set():
            try:
                request_id, sequence_index, answer_text = self.answer_text_queue.get(timeout=0.1)
                
                self.get_logger().debug(f'[{threading.current_thread().name}] Retrieved sentence from queue')
                
                try:
                    if answer_text is None:
                        continue

                    answer_text_str = answer_text if isinstance(answer_text, str) else answer_text.data
                    if not answer_text_str or not answer_text_str.strip():
                        continue

                    if not self._is_current_request(request_id):
                        self.get_logger().debug('Response interrupted before synthesis started, discarding text segment')
                        continue
                    
                    pcm_bytes = self.tts_service.tts(answer_text_str)
                    if not pcm_bytes:
                        continue
                    
                    # Verify this response is still for the current request (not interrupted)
                    if not self._is_current_request(request_id):
                        self.get_logger().debug(f'Response interrupted, discarding audio segment')
                        continue
                    
                    self.audio_segment_queue.put((request_id, sequence_index, answer_text_str, pcm_bytes))
                    self.get_logger().debug(f'[{threading.current_thread().name}] [{answer_text_str}] Synthesized audio segment #{sequence_index}')

                except Exception as e:
                    self.get_logger().error(f"[{threading.current_thread().name}] TTS conversion or playback error: {e}")
                    traceback.print_exc()
                    
            except Empty:
                # Timeout - continue to check stop_event
                continue
            except Exception as e:
                self.get_logger().error(f'[{threading.current_thread().name}] keep_answer_to_audio loop error: {e}')
                traceback.print_exc()
                time.sleep(0.01)  # Brief pause before retry on unexpected error

    def keep_audio_segments_in_order(self):
        """Worker thread: Queue synthesized audio for playback in sentence order"""
        pending_segments = {}
        next_sequence_by_request = {}
        active_request_id = None

        while not self.stop_event.is_set():
            current_request_id = self.audio_player.get_audioid() if self.audio_player else None
            if current_request_id != active_request_id:
                active_request_id = current_request_id
                pending_segments.clear()
                next_sequence_by_request.clear()

            try:
                request_id, sequence_index, answer_text_str, pcm_bytes = self.audio_segment_queue.get(timeout=0.1)
            except Empty:
                continue
            except Exception as e:
                self.get_logger().error(f'[{threading.current_thread().name}] keep_audio_segments_in_order loop error: {e}')
                traceback.print_exc()
                time.sleep(0.01)
                continue

            try:
                if not self._is_current_request(request_id):
                    self.get_logger().debug('Discarding synthesized audio for interrupted request')
                    continue

                request_segments = pending_segments.setdefault(request_id, {})
                request_segments[sequence_index] = (answer_text_str, pcm_bytes)
                next_sequence = next_sequence_by_request.setdefault(request_id, 0)

                while next_sequence in request_segments:
                    if not self._is_current_request(request_id):
                        pending_segments.pop(request_id, None)
                        next_sequence_by_request.pop(request_id, None)
                        break

                    ready_text, ready_pcm = request_segments.pop(next_sequence)
                    self.audio_player.play(ready_pcm, audioid=request_id)
                    self.get_logger().info(f'[{threading.current_thread().name}] [{ready_text}] Queued for playback - {datetime.now().strftime("%H:%M:%S")}')
                    next_sequence += 1
                    next_sequence_by_request[request_id] = next_sequence
            except Exception as e:
                self.get_logger().error(f'[{threading.current_thread().name}] keep_audio_segments_in_order processing error: {e}')
                traceback.print_exc()

    def close(self):
        """Gracefully shutdown worker threads and cleanup resources"""
        self.get_logger().info("Starting to close AudioProcess...")
        
        # Signal threads to stop
        self.stop_event.set()
        
        # Interrupt any ongoing LLM operations
        try:
            if self.llm_client:
                self.llm_client.set_interrupted(True)
                self.llm_client.close()
        except Exception as e:
            self.get_logger().error(f"Error closing LLM client: {e}")
        
        # Wait for threads to finish with timeout to avoid hanging
        # Check if we're in the NLP thread itself (can happen during signal handling)
        if self.question_to_answer_thread and self.question_to_answer_thread.is_alive():
            if threading.current_thread() == self.question_to_answer_thread:
                self.get_logger().warning("Cannot join NLP thread from within itself, skipping join")
            else:
                self.get_logger().info("Waiting for NLP thread to finish...")
                self.question_to_answer_thread.join(timeout=3)
                if self.question_to_answer_thread.is_alive():
                    self.get_logger().warning("NLP thread did not finish within 3 seconds")

        for thread in self.tts_threads:
            if thread and thread.is_alive():
                if threading.current_thread() == thread:
                    self.get_logger().warning(f"Cannot join {thread.name} thread from within itself, skipping join")
                else:
                    self.get_logger().info(f"Waiting for {thread.name} thread to finish...")
                    thread.join(timeout=2)
                    if thread.is_alive():
                        self.get_logger().warning(f"{thread.name} thread did not finish within 2 seconds")

        if self.audio_playback_thread and self.audio_playback_thread.is_alive():
            if threading.current_thread() == self.audio_playback_thread:
                self.get_logger().warning("Cannot join PLAYBACK thread from within itself, skipping join")
            else:
                self.get_logger().info("Waiting for PLAYBACK thread to finish...")
                self.audio_playback_thread.join(timeout=2)
                if self.audio_playback_thread.is_alive():
                    self.get_logger().warning("PLAYBACK thread did not finish within 2 seconds")
        
        # Cleanup audio player
        try:
            if self.audio_player:
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

        import traceback
        print("接收到终止信号，调用栈：")
        traceback.print_stack()

        tk_audio_process.close()
        tk_audio_process.destroy_node()
        print("节点已销毁，正在关闭 rclpy...")
        if rclpy.ok():
            rclpy.shutdown()

    signal.signal(signal.SIGTERM, lambda *args: stop_handle())

    try:
        rclpy.spin(tk_audio_process)
    except KeyboardInterrupt:
        print("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()


# for development and testing:
# rm -rf build install log && colcon build --packages-select audio_message audio_service
# source install/setup.bash
# MODEL_DIR=/home/nvidia/tkvoice/res/ ros2 launch audio_service asr_llm_tts_process_launch.py