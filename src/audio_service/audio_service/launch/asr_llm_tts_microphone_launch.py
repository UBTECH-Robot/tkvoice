from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node
import subprocess
import time
import os
from dotenv import load_dotenv
# pip install python-dotenv==1.2.1
from pathlib import Path

def check_env_file_exists(env_path):
    """
    Check if .env file exists
    Raise exception if not found to terminate launch
    """
    if not env_path.exists():
        error_msg = f"❌ Error: Environment config file not found: {env_path}\nPlease ensure .env file exists in project root directory"
        print(error_msg)
        exit(1)
        raise FileNotFoundError(error_msg)
    print(f"✅ Environment config file found: {env_path}")


def is_ros2_node_running(node_name):
    """
    Check if ROS2 node is running.
    node_name can be 'microphone_audio_publisher', will match /microphone_audio_publisher or /ns/microphone_audio_publisher
    """
    try:
        output = subprocess.check_output(['ros2', 'node', 'list'], text=True)
        nodes = output.strip().splitlines()
        return any(n.endswith('/' + node_name) for n in nodes)
    except Exception as e:
        print(f"Failed to check ROS2 node: {e}")
        return False
    
def kill_ros2_node(node_name, timeout=5):
    """
    Force kill specified ROS2 node (match by process name), ensure it's killed before returning.
    Avoid accidentally killing current launch process itself.
    """
    try:
        current_pid = str(os.getpid())
        output = subprocess.check_output(['pgrep', '-f', node_name], text=True)
        pids = [pid for pid in output.strip().splitlines() if pid != current_pid]

        if not pids:
            print(f"No node found to kill: {node_name}")
            return

        for pid in pids:
            print(f"Attempting to kill old node {node_name}, PID={pid}")
            subprocess.run(['kill', '-9', pid])
            print(f"kill -9 {node_name} (PID={pid}) command sent")

            start_time = time.time()
            while os.path.exists(f"/proc/{pid}"):
                if time.time() - start_time > timeout:
                    print(f"⚠️ Node {node_name} (PID={pid}) did not exit within {timeout}s")
                    break
                time.sleep(0.1)

            print(f"✅ Node {node_name} (PID={pid}) successfully killed")

    except subprocess.CalledProcessError:
        print(f"No node found to kill: {node_name}")
    except Exception as e:
        print(f"Error killing node {node_name}: {e}")

def generate_launch_description():
    env_path = Path(__file__).resolve().parent.parent.parent.parent.parent.parent / ".env"
    check_env_file_exists(env_path)
    load_dotenv(env_path)

    launch_description = []

    if is_ros2_node_running("microphone_audio_publisher"):
        kill_ros2_node("microphone_audio_publisher")    
        print("microphone_audio_publisher node has been force stopped, will restart it")
    if is_ros2_node_running("tk_asr_text_publisher"):
        kill_ros2_node("tk_asr_text_publisher")    
        print("tk_asr_text_publisher node has been force stopped, will restart it")
    if is_ros2_node_running("tk_audio_process"):
        kill_ros2_node("tk_audio_process")    
        print("asr_xf_tts_process node has been force stopped, will restart it")

    audio_publisher_node = Node(
        package='audio_service',
        executable='microphone_audio_publisher',
        name='microphone_audio_publisher',
        output='screen',
    )
    launch_description.append(audio_publisher_node)
    # Second node: text audio publisher (depends on previous, so use Timer to delay startup)
    asr_sentence_publisher_node = TimerAction(
        period=2.0,  # Delay 2 seconds to ensure microphone_audio_publisher starts first
        actions=[
            Node(
                package='audio_service',
                executable='tk_asr_text_publisher',
                name='tk_asr_text_publisher'
            )
        ]
    )
    launch_description.append(asr_sentence_publisher_node)

    # Delay 3 seconds before starting tk_audio_process
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


# rm -rf build install log && colcon build --packages-select audio_message audio_service
# source install/setup.bash
# ros2 launch audio_service asr_llm_tts_microphone_launch.py