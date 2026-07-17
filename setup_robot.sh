#!/bin/bash
set -e
cd /debug/tkvoice

echo "=== 1. 创建 tkvoice venv ==="
python3 -m venv venv
source venv/bin/activate
pip install --quiet setuptools wheel
pip install --quiet --no-deps cosyvoice/third_party/Monotonic_Alignment/*.whl
pip install --quiet --no-deps cosyvoice/third_party/Bert-VITS2/*.whl
pip install --quiet transformers==4.40.1 tokenizers==0.19.1
deactivate

echo "=== 2. 创建 .pth 指向主 venv ==="
echo /opt/venv/lib/python3.12/site-packages > venv/lib/python3.12/site-packages/main_venv.pth

echo "=== 3. 安装主 venv 额外依赖 ==="
pip install --quiet hyperpyyaml modelscope openai-whisper wetext inflect \
  typeguard textsearch kaldifst omegaconf diffusers pyarrow \
  pyworld onnxruntime ruamel.yaml modelscope-hub contractions \
  openai

echo "=== 4. 启动服务 ==="
bash container_main.sh
bash run_asr_bridge.sh &
bash audio_bridge.sh &
echo "=== 完成 ==="
