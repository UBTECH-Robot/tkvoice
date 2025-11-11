#!/bin/bash
set -e

MODEL_NAME="qwen2.5:1.5b"

echo "[0/8] 卸载 Ollama 模型..."
if command -v ollama >/dev/null 2>&1; then
    # 尝试删除模型，忽略报错
    ollama rm "$MODEL_NAME" || true
    echo "✅ 模型 $MODEL_NAME 已删除或不存在。"
else
    echo "⚠️ Ollama 命令未找到，跳过模型卸载。"
fi

echo "[1/8] 检查 Ollama 服务状态..."
if systemctl is-active --quiet ollama; then
    echo "⚠️ Ollama 服务正在运行，准备停止..."
    sudo systemctl stop ollama
fi

echo "[2/8] 禁用 Ollama systemd 服务..."
sudo systemctl disable ollama || true
sudo rm -f /etc/systemd/system/ollama.service
sudo systemctl daemon-reload

echo "[3/8] 删除 Ollama 二进制文件..."
sudo rm -f /usr/bin/ollama /usr/local/bin/ollama || true

echo "[4/8] 删除 Ollama 安装目录、缓存和日志..."
sudo rm -rf /usr/share/ollama /usr/lib/ollama /local/lib/ollama || true
sudo rm -f /var/log/ollama.log
sudo rm -rf ~/.ollama
sudo rm -rf /home/ollama
sudo rm -rf /home/*/.ollama || true

echo "[5/8] 删除 Ollama 用户和组..."
sudo userdel -r ollama || true
sudo groupdel ollama || true

echo "[6/8] 删除 JetPack6 GPU 相关目录权限残留..."
sudo rm -rf /usr/lib/ollama/cuda_jetpack6 || true

echo "[7/8] 删除 Ollama 模型缓存目录..."
sudo rm -rf ~/.ollama/models
sudo rm -rf /home/*/.ollama/models || true
sudo rm -rf /usr/share/ollama/models || true

echo "[8/8] 卸载完成！"
echo "✅ Ollama 已被彻底卸载，包括二进制文件、服务、用户、配置和模型。"