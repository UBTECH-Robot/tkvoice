#!/usr/bin/env python3

import json
import math
import struct
from pathlib import Path
import signal
import threading
from queue import Queue, Empty
import rclpy
from rclpy.node import Node
from std_msgs.msg import Header
from audio_message.msg import AudioFrame
from audio_service.audio_file_saver import AudioFileSaverMixin

try:
    from lyre_msgs.msg import AudioFrame as LyreAudioFrame
    from lyre_msgs.msg import LyreVoiceActivity
    from lyre_msgs.srv import AudioControl
    LYRE_MSGS_AVAILABLE = True
except ImportError:
    LYRE_MSGS_AVAILABLE = False
    LyreAudioFrame = None
    LyreVoiceActivity = None
    AudioControl = None


def calc_amplitude(audio_bytes: bytes, sample_width: int = 2) -> float:
    """计算 PCM 音频的平均绝对振幅"""
    if len(audio_bytes) < sample_width:
        return 0.0
    if sample_width == 2:
        count = len(audio_bytes) // 2
        samples = struct.unpack('<' + 'h' * count, audio_bytes[:count * 2])
    elif sample_width == 1:
        samples = audio_bytes
    else:
        return 0.0
    return sum(abs(s) for s in samples) / len(samples)


class LyreAudioPublisher(Node, AudioFileSaverMixin):
    def __init__(self, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2):
        super().__init__('tk_audio_publisher')
        self.publisher_ = self.create_publisher(AudioFrame, 'audio_frames', 10)
        self.sentence_publisher_ = self.create_publisher(AudioFrame, 'audio_sentence_frames', 10)
        self.declare_parameter('save_audio', False)
        self.save_audio = self.get_parameter('save_audio').get_parameter_value().bool_value

        self.declare_parameter('amp_threshold', 600)
        self.declare_parameter('silence_timeout_ms', 1500)
        self.declare_parameter('min_speech_ms', 300)
        self.declare_parameter('max_speech_ms', 30000)
        self.amp_threshold = self.get_parameter('amp_threshold').value
        self.silence_timeout_ns = self.get_parameter('silence_timeout_ms').value * 1000000
        self.min_speech_ns = self.get_parameter('min_speech_ms').value * 1000000
        self.max_speech_ns = self.get_parameter('max_speech_ms').value * 1000000

        self.stop_event = threading.Event()
        self.audio_files_dir = str(Path('audio_files'))

        self.set_audio_params(sample_rate=sample_rate, channels=channels, sample_width=sample_width)

        self.audio_buffer = bytearray()
        self.is_in_speech = False
        self.frame_counter = 0
        self.last_speech_time = self.get_clock().now()
        self.speech_start_time = self.get_clock().now()

        if not LYRE_MSGS_AVAILABLE:
            self.get_logger().error("lyre_msgs 不可用，请确保已 source 机器人 SDK 的 ROS2 环境")
            return

        self.audio_control_client = self.create_client(AudioControl, '/lyre/audio_control')
        while not self.audio_control_client.wait_for_service(timeout_sec=5):
            self.get_logger().warn('等待 /lyre/audio_control 服务...')
        req = AudioControl.Request()
        req.enable = True
        future = self.audio_control_client.call_async(req)
        future.add_done_callback(self._on_audio_control_response)

        self.lyre_audio_sub = self.create_subscription(
            LyreAudioFrame, '/lyre/audio_stream', self.on_lyre_audio, 10
        )
        self.voice_activity_sub = self.create_subscription(
            LyreVoiceActivity, '/lyre/voice_activity', self.on_voice_activity, 10
        )

        if self.save_audio:
            self.audio_queue = Queue()
            self.clear_old_files()
            self.saving_thread = threading.Thread(target=self.keep_saving_wav_pcm_file)
            self.saving_thread.start()
            self.get_logger().info(f"音频保存功能已启用，音频文件将保存在{self.audio_files_dir}目录下")
        else:
            self.audio_queue = None
            self.saving_thread = None
            self.get_logger().info(f"音频保存功能未启用，使用 --ros-args -p save_audio:=true 可启用")

        self.get_logger().info(
            f"LyreAudioPublisher 启动, amp_threshold={self.amp_threshold}, "
            f"silence_timeout={self.get_parameter('silence_timeout_ms').value}ms, "
            f"min_speech={self.get_parameter('min_speech_ms').value}ms"
        )

    def _on_audio_control_response(self, future):
        try:
            response = future.result()
            if response.success:
                self.get_logger().info("已通过 /lyre/audio_control 启用音频流")
            else:
                self.get_logger().error(f"启用音频流失败: {response.message}")
        except Exception as e:
            self.get_logger().error(f"音频控制服务调用失败: {e}")

    def on_voice_activity(self, msg):
        """仅用于调试日志，VAD 改用本地能量检测"""
        try:
            data = json.loads(msg.content)
            content = data.get("content", {})
            event_type = content.get("eventType", 0)
            if event_type == 4:
                self.get_logger().info("检测到关键词唤醒")
            elif event_type == 5:
                self.get_logger().info("检测到退出对话")
        except Exception:
            pass

    def on_lyre_audio(self, msg):
        audio_bytes = bytes(msg.data)
        self.frame_counter += 1

        now = self.get_clock().now()
        amp = calc_amplitude(audio_bytes, msg.bits_per_sample // 8)
        is_voice = amp > self.amp_threshold

        if is_voice:
            self.last_speech_time = now
            if not self.is_in_speech:
                self.is_in_speech = True
                self.audio_buffer.clear()
                self.speech_start_time = now
                self.get_logger().info(f"本地VAD: 开始说话 (amp={amp:.0f})")
            self.audio_buffer.extend(audio_bytes)
            self.publish_audio(2, self.frame_counter, msg.channels, msg.bits_per_sample, msg.sample_rate, audio_bytes)

            if (now - self.speech_start_time).nanoseconds > self.max_speech_ns:
                self.get_logger().info("说话超时，强制结束句子")
                self.finalize_sentence(msg)
        else:
            vad = 0
            if self.is_in_speech:
                silence_duration = (now - self.last_speech_time).nanoseconds
                speech_duration = (now - self.speech_start_time).nanoseconds
                if silence_duration > self.silence_timeout_ns and speech_duration > self.min_speech_ns:
                    self.get_logger().info(f"本地VAD: 结束说话, 句子时长={speech_duration / 1e6:.0f}ms")
                    self.finalize_sentence(msg)
                    return
                else:
                    # 静音期间继续累积（可能在句子中间停顿）
                    self.audio_buffer.extend(audio_bytes)
                    self.publish_audio(2, self.frame_counter, msg.channels, msg.bits_per_sample, msg.sample_rate, audio_bytes)
                    return
            self.publish_audio(vad, self.frame_counter, msg.channels, msg.bits_per_sample, msg.sample_rate, audio_bytes)

    def finalize_sentence(self, msg):
        self.is_in_speech = False
        if self.audio_buffer:
            sentence_audio = bytes(self.audio_buffer)
            if self.save_audio and self.audio_queue is not None:
                self.audio_queue.put(sentence_audio)
            self.publish_sentence_audio(3, 0, msg.channels, msg.bits_per_sample, msg.sample_rate, sentence_audio)
            self.get_logger().info(f"已发布句子音频，长度={len(sentence_audio)}B")

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
        if self.saving_thread and self.saving_thread.is_alive():
            self.saving_thread.join()

    def publish_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.publisher_.publish(msg)

    def build_frame(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = AudioFrame()
        msg.header = Header()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.vad = vad
        msg.frame_id = frame_id
        msg.sample_rate = sample_rate
        msg.channels = channels
        msg.bit_depth = bit_depth
        msg.data = list(audio_bytes)
        return msg

    def publish_sentence_audio(self, vad: int, frame_id: int, channels: int, bit_depth: int, sample_rate: int, audio_bytes: bytes):
        msg = self.build_frame(vad, frame_id, channels, bit_depth, sample_rate, audio_bytes)
        self.sentence_publisher_.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    tk_audio_publisher = LyreAudioPublisher()

    stop_called = False

    def stop_handle():
        nonlocal stop_called
        if stop_called:
            return
        stop_called = True
        print("接收到终止信号，准备终止程序...")
        tk_audio_publisher.close()
        tk_audio_publisher.destroy_node()
        print("节点已销毁，正在关闭 rclpy...")
        if rclpy.ok():
            rclpy.shutdown()

    signal.signal(signal.SIGTERM, lambda *args: stop_handle())

    try:
        rclpy.spin(tk_audio_publisher)
    except KeyboardInterrupt:
        print("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()


if __name__ == '__main__':
    main()

# colcon build --packages-select audio_message audio_service
# source install/setup.bash
# ros2 run audio_service tk_audio_publisher --ros-args -p save_audio:=true
