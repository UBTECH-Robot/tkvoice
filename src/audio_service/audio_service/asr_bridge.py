#!/usr/bin/env python3
import rclpy, json, os, time
from rclpy.node import Node
from std_msgs.msg import String

ASR_FILE = '/debug/tkvoice/asr_request.json'

class ASRBridge(Node):
    def __init__(self):
        super().__init__('asr_bridge')
        self.sub = self.create_subscription(String, 'asr_sentence', self.on_asr, 10)
        self.get_logger().info('ASR Bridge started, writing to %s' % ASR_FILE)
    def on_asr(self, msg):
        text = msg.data.strip()
        if not text:
            return
        data = json.dumps({'text': text, 'time': time.time()})
        with open(ASR_FILE, 'w') as f:
            f.write(data)
        self.get_logger().info('ASR: %s' % text[:60])

def main():
    rclpy.init()
    node = ASRBridge()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
