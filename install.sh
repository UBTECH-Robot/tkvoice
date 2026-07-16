#!/bin/bash
set -e

RELEASE_DIR="$(basename "$(cd "$(dirname "$0")" && pwd)")"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PARENT_DIR="$( dirname "$SCRIPT_DIR" )"
BASE_DIR="${PARENT_DIR}/${RELEASE_DIR}"

cd "${PARENT_DIR}"

if [ ! -f "${RELEASE_DIR}.tar" ]; then
    echo "[ERROR] 找不到 ${RELEASE_DIR}.tar"
    exit 1
fi

echo "[INFO] 解压发布包..."
cd "${PARENT_DIR}"
tar -xvf "${RELEASE_DIR}.tar"
cd "${BASE_DIR}"
echo "[OK] 解压完成"

echo "[INFO] 安装 Python 依赖包..."
export PIP_BREAK_SYSTEM_PACKAGES=1
python3 -m pip uninstall piper-tts -y 2>/dev/null || true
if [ -f requirements_tkvoice.txt ]; then
    python3 -m pip install --no-cache-dir -r requirements_tkvoice.txt 2>/dev/null || true
fi
python3 -m pip install --no-cache-dir 'onnxruntime<2,>=1' httpx==0.28.1 websockets==15.0.1 openai hyperpyyaml inflect modelscope funasr openai-whisper wetext 'diffusers<0.30' pyarrow pyworld conformer librosa soundfile onnx
python3 -m pip install --no-cache-dir onnxruntime-gpu 2>/dev/null || true
echo "[OK] Python 依赖安装完成"

echo "[INFO] 安装 Ollama..."
OLLAMA_TGZ="${BASE_DIR}/res/ollama/ollama-linux-arm64.tar.zst"
Qwen_TGZ="${BASE_DIR}/res/ollama/qwen2.5_1.5b.tar.gz"
if [ -f "$OLLAMA_TGZ" ]; then
    sudo apt-get install -y zstd 2>/dev/null || true
    sudo tar -I zstd -xvf "$OLLAMA_TGZ" -C /usr/bin ollama 2>/dev/null || true
    if command -v ollama &>/dev/null; then
        echo "[OK] Ollama 已安装"
        nohup ollama serve > /dev/null 2>&1 &
        sleep 3
        if [ -f "$Qwen_TGZ" ]; then
            echo "[INFO] 导入 qwen2.5:1.5b 模型..."
            ollama import qwen2.5:1.5b --file "$Qwen_TGZ" 2>/dev/null || true
            echo "[OK] 模型导入完成"
        fi
    fi
else
    echo "[WARN] 未找到 $OLLAMA_TGZ，跳过 Ollama"
fi
echo "[OK] Ollama 安装完成"

echo "[INFO] 编译 ROS2 包..."
for distro in jazzy humble rolling; do
    if [ -f "/opt/ros/$distro/setup.bash" ]; then
        source "/opt/ros/$distro/setup.bash"
        echo "[INFO] 已加载 /opt/ros/$distro/setup.bash"
        break
    fi
done
colcon build --packages-select audio_message audio_service
echo "[OK] ROS2 包编译完成"

echo ""
echo "✅ tkvoice服务已成功安装，可用如下命令进行管理:"
echo ""
echo "# 启动服务"
echo "./tkvoice.sh start"
echo ""
echo "# 停止服务"
echo "./tkvoice.sh stop"
echo ""
echo "# 重启服务"
echo "./tkvoice.sh restart"
echo ""
echo "# 查看状态"
echo "./tkvoice.sh status"
echo ""
echo "# 查看日志"
echo "tail -f ${BASE_DIR}/tkvoice.log"
echo ""
