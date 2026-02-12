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
        self.answer_text_queue_lock = threading.Lock()
        self.asr_sentence_queue = Queue(maxsize=1)
        self.question_to_answer_thread = None
        self.answer_to_audio_thread = None
        
        self.question_to_answer_thread = threading.Thread(target=self.keep_question_to_answer_by_ollama, name="NLP", daemon=True)
        self.question_to_answer_thread.start()

        self.answer_to_audio_thread = threading.Thread(target=self.keep_answer_to_audio_and_play, name="TTS", daemon=True)
        self.answer_to_audio_thread.start()

        self.audio_player = AudioPlayer()
        self.llm_client = LLMClient()
        self.tts_service = AzureSpeechAdapter()

        self.get_logger().info("AudioProcess 节点已启动")
        self.interrupt_words = os.environ.get("INTERRUPT_WORDS", "").split(",")
    
    def on_asr_sentence(self, msg: String):
        if not msg.data:
            return
        # self.get_logger().info(f"收到文本: {msg.data}")

        interrupted = any(word in msg.data for word in self.interrupt_words)
        if self.audio_player.is_speaking() and not interrupted:
            self.get_logger().info(f"说话中，[{msg.data}]不包含打断词，忽略")
            return
        if self.audio_player.is_speaking() and interrupted:
            self.audio_player.set_audioid(msg.data)
            self.llm_client.set_interrupted(True)
            self.audio_player.stop_other_audio_and_clear_queue()
            self.get_logger().info(f"收到[{msg.data}]包含打断词，停止天工行者说话")

            return
        
        self.get_logger().info(f"收到有效提问：[{msg.data}]，放入队列等待处理")
            
        self.audio_player.set_audioid(msg.data)
        self.llm_client.set_interrupted(True)
        try:
            self.asr_sentence_queue.put(msg, block=False)
        except Full:
            self.asr_sentence_queue.get_nowait()  # 弹出最旧的一条
            self.asr_sentence_queue.put(msg)
        self.audio_player.stop_other_audio_and_clear_queue()

    def keep_question_to_answer_by_ollama(self):
        process_question = ""
        while not self.stop_event.is_set():

            try:
                msg = self.asr_sentence_queue.get(timeout=1)
                # self.get_logger().info(f"假装在处理收到的文本: {msg.data}")
                # self.answer_text_queue.put((msg.data, msg.data))

                # continue
                try:
                    if msg is None:
                        self.get_logger().debug(f'没有音频数据，继续等待...')
                        continue

                    process_question = msg.data
                    if not process_question or not process_question.strip():
                        continue
                    self.get_logger().info(f'[{threading.current_thread().name}] 提问[{process_question}]将要开始流式输出-{datetime.now().strftime("%H:%M:%S")}')
                    count = 0
                    for chunk in self.llm_client.stream_sentence(process_question):
                        if not chunk or not chunk.strip():
                            break
                        count += 1
                            
                        if process_question != self.audio_player.get_audioid():
                            self.get_logger().info(f'有新问题进来，打断大模型输出回答-{datetime.now().strftime("%H:%M:%S")}')
                            with self.answer_text_queue_lock:
                                self.answer_text_queue = Queue()
                            break
                        self.answer_text_queue.put((process_question, chunk))
                        # self.get_logger().info(f'[{threading.current_thread().name}] 模型输出 [{chunk}] 已放入队列待生成音频-{datetime.now().strftime("%H:%M:%S")}')

                except Exception as e:
                    self.get_logger().info(f"[{threading.current_thread().name}] 处理音频文件时发生错误: {e}")
                    traceback.print_exc()
            except Empty:
                continue
            except Exception as e:
                self.get_logger().info(f'[{threading.current_thread().name}] keep_process_asr_sentence循环错误: {e}')

    def keep_answer_to_audio_and_play(self):
        while not self.stop_event.is_set():
            try:
                answer_text = ""
                with self.answer_text_queue_lock:
                    process_question, answer_text = self.answer_text_queue.get(timeout=0.1)
                try:
                    if answer_text is None:
                        continue

                    answer_text_str = answer_text if isinstance(answer_text, str) else answer_text.data
                    if not answer_text_str or not answer_text_str.strip():
                        continue
                    # self.get_logger().debug(f'[{threading.current_thread().name}] 从队列拿出回答文本：{answer_text_str}')
                    audio_bytes = self.tts_service.tts(answer_text_str)
                    if self.audio_player.get_audioid() != process_question:
                        continue
                    self.audio_player.play(audio_bytes)
                    self.get_logger().info(f'[{threading.current_thread().name}] [{answer_text_str}] 进入播放队列-{datetime.now().strftime("%H:%M:%S")}')

                except Exception as e:
                    self.get_logger().info(f"[{threading.current_thread().name}] 处理回答文本时发生错误: {e}")
            except Empty:
                continue
            except Exception as e:
                time.sleep(0.01)
                self.get_logger().info(f'[{threading.current_thread().name}] keep_answer_to_audio_and_play循环错误: {e}')

    def close(self):
        self.stop_event.set()
        self.audio_player.close()
        if self.question_to_answer_thread and self.question_to_answer_thread.is_alive():
            self.question_to_answer_thread.join()
        if self.answer_to_audio_thread and self.answer_to_audio_thread.is_alive():
            self.answer_to_audio_thread.join(timeout=1)

def main(args=None):
    rclpy.init(args=args)
    tk_audio_process = AudioProcess()
    stop_called = False

    def stop_handle():
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True

        print("接收到终止信号，准备终止程序...")

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


# rm -rf build install log && colcon build --packages-select audio_message audio_service
# source install/setup.bash
# ros2 launch audio_service asr_llm_tts_process_launch.py