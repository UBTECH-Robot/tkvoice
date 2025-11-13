from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node
import subprocess
import time
import os
from dotenv import load_dotenv
# pip install python-dotenv==1.2.1
from pathlib import Path

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
    
def kill_ros2_node(node_name, timeout=5):
    """
    强制关闭指定 ROS2 节点（根据进程名匹配），确保杀掉后再返回。
    避免误杀当前 launch 自身。
    """
    try:
        current_pid = str(os.getpid())
        output = subprocess.check_output(['pgrep', '-f', node_name], text=True)
        pids = [pid for pid in output.strip().splitlines() if pid != current_pid]

        if not pids:
            print(f"没有找到需要杀掉的节点 {node_name}")
            return

        for pid in pids:
            print(f"尝试强杀旧节点 {node_name}，PID={pid}")
            subprocess.run(['kill', '-9', pid])
            print(f"kill -9 {node_name} (PID={pid}) 命令已发送")

            start_time = time.time()
            while os.path.exists(f"/proc/{pid}"):
                if time.time() - start_time > timeout:
                    print(f"⚠️ 节点 {node_name} (PID={pid}) 在 {timeout}s 内未退出")
                    break
                time.sleep(0.1)

            print(f"✅ 节点 {node_name} (PID={pid}) 已被成功杀掉")

    except subprocess.CalledProcessError:
        print(f"没有找到需要杀掉的节点 {node_name}")
    except Exception as e:
        print(f"杀掉节点 {node_name} 出错: {e}")

def generate_launch_description():
    env_path = Path(__file__).resolve().parent.parent.parent.parent.parent.parent / ".env"
    load_dotenv(env_path)

    launch_description = []

    if is_ros2_node_running("tk_audio_publisher"):
        kill_ros2_node("tk_audio_publisher")    
        print("audio_publisher节点已强制停止，将会重新启动它")
    if is_ros2_node_running("tk_asr_text_publisher"):
        kill_ros2_node("tk_asr_text_publisher")    
        print("tk_asr_text_publisher节点已强制停止，将会重新启动它")
    if is_ros2_node_running("tk_audio_process"):
        kill_ros2_node("tk_audio_process")    
        print("asr_xf_tts_process节点已强制停止，将会重新启动它")

    audio_publisher_node = Node(
        package='audio_service',
        executable='tk_audio_publisher',
        name='tk_audio_publisher',
        output='screen',
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

    # 延迟 3 秒后启动 tk_audio_process
    delayed_process = TimerAction(
        period=3.0,
        actions=[Node(
        package='audio_service',
        executable='tk_audio_process',
        name='tk_audio_process',
        output='screen'
    )]
    )

    launch_description.append(delayed_process)

    return LaunchDescription(launch_description)
