#!/usr/bin/env python3

import os
from queue import Queue, Empty
import threading
import time
import traceback
from rclpy.node import Node
from datetime import datetime
from audio_message.msg import AudioFrame
import rclpy
# from audio_service.utils import FunASRClient
from audio_service.funasr_client import FunASRClient
from std_msgs.msg import String
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
import signal

qos = QoSProfile(
    depth=10,
    reliability=ReliabilityPolicy.RELIABLE,
    history=HistoryPolicy.KEEP_LAST,
)

class FunASRTextPublisher(Node):
    def __init__(self):
        super().__init__('tk_asr_text_publisher')
        self.subscription = self.create_subscription(
            AudioFrame,
            'audio_sentence_frames',
            self.audio_sentence_callback,
            10
        )
        self.asr_sentence_publisher = self.create_publisher(String, '/asr_sentence', qos)

        self.subscription  # prevent unused variable warning
        self.get_logger().info("FunASRTextPublisher 节点已启动，正在订阅 audio_sentence_frames")
        self.stop_event = threading.Event()

        self.audio_queue = Queue(maxsize=1)
        self.process_thread = threading.Thread(target=self.keep_process_audio)
        self.process_thread.start()
        self.ignore_words = ["嗯", "啊", "哦", "恩", "唔", "噢", "呃", "哈", "嘿", "呀", "的", "了", "嘛", "吧"]

        self.asr_service = FunASRClient(
            host="192.168.41.1",
            port=10097,
        )

    def keep_process_audio(self):
        while not self.stop_event.is_set():
            try:
                msg = self.audio_queue.get(timeout=2)
                try:
                    if msg is None:
                        continue
                    
                    audio_bytes = bytes(msg.data)
                    self.get_logger().info(f'从 audio_sentence_frames 收 len[{len(audio_bytes)}], 识别...{datetime.now().strftime("%H:%M:%S")}')

                    asr_sentence = self.asr_service.to_text(audio_bytes)
                    
                    if asr_sentence:
                        if len(asr_sentence) <= 3 or (len(asr_sentence) <= 4 and any(word in asr_sentence for word in self.ignore_words)):
                            self.get_logger().info(f'忽略过短[{asr_sentence}]-{datetime.now().strftime("%H:%M:%S")}')
                            continue
                        text_msg = String()
                        text_msg.data = asr_sentence
                        self.asr_sentence_publisher.publish(text_msg)
                        self.get_logger().info(f'已发布[{asr_sentence}]-{datetime.now().strftime("%H:%M:%S")}')

                except Exception as e:
                    self.get_logger().info(f"音频转化为文本并发布到话题时发生错误: {e}")
                    traceback.print_exc()
                finally:
                    self.audio_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                self.get_logger().info(f'keep_process_audio循环错误: {e}')

    def close(self):
        self.stop_event.set()
        if self.process_thread and self.process_thread.is_alive():
            self.process_thread.join()


    def audio_sentence_callback(self, msg: AudioFrame):
        if not msg.data:
            self.get_logger().warn("收到空音频数据")
            return
        self.audio_queue.put(msg)
        # self.get_logger().info(f"收到非空的音频数据已放入队列: {len(msg.data)}")


def main(args=None):
    rclpy.init(args=args)
    tk_audio_process = FunASRTextPublisher()

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
        print("开始接收音频数据...")
        rclpy.spin(tk_audio_process)
    except KeyboardInterrupt:
        print("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()

# colcon build --packages-select audio_message audio_service
# source install/setup.bash
# ros2 launch audio_service funasr_text_launch.py
