from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node
import subprocess

def is_ros2_node_running(node_name):
    """
    检查 ROS2 节点是否运行。
    node_name 可以是 'tk_audio_publisher'，会匹配 /tk_audio_publisher 或 /ns/tk_audio_publisher
    """
    try:
        output = subprocess.check_output(['ros2', 'node', 'list'], text=True)
        nodes = output.strip().splitlines()
        return any(n.endswith('/' + node_name) for n in nodes)
    except Exception as e:
        print(f"检查 ROS2 节点失败: {e}")
        return False

def kill_ros2_node(node_name):
    """
    强制关闭指定 ROS2 节点（根据进程名匹配）
    """
    try:
        # 使用 pgrep 查找进程
        output = subprocess.check_output(['pgrep', '-f', node_name], text=True)
        pids = output.strip().splitlines()
        for pid in pids:
            print(f"杀掉旧节点 {node_name}，PID={pid}")
            subprocess.run(['kill', '-9', pid])
    except subprocess.CalledProcessError:
        print(f"没有找到需要杀掉的节点 {node_name}")
    except Exception as e:
        print(f"杀掉节点 {node_name} 出错: {e}")

def generate_launch_description():
    launch_description = []

    # 检查 tk_audio_publisher 是否已在运行
    if is_ros2_node_running("tk_audio_publisher"):
        kill_ros2_node("tk_audio_publisher")    
        print("audio_publisher未启动，将会启动它")

    audio_publisher_node = Node(
        package='audio_service',
        executable='tk_audio_publisher',
        name='tk_audio_publisher',
        output='screen'
    )
    launch_description.append(audio_publisher_node)

    # 第二个节点：文本音频发布器（依赖前者，因此用 Timer 延迟启动）
    asr_sentence_publisher_node = TimerAction(
        period=2.0,  # 延迟2秒启动，确保 tk_audio_publisher 先启动完成
        actions=[
            Node(
                package='audio_service',
                executable='tk_asr_text_publisher',
                name='tk_asr_text_publisher'
            )
        ]
    )
    launch_description.append(asr_sentence_publisher_node)

    return LaunchDescription(launch_description)
