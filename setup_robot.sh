#!/bin/bash
set -e
cd /debug/tkvoice

echo "=== 1. 安装系统依赖 ==="
sudo apt update && sudo apt install -y python3.12-venv

echo "=== 2. 创建 tkvoice venv ==="
rm -rf tkvoice_venv
python3 -m venv tkvoice_venv
source tkvoice_venv/bin/activate
pip install --quiet setuptools wheel
pip install --quiet transformers==4.40.1 tokenizers==0.19.1
deactivate

echo "=== 3. 创建 .pth 指向容器主 venv ==="
echo /opt/venv/lib/python3.12/site-packages > tkvoice_venv/lib/python3.12/site-packages/main_venv.pth

echo "=== 4. 安装容器主 venv 额外依赖 ==="
docker exec walker-llm.vllm-1 pip install --quiet hyperpyyaml modelscope openai-whisper wetext inflect typeguard textsearch kaldifst omegaconf diffusers pyarrow pyworld onnxruntime ruamel.yaml modelscope-hub contractions openai 2>&1 || echo "[WARN] 部分包可能已存在，继续..."

echo "=== 5. 验证 tkvoice venv ==="
tkvoice_venv/bin/python3 -c "import transformers; print('transformers', transformers.__version__)" || echo "[ERROR] transformers 安装失败"

echo "=== 6. 检测容器 ==="
ROS_CONTAINER=$(docker ps --format '{{.Names}}' | grep ros | head -1)
VLLM_CONTAINER=$(docker ps --format '{{.Names}}' | grep vllm | head -1)
echo "  ROS容器: ${ROS_CONTAINER:-未找到}"
echo "  vLLM容器: ${VLLM_CONTAINER:-未找到}"

echo "=== 7. 启动服务 ==="
if [ -n "$VLLM_CONTAINER" ]; then
    docker exec "$VLLM_CONTAINER" /debug/tkvoice/tkvoice_venv/bin/python3 \
        /debug/tkvoice/container_pipeline.py > /debug/tkvoice/pipeline.log 2>&1 &
    echo "  Pipeline started in $VLLM_CONTAINER"
else
    echo "[ERROR] 未找到 vllm 容器"
fi

if [ -n "$ROS_CONTAINER" ]; then
    docker exec "$ROS_CONTAINER" bash /debug/tkvoice/run_asr_bridge.sh &
    echo "  ASR bridge started in $ROS_CONTAINER"
else
    echo "[WARN] 未找到 ROS 容器，跳过 ASR bridge"
fi
bash audio_bridge.sh &
echo "  Audio bridge started"

echo "=== 完成 ==="
cat version.txt 2>/dev/null && echo ""
