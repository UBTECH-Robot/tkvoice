#!/bin/bash
set -e
# 一旦出错立即退出

# ========================
# 1 配置远程服务器信息
# ========================
REMOTE_USER="ubuntu"
REMOTE_IP="192.168.41.1"
REMOTE_DIR="/home/ubuntu"

RELEASE_DIR="tkvoice_release_0.3.35_0623_073057"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PARENT_DIR="$( dirname "$SCRIPT_DIR" )"

BASE_DIR="${PARENT_DIR}/${RELEASE_DIR}"

cd "${PARENT_DIR}"

# 检查 tar 包是否存在
if [ ! -f "${RELEASE_DIR}.tar" ]; then
    echo "[ERROR] 找不到 ${RELEASE_DIR}.tar"
    exit 1
fi

cd "${PARENT_DIR}"
tar -xvf "${RELEASE_DIR}.tar" \
    "${RELEASE_DIR}/uninstall.sh"

cd "${BASE_DIR}"

# ========================
# 6 安装 Python 依赖
# ========================
echo "[INFO] 安装 Python 依赖包..."

# PEP 668 (externally-managed-environment) 兼容：Ubuntu 24.04 / Python 3.12
export PIP_BREAK_SYSTEM_PACKAGES=1

# 从 PyPI 安装 Python 依赖
cd "${PARENT_DIR}"
python3 -m pip uninstall piper-tts onnxruntime onnxruntime-gpu -y 2>/dev/null || true
python3 -m pip install --no-cache-dir 'onnxruntime<2,>=1' httpx==0.28.1 websockets==15.0.1 openai
# 若环境有 GPU（如 Jetson），尝试安装 GPU 版本
python3 -m pip install --no-cache-dir onnxruntime-gpu 2>/dev/null || true
echo "[OK] Python 依赖安装完成"

# ========================
# 7 安装 Ollama
# ========================
cd "${PARENT_DIR}"

# 检查是否需要远程安装 Ollama
OLLAMA_REMOTE_HOST="192.168.41.2"
OLLAMA_REMOTE_USER="nvidia"
OLLAMA_PATH="${BASE_DIR}/res/ollama"

if ping -c 1 -W 2 "$OLLAMA_REMOTE_HOST" >/dev/null 2>&1; then
    echo "[INFO] 检测到 $OLLAMA_REMOTE_HOST 可达，准备远程安装 Ollama..."

    # 解压整个 ollama 目录
    tar -xvf "${RELEASE_DIR}.tar" "${RELEASE_DIR}/res/ollama/"

    cd "${OLLAMA_PATH}"

    # 同步文件到远程（源路径末尾加 / 表示同步目录内容）
    ssh "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "mkdir -p '${OLLAMA_PATH}'"
    echo "[INFO] 开始传输 Ollama 文件到 ${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}:${OLLAMA_PATH}"
    rsync -av --progress --delete -e "ssh -o StrictHostKeyChecking=no" "${OLLAMA_PATH}/" "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}:${OLLAMA_PATH}/"
    echo "[OK] Ollama 文件传输完成！"

    rm -rf "${OLLAMA_PATH}"
    echo "[OK] 已删除本地临时目录 res/ollama"

    # 远程执行安装和清理（合并为一个 ssh 会话，sudo 密码只需输入一次）
    if ssh -t "${OLLAMA_REMOTE_USER}@${OLLAMA_REMOTE_HOST}" "cd '${OLLAMA_PATH}' && bash install_ollama.sh '${PARENT_DIR}' '${RELEASE_DIR}' && sudo find '${OLLAMA_PATH}' -mindepth 1 ! -name 'uninstall_ollama.sh' -exec rm -rf {} +"; then
        echo "[OK] Ollama 远程安装完成并清理除卸载脚本外的所有文件！"
    else
        echo "[WARN] Ollama 远程安装失败（可能无公网访问），跳过，后续步骤继续执行"
    fi
else
    echo "[INFO] $OLLAMA_REMOTE_HOST 不可达，在本地安装 Ollama..."

    tar -xvf "${RELEASE_DIR}.tar" "${RELEASE_DIR}/res/ollama/uninstall_ollama.sh" \
        "${RELEASE_DIR}/res/ollama/install_ollama.sh" \
        "${RELEASE_DIR}/res/ollama/import_ollama_model.sh"

    cd "${OLLAMA_PATH}"
    chmod +x install_ollama.sh import_ollama_model.sh 2>/dev/null || true
    if bash install_ollama.sh "${PARENT_DIR}" "${RELEASE_DIR}"; then
        echo "[OK] Ollama 安装完成"
    else
        echo "[WARN] Ollama 安装失败（可能无公网访问），跳过，后续步骤继续执行"
    fi

    cd "${OLLAMA_PATH}"
    sudo find "${OLLAMA_PATH}" -mindepth 1 ! -name 'uninstall_ollama.sh' -exec rm -rf {} +
    echo "[OK] 已删除本地临时目录 res/ollama 下除卸载脚本外的所有文件"
fi

# ========================
# 8 解压主项目并编译 ROS2
# ========================
cd "${PARENT_DIR}"
tar -xvf "${RELEASE_DIR}.tar" \
    "${RELEASE_DIR}/tkvoice.sh" \
    "${RELEASE_DIR}/version.txt" \
    "${RELEASE_DIR}/src/"

cd "${BASE_DIR}"

echo "[INFO] 加载 ROS2 Jazzy 环境..."
if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    source /opt/ros/jazzy/setup.bash
else
    echo "[WARN] /opt/ros/jazzy/setup.bash 不存在，尝试自动检测 ROS2..."
    # 兜底：尝试常见 ROS2 发行版
    for distro in jazzy humble rolling; do
        if [ -f "/opt/ros/$distro/setup.bash" ]; then
            source "/opt/ros/$distro/setup.bash"
            echo "[INFO] 已加载 /opt/ros/$distro/setup.bash"
            break
        fi
    done
fi

echo "[INFO] 开始编译 ROS2 包 audio_message 与 audio_service..."
colcon build --packages-select audio_message audio_service
echo "[OK] ROS2 包编译完成"

# ========================
# 9 提示信息
# ========================
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
