#!/bin/bash
set -e

WORKDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
LAUNCH_FILE="audio_service asr_llm_tts_process_launch.py"
LOG_FILE="${WORKDIR}/tkvoice.log"
# lyre 语音系统由机器人 proc_manager 管理，tkvoice 只需启动 ASR 文本发布和音频处理节点
NODES=("tk_audio_publisher" "tk_asr_text_publisher" "tk_audio_process")
export MODEL_DIR="${WORKDIR}/res/"
export COSYVOICE_DIR="${WORKDIR}"
export COSYVOICE_MODEL_DIR="${WORKDIR}/CosyVoice2-0.5B"
export MATCHA_DIR="${WORKDIR}/matcha"
export PYTHONPATH="${WORKDIR}:${PYTHONPATH}"
export PRIMARY_MODEL="qwen2.5:1.5b"
export TTS_WORKERS="1"

# ===========================
# 功能函数
# ===========================
kill_nodes() {
    launch_pid=$(pgrep -f "$LAUNCH_FILE" || true)
    for node in "${NODES[@]}"; do
        pids=$(pgrep -f "$node" || true)
        # 排除 launch 进程本身
        [ -n "$launch_pid" ] && [ -n "$pids" ] && pids=$(echo "$pids" | grep -v "^${launch_pid}$" || true)
        [ -n "$pids" ] && echo "杀掉节点 $node，PID=$pids" && kill -9 $pids || true
    done
    [ -n "$launch_pid" ] && echo "杀掉 launch 进程 $LAUNCH_FILE，PID=$launch_pid" && kill -9 $launch_pid || true
}

wait_for_nodes() {
    local desired_state="$1"   # "running" 或 "stopped"
    local timeout="${2:-30}"
    local interval="${3:-1}"

    local waited=0
    while [ $waited -lt $timeout ]; do
        all_ok=true
        running_count=0
        echo ""
        echo "节点状态:"

        for node in "${NODES[@]}"; do
            pids=$(pgrep -f "$node" || true)
            [ -n "$launch_pid" ] && [ -n "$pids" ] && pids=$(echo "$pids" | grep -v "^${launch_pid}$" || true)

            if [ "$desired_state" = "running" ]; then
                if [ -n "$pids" ]; then
                    echo "  - $node ✅ (PID: $pids)"
                    ((running_count++))
                else
                    echo "  - $node ❌ (未运行)"
                    all_ok=false
                fi
            else
                if [ -z "$pids" ]; then
                    echo "  - $node ✅ (已停止)"
                    ((running_count++))
                else
                    echo "  - $node ⚠️ (仍在运行, PID: $pids)"
                    all_ok=false
                fi
            fi
        done

        $all_ok && break

        sleep $interval
        waited=$((waited + interval))
        echo ""
        echo "⏳ 等待节点 ${desired_state}中 (${waited}s/${timeout}s)..."
    done

    $all_ok && return 0 || return 1
}

start() {
    echo "=============================="
    echo "🚀 启动tkvoice服务"
    echo "=============================="
    echo "工作目录: $WORKDIR"
    echo ""

    rm -rf "$LOG_FILE"
    mkdir -p "$(dirname "$LOG_FILE")"
    touch "$LOG_FILE"

    cd "$WORKDIR"
    source install/setup.bash
    # source 机器人 SDK 环境（提供 lyre_msgs）
    ROBOT_SETUP="${HOME}/xos/setup.bash"
    [ -f "$ROBOT_SETUP" ] && source "$ROBOT_SETUP"

    echo "启动 ROS2 launch 文件: $LAUNCH_FILE"
    mkdir -p "${WORKDIR}/roslogs"
    export ROS_LOG_DIR="${WORKDIR}/roslogs"
    ros2 launch audio_service asr_llm_tts_process_launch.py > "$LOG_FILE" 2>&1 &

    echo ""
    echo "等待节点启动中..."
    launch_pid=$(pgrep -f "$LAUNCH_FILE" || true)
    if wait_for_nodes "running" 30 1; then
        echo ""
        echo "✅ 所有节点已启动 (${#NODES[@]}/${#NODES[@]})"
    else
        echo ""
        echo "⚠️ 超时: 部分节点未能在 30s 内启动"
    fi
    echo "查看日志: "
    echo "tail -f ${LOG_FILE}"
}

stop() {
    echo "=============================="
    echo "🛑 停止tkvoice服务"
    echo "=============================="
    kill_nodes
}

restart() {
    echo "=============================="
    echo "🔁 重启tkvoice服务"
    echo "=============================="
    stop
    echo ""
    echo "等待节点完全停止..."
    launch_pid=$(pgrep -f "$LAUNCH_FILE" || true)
    wait_for_nodes "stopped" 30 2 || echo "⚠️ 超时: 部分节点未能完全停止"
    echo ""
    start
}

status() {
    echo "=============================="
    echo "📊 tkvoice服务运行状态"
    echo "=============================="
    echo "工作目录: $WORKDIR"
    echo "查看日志文件: "
    echo "tail -f $LOG_FILE"
    echo ""

    launch_pid=$(pgrep -f "$LAUNCH_FILE" || true)
    if [ -n "$launch_pid" ]; then
        echo "ROS2 launch 进程: 运行中 ✅  PID=$launch_pid"
    else
        echo "ROS2 launch 进程: 未运行 ❌"
    fi

    echo ""
    echo "节点状态:"
    running_count=0
    for node in "${NODES[@]}"; do
        set +e
        pids=$(pgrep -f "$node" || true)
        # 排除 launch PID，避免误匹配
        [ -n "$launch_pid" ] && [ -n "$pids" ] && pids=$(echo "$pids" | grep -v "^${launch_pid}$" || true)

        if [ -n "$pids" ]; then
            echo "  - $node ✅ (PID: $pids)"
            ((running_count++))
        else
            echo "  - $node ❌ (未运行)"
        fi
        set -e
    done

    echo ""
    if [ "$running_count" -eq "${#NODES[@]}" ]; then
        echo "✅ 所有节点均在运行 (${running_count}/${#NODES[@]})"
    elif [ "$running_count" -gt 0 ]; then
        echo "⚠️  部分节点在运行 (${running_count}/${#NODES[@]})"
    else
        echo "❌ 无节点在运行 (0/${#NODES[@]})"
    fi
    echo ""
}


# ===========================
# 主入口
# ===========================
case "$1" in
    start) start ;;
    stop) stop ;;
    restart) restart ;;
    status) status ;;
    *) echo "用法: $0 {start|stop|restart|status}" ; exit 1 ;;
esac
