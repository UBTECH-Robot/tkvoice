#!/usr/bin/env python3

from datetime import datetime
import struct
from socket import *
import signal
import os
import threading
import wave
from queue import Queue, Empty
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from audio_message.msg import AudioFrame
from audio_service.socket_audio_provider import SocketAudioProvider
import signal

class SocketAudioPublisher(Node):
    def __init__(self):        
        super().__init__('audio_publisher')
        self.publisher_ = self.create_publisher(AudioFrame, 'audio_frames', 10)
        self.sentence_publisher_ = self.create_publisher(AudioFrame, 'audio_sentence_frames', 10)
        self.declare_parameter('save_audio', False)
        self.save_audio = self.get_parameter('save_audio').get_parameter_value().bool_value

        self.audio_provider = SocketAudioProvider('10.42.0.127', 9080)
        self.stop_event = threading.Event()

        self.audio_files_dir = "audio_files"

        self.pcm_file = None
        self.wav_file = None

        self.audio = None
        self.stream = None
        
        # 音频参数
        self.sample_rate = 16000
        self.channels = 1
        self.bit_depth = 16
        
        # 音频缓存
        self.audio_buffer = bytearray()
        
        if self.save_audio:
            self.audio_queue = Queue()
            # 清理旧文件
            self.clear_old_files()
            self.saving_thread = threading.Thread(target=self.keep_saving_wav_pcm_file)
            self.saving_thread.start()
            self.get_logger().info(f"音频保存功能已启用，音频文件将保存在{self.audio_files_dir}目录下")
        else:
            self.audio_queue = None
            self.saving_thread = None
            self.get_logger().info(f"音频保存功能未启用，使用 ros2 run audio_service audio_publisher --ros-args -p save_audio:=true 命令可启用音频保存功能")

        self.receive_pub_thread = threading.Thread(target=self.keep_receiving_publish_audio)
        self.receive_pub_thread.start()    
        self.get_logger().info("AudioPublisher 节点成功启动")

    def ensure_directories(self):
        """确保音频文件目录存在"""
        os.makedirs(self.audio_files_dir, exist_ok=True)

    def clear_old_files(self):
        """清理旧的音频文件"""
        self.ensure_directories()

        for file in os.listdir(self.audio_files_dir):
            try:
                os.remove(os.path.join(self.audio_files_dir, file))
            except Exception as e:
                self.get_logger().info(f"删除文件失败: {e}")

    def get_new_name(self, dir_name):
        """生成新的音频文件名"""
        timestamp = datetime.now().strftime('%H%M%S%f')[:-3]  # 时分秒+毫秒（保留3位）
        filename = os.path.join(dir_name, f"audio_{timestamp}")
        self.pcm_file = f"{filename}.pcm"
        self.wav_file = f"{filename}.wav"
    
    def save_wav_file(self, audio_data):
        """保存音频数据为WAV文件"""
        if not audio_data:
            self.get_logger().info("没有音频数据可保存")
            return
        
        self.get_new_name(self.audio_files_dir)
        
        try:
            with wave.open(self.wav_file, 'wb') as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(self.bit_depth // 8)
                wf.setframerate(self.sample_rate)
                wf.writeframes(audio_data)
            self.get_logger().info(f"已转换为WAV格式: {self.wav_file}")
        except Exception as e:
            self.get_logger().info(f"保存WAV文件失败: {e}")

    def save_pcm_file(self, audio_data):
        """保存音频数据为PCM文件"""
        if not audio_data:
            self.get_logger().info("没有音频数据可保存")
            return        
        
        try:
            with open(self.pcm_file, 'ab') as pcm_file:
                pcm_file.write(audio_data)
            self.get_logger().info(f"已保存PCM文件: {self.pcm_file}")
        except Exception as e:
            self.get_logger().info(f"保存PCM文件失败: {e}")

    def keep_saving_wav_pcm_file(self):
        while not self.stop_event.is_set():
            try:
                audio_data = self.audio_queue.get(timeout=2)
                try:
                    if audio_data is None:
                        continue
                    self.ensure_directories()

                    self.save_wav_file(audio_data)
                    self.save_pcm_file(audio_data)
                except Exception as e:
                    self.get_logger().info(f"保存音频文件时发生错误: {e}")
                finally:
                    self.audio_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                self.get_logger().info(f'keep_saving_wav_file循环错误: {e}')

    def close(self):
        self.stop_event.set()
        self.audio_provider.close()
        if self.saving_thread and self.saving_thread.is_alive():
            self.saving_thread.join()

    def keep_receiving_publish_audio(self):
        """持续接收音频数据并处理"""
        while not self.stop_event.is_set():
            audio_res = self.audio_provider.read()
            if audio_res is None:
                continue

            audio_data, vad = audio_res
            if vad == 1:
                self.get_logger().debug("开始说话，先清空缓存，然后缓存音频数据")
                self.audio_buffer.clear()
                self.audio_buffer.extend(audio_data)
                self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
            elif vad == 2:
                self.get_logger().debug("持续说话，继续缓存音频数据")
                self.audio_buffer.extend(audio_data)
                self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
            elif vad == 3:
                self.audio_buffer.extend(audio_data)
                sentence_audio_data = bytes(self.audio_buffer)
                if self.save_audio and self.audio_queue is not None:
                    self.audio_queue.put(sentence_audio_data)
                self.publish_sentence_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, sentence_audio_data)
                self.publish_audio(vad, 0, self.channels, self.bit_depth, self.sample_rate, bytes(audio_data))
                self.get_logger().debug("结束说话，已发布音频数据到 audio_sentence_frames 话题")

    def publish_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.publisher_.publish(msg)
        # self.get_logger().info(f"已发布帧#{frame_id}，VAD={vad}，长度={len(audio_bytes)}B")

    def build_frame(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = AudioFrame()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.vad = vad
        msg.frame_id = frame_id
        msg.sample_rate = sample_rate
        msg.channels = channels
        msg.bit_depth = bit_depth
        msg.data = list(audio_bytes)  # 注意必须是 List[int]，不能直接赋 bytes
        return msg

    def publish_sentence_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.sentence_publisher_.publish(msg)
        # self.get_logger().info(f"已发布句子帧#{frame_id}，VAD={vad}，长度={len(audio_bytes)}B")
    
def main(args=None):
    rclpy.init(args=args)
    audio_publisher = SocketAudioPublisher()

    stop_called = False

    def stop_handle():
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True

        print("接收到终止信号，准备终止程序...")

        audio_publisher.close()
        audio_publisher.destroy_node()
        print("节点已销毁，正在关闭 rclpy...")
        if rclpy.ok():
            rclpy.shutdown()

    signal.signal(signal.SIGTERM, lambda *args: stop_handle())

    try:
        rclpy.spin(audio_publisher)
    except KeyboardInterrupt:
        print("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()

# colcon build --packages-select audio_message audio_service
# source install/setup.bash

# ros2 run audio_service audio_publisher --ros-args -p save_audio:=true
# ros2 run audio_service audio_publisher
