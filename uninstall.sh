#!/bin/bash
set -e
# set -e: 遇到错误立即退出

./tkvoice.sh stop || true

echo "[1/5] 开始卸载 Ollama ..."
OLLAMA_REMOTE_HOST="192.168.41.3"
OLLAMA_REMOTE_USER="nvidia"

# 检查 Ollama 安装位置
if ping -c 1 -W 2 "$OLLAMA_REMOTE_HOST" >/dev/null 2>&1; then
    echo "[INFO] 检测到 $OLLAMA_REMOTE_HOST 可达，尝试远程卸载 Ollama..."

    # 动态查找远程 ollama 目录
    REMOTE_OLLAMA_DIR=$(ssh "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "find /home -path '*/tkvoice_release_*/res/ollama' -type d 2>/dev/null | head -1")

    if [ -n "$REMOTE_OLLAMA_DIR" ] && ssh "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "test -f '${REMOTE_OLLAMA_DIR}/uninstall_ollama.sh'" 2>/dev/null; then
        ssh -t "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "cd '${REMOTE_OLLAMA_DIR}' && bash uninstall_ollama.sh"
        echo "[OK] 远程 Ollama 卸载完成"
    else
        # 远程没有卸载脚本，尝试直接卸载服务
        echo "[INFO] 远程未找到卸载脚本，尝试直接卸载服务..."
        ssh -t "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "sudo systemctl stop ollama 2>/dev/null || true; sudo systemctl disable ollama 2>/dev/null || true; sudo rm -f /etc/systemd/system/ollama.service; sudo systemctl daemon-reload; sudo rm -rf /usr/share/ollama /usr/lib/ollama /home/ollama; sudo userdel -r ollama 2>/dev/null || true; sudo groupdel ollama 2>/dev/null || true"
        echo "[OK] 远程 Ollama 服务已清理"
    fi
else
    echo "[INFO] $OLLAMA_REMOTE_HOST 不可达，尝试本地卸载 Ollama..."

    if [ -d "res/ollama" ]; then
        cd res/ollama
        if [ -x "./uninstall_ollama.sh" ]; then
            ./uninstall_ollama.sh
        else
            echo "⚠️ 找不到可执行的卸载脚本 ./uninstall_ollama.sh，跳过 Ollama 卸载。"
        fi
        cd - >/dev/null
    else
        echo "⚠️ 未找到 res/ollama 目录，跳过 Ollama 卸载。"
    fi
fi


echo "[2/5] 卸载本地 Python 包 ..."
python3 -m pip uninstall onnxruntime piper-tts onnxruntime-gpu httpx websockets -y || sudo python3 -m pip uninstall onnxruntime piper-tts onnxruntime-gpu httpx websockets -y || true

echo "[3/5] 在远程服务器上卸载 ASR 服务 ..."
REMOTE_USER="ubuntu"
REMOTE_IP="192.168.41.1"
REMOTE_DIR="/home/ubuntu"

if ping -c 1 -W 2 "$REMOTE_IP" >/dev/null 2>&1; then
    ssh -t "${REMOTE_USER}@${REMOTE_IP}" "cd ${REMOTE_DIR}/docker_funasr && bash uninstall_asr.sh" || \
    echo "⚠️ 远程卸载失败（可能未部署 docker_funasr 或脚本缺失）。"
else
    echo "⚠️ 无法连接远程服务器 ${REMOTE_IP}，跳过远程卸载。"
fi

sudo rm -f /home/nvidia/logs/tkvoice.log


echo "[4/5] 删除本地 tkvoice_release 相关目录 ..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
TARGET_DIR="$( dirname "$SCRIPT_DIR" )"

if [ -d "$TARGET_DIR" ]; then
    cd "$TARGET_DIR"
    # 仅删除以 tkvoice_release_ 开头的目录，不删除 tar 包或其他文件
    for dir in tkvoice_release_*; do
        if [ -d "$dir" ]; then
            echo "删除目录: $dir"
            sudo rm -rf "$dir"
        fi
    done
else
    echo "⚠️ 目标目录 $TARGET_DIR 不存在，跳过删除。"
fi


echo "[5/5] 卸载完成 ✅"
