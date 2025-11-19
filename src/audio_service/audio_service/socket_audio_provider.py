#!/usr/bin/env python3

from datetime import datetime
import struct
from socket import *
from audio_service.socket_connector import SocketConnector
from audio_service.utils import AudioPlayer
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class SocketAudioProvider(SocketConnector):
    def __init__(self, ip: str, port: int):
        super().__init__(ip, port)

    def read(self):
        """
        从socket读取音频数据，解析并返回音频数据和VAD状态。
        返回值:
            audio_data: bytes - 音频数据
            vad: int - 0: "静音", 1: "开始说话", 2: "持续说话", 3: "结束说话"
        """
        try:
            header = self.receive_full_data(9)
            if not header:
                return None

            try:
                sync_head, user_id, msg_type, msg_length, msg_id = struct.unpack('<BBBIH', header)
            except struct.error as e:
                logging.error(f"解析头部出错: {e}")
                return None

            if sync_head != 0xa5 or user_id != 0x01:
                logging.info(f"头部校验失败: sync={sync_head:02x}, user={user_id:02x}")
                return None

            body = self.receive_full_data(msg_length + 1)
            if not body:
                return None

            try:
                vad = body[0]
                channel = body[1]
                frame_id = struct.unpack('<I', body[4:8])[0]
                audio_data = body[8:-1]  # 提取音频数据
            except Exception as e:
                logging.error(f"解析body出错: {e}, body长度={len(body)}")
                return None

            if channel == 0:
                return audio_data, vad
            return None

        except Exception as e:
            logging.error(f"处理异常: {e}")
            return None

def main(args=None):
    audio_provider = SocketAudioProvider('10.42.0.127', 9080)
    audio_player = AudioPlayer()
    audio_buffer = bytearray()

    def stop_handle():
        logging.info("接收到终止信号，准备终止程序...")
        audio_provider.close()
        audio_player.close()
        logging.info("节点已销毁，正在退出...")

    try:
        logging.info("开始接收原生音频数据...")
        while True:
            audio_res = audio_provider.read()
            if audio_res is None:
                continue
            audio_data, vad = audio_res
            if vad == 1:
                logging.info("开始说话，先清空缓存，然后缓存音频数据")
                audio_buffer.clear()
                audio_buffer.extend(audio_data)
            elif vad == 2:
                logging.info("持续说话，继续缓存音频数据")
                audio_buffer.extend(audio_data)
            elif vad == 3:
                logging.info("结束说话，保存音频数据")
                audio_buffer.extend(audio_data)
                sentence_audio_data = bytes(audio_buffer)
                audio_player.play(sentence_audio_data)

    except KeyboardInterrupt:
        logging.error("接收到 Ctrl+C，准备退出...")
    finally:
        stop_handle()

if __name__ == '__main__':
    main()

# cd /home/nvidia/voicelocal/tkvoice_release/src/audio_service
# python -m audio_service.socket_audio_provider

