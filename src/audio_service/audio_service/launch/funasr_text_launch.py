from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node
import subprocess

def is_ros2_node_running(node_name):
    try:
        output = subprocess.check_output(['ros2', 'node', 'list'], text=True)
        nodes = output.strip().splitlines()
        return any(n.endswith('/' + node_name) for n in nodes)
    except Exception as e:
        print(f"检查 ROS2 节点失败: {e}")
        return False

def kill_ros2_node(node_name):
    try:
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

    if is_ros2_node_running("tk_audio_publisher"):
        kill_ros2_node("tk_audio_publisher")    
        print("audio_publisher未启动，将会启动它")

    sdk_prefix = "bash -c 'source /home/nvidia/xos/setup.bash 2>/dev/null || true; exec \"$@\"' bash"

    audio_publisher_node = Node(
        package='audio_service',
        executable='tk_audio_publisher',
        name='tk_audio_publisher',
        output='screen',
        prefix=sdk_prefix,
    )
    launch_description.append(audio_publisher_node)

    asr_sentence_publisher_node = TimerAction(
        period=2.0,
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
