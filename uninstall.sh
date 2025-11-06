#!/bin/bash
set -e
# set -e: 遇到错误立即退出

./audiolocal.sh stop || true

echo "[1/5] 开始卸载本地 Ollama ..."
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


echo "[2/5] 卸载本地 Python 包 ..."
python3 -m pip uninstall onnxruntime piper-tts onnxruntime-gpu httpx websockets -y || true

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

sudo rm -f /home/nvidia/logs/audiolocal.log


echo "[4/5] 删除本地 audiolocal_release 相关目录 ..."
TARGET_DIR="/home/nvidia"

if [ -d "$TARGET_DIR" ]; then
    cd "$TARGET_DIR"
    # 仅删除以 audiolocal_release_ 开头的目录，不删除 tar 包或其他文件
    for dir in audiolocal_release_*; do
        if [ -d "$dir" ]; then
            echo "删除目录: $dir"
            sudo rm -rf "$dir"
        fi
    done
else
    echo "⚠️ 目标目录 $TARGET_DIR 不存在，跳过删除。"
fi


echo "[5/5] 卸载完成 ✅"
