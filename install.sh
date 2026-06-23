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

# ========================
# 1 解压全部文件
# ========================
echo "[INFO] 解压发布包..."
cd "${PARENT_DIR}"
tar -xvf "${RELEASE_DIR}.tar"
cd "${BASE_DIR}"
echo "[OK] 解压完成"

# ========================
# 2 安装 Python 依赖
# ========================
echo "[INFO] 安装 Python 依赖包..."
export PIP_BREAK_SYSTEM_PACKAGES=1

python3 -m pip uninstall piper-tts -y 2>/dev/null || true
if [ -f requirements_tkvoice.txt ]; then
    python3 -m pip install --no-cache-dir -r requirements_tkvoice.txt 2>/dev/null || true
fi
python3 -m pip install --no-cache-dir 'onnxruntime<2,>=1' httpx==0.28.1 websockets==15.0.1 openai hyperpyyaml inflect modelscope funasr openai-whisper wetext 'diffusers<0.30' pyarrow pyworld conformer librosa soundfile onnx
python3 -m pip install --no-cache-dir onnxruntime-gpu 2>/dev/null || true
echo "[OK] Python 依赖安装完成"

# ========================
# 3 安装 Ollama（本地或远程 192.168.41.2）
# ========================
OLLAMA_TGZ="${BASE_DIR}/res/ollama-linux-arm64.tar.zst"
OLLAMA_REMOTE_HOST="192.168.41.2"
OLLAMA_REMOTE_USER="nvidia"

install_ollama_local() {
    echo "[INFO] 在本地安装 Ollama..."
    if [ -f "$OLLAMA_TGZ" ]; then
        sudo apt-get install -y zstd 2>/dev/null || true
        tar -I zstd -xvf "$OLLAMA_TGZ" -C /usr/bin ollama 2>/dev/null || true
        if command -v ollama &>/dev/null; then
            echo "[OK] Ollama 二进制已安装"
            nohup ollama serve > /dev/null 2>&1 &
            sleep 2
            # 导入 qwen2.5 模型
            if [ -f "${BASE_DIR}/res/qwen2.5_1.5b.tar.gz" ]; then
                echo "[INFO] 导入 qwen2.5:1.5b 模型..."
                ollama import qwen2.5:1.5b --file "${BASE_DIR}/res/qwen2.5_1.5b.tar.gz" 2>/dev/null || \
                ollama pull qwen2.5:1.5b 2>/dev/null || true
            fi
        fi
    else
        echo "[WARN] 未找到 ollama-linux-arm64.tar.zst，尝试从网络安装..."
        bash "${BASE_DIR}/res/ollama/install_ollama.sh" 2>/dev/null || true
    fi
}

install_ollama_remote() {
    echo "[INFO] 远程安装 Ollama 到 ${OLLAMA_REMOTE_HOST}..."
    ssh "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "mkdir -p '${BASE_DIR}/res/ollama'"
    rsync -av --progress -e "ssh -o StrictHostKeyChecking=no" "${BASE_DIR}/res/ollama/" "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}:${BASE_DIR}/res/ollama/"
    if [ -f "$OLLAMA_TGZ" ]; then
        rsync -av --progress -e "ssh -o StrictHostKeyChecking=no" "$OLLAMA_TGZ" "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}:${BASE_DIR}/res/"
    fi
    ssh -t "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "cd '${BASE_DIR}/res/ollama' && bash install_ollama.sh '${PARENT_DIR}' '${RELEASE_DIR}'" || true
}

if ping -c 1 -W 2 "$OLLAMA_REMOTE_HOST" >/dev/null 2>&1; then
    install_ollama_remote
else
    install_ollama_local
fi

# ========================
# 4 编译 ROS2 包
# ========================
echo "[INFO] 加载 ROS2 环境..."
for distro in jazzy humble rolling; do
    if [ -f "/opt/ros/$distro/setup.bash" ]; then
        source "/opt/ros/$distro/setup.bash"
        echo "[INFO] 已加载 /opt/ros/$distro/setup.bash"
        break
    fi
done

echo "[INFO] 开始编译 ROS2 包 audio_message 与 audio_service..."
colcon build --packages-select audio_message audio_service
echo "[OK] ROS2 包编译完成"

# ========================
# 5 提示信息
# ========================
echo ""
echo "✅ tkvoice 服务已成功安装"
echo ""
echo "# 启动服务"
echo "./tkvoice.sh start"
echo ""
echo "# 查看日志"
echo "tail -f ${BASE_DIR}/tkvoice.log"
echo ""
