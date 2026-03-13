from socket import *
from audio_service.log_config import setup_logger
import sys

logging = setup_logger(__name__)

class SocketConnector:
    def __init__(self, ip: str, port: int):
        self.client_socket = socket(AF_INET, SOCK_STREAM)
        self.server_ip_port = (ip, port)
        self.run = False  # 默认未连接

        try:
            self.client_socket.connect(self.server_ip_port)
            self.client_socket.settimeout(3.0)
            self.run = True
            logging.info(f"已成功连接到服务器 {ip}:{port}")
        except ConnectionRefusedError:
            logging.error(f"连接被拒绝: {ip}:{port}")
        except timeout:
            logging.error(f"连接超时: {ip}:{port}")
        except Exception as e:
            logging.error(f"连接服务器失败: {ip}:{port}, 错误: {e}")
            sys.exit(1)

    def close(self):
        self.run = False
        try:
            self.client_socket.close()
        except Exception as e:
            logging.warning(f"关闭socket时出错: {e}")
        logging.info("资源已释放")

    def receive_full_data(self, expected_length):
        received_data = bytearray()
        while len(received_data) < expected_length and self.run:
            try:
                chunk = self.client_socket.recv(min(4096, expected_length - len(received_data)))
                if not chunk:
                    logging.info("服务器关闭连接")
                    return None
                received_data.extend(chunk)
            except timeout:
                return None
            except Exception as e:
                logging.error(f"接收错误: {e}")
                return None
        return bytes(received_data)
