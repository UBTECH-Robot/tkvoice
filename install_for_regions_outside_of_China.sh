#!/bin/bash
set -e
# 一旦出错立即退出

# ========================
# 1 配置远程服务器信息
# ========================
REMOTE_USER="ubuntu"
REMOTE_IP="192.168.41.1"
REMOTE_DIR="/home/ubuntu"

RELEASE_DIR="tkvoice_release_0.3.20_0320_193403"
BASE_DIR="${HOME}/${RELEASE_DIR}"

echo "[INFO] 解压 res/docker_funasr 到本地临时目录..."

cd "${HOME}"

# 检查 tar 包是否存在
if [ ! -f "${RELEASE_DIR}.tar" ]; then
    echo "[ERROR] 找不到 ${RELEASE_DIR}.tar"
    exit 1
fi

# 检查目标路径是否在 tar 中存在
if ! tar -tf "${RELEASE_DIR}.tar" | grep -q "${RELEASE_DIR}/res/docker_funasr/"; then
    echo "[ERROR] tar 包中未找到 ${RELEASE_DIR}/res/docker_funasr/"
    exit 1
fi

cd "${HOME}"
tar -xvf "${RELEASE_DIR}.tar" \
    "${RELEASE_DIR}/uninstall.sh" \
    "${RELEASE_DIR}/res/docker_funasr/"
cd "${BASE_DIR}"

# ========================
# 2 检查本地目录是否存在
# ========================
if [ ! -d "res/docker_funasr" ]; then
    echo "[ERROR] 本地目录 res/docker_funasr 不存在，退出安装"
    exit 1
fi

# ========================
# 3 使用 rsync 传输 docker_funasr
# ========================
echo "[INFO] 开始传输整个 docker_funasr 目录到 ${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}"
rsync -av --progress --delete -e "ssh -o StrictHostKeyChecking=no" res/docker_funasr ${REMOTE_USER}@${REMOTE_IP}:${REMOTE_DIR}/
# rsync 参数说明：
# -a : archive 模式，保留文件权限、时间戳、符号链接等
# -v : verbose，显示详细信息
# --progress : 显示每个文件传输进度
# --delete : 删除远程多余文件，实现完全同步
# 注意：源目录末尾没有 / 表示传整个 docker_funasr 目录，而不仅仅是其内容
echo "[OK] docker_funasr 目录传输完成！"

# ========================
# 4 在远程服务器上执行安装脚本
# ========================
ssh -t ${REMOTE_USER}@${REMOTE_IP} "cd ${REMOTE_DIR}/docker_funasr && bash install_asr.sh"
echo "[OK] 远程 ASR 服务安装完成"

# ========================
# 5 删除本地临时目录
# ========================
cd "${BASE_DIR}/res"
rm -rf docker_funasr
echo "[OK] 已删除本地临时目录 res/docker_funasr"

# ========================
# 6 安装本地 Python 包和依赖
# ========================
echo "[INFO] 安装 Python 依赖包..."
cd "${HOME}"
tar -xvf "${RELEASE_DIR}.tar" \
    "${RELEASE_DIR}/res/onnxruntime_gpu-1.20.1-cp310-cp310-linux_aarch64.whl"

cd "${BASE_DIR}/res"
python3 -m pip uninstall onnxruntime piper-tts onnxruntime-gpu -y || sudo python3 -m pip uninstall onnxruntime piper-tts onnxruntime-gpu -y || true
python3 -m pip install --no-cache-dir onnxruntime==1.23.2 piper_tts==1.3.0 httpx==0.28.1 websockets==15.0.1
python3 -m pip uninstall onnxruntime -y || sudo python3 -m pip uninstall onnxruntime -y || true
python3 -m pip install --no-cache-dir onnxruntime_gpu-1.20.1-cp310-cp310-linux_aarch64.whl
echo "[OK] Python 依赖安装完成"

rm -f *.whl

# ========================
# 7 安装 Ollama
# ========================
cd "${HOME}"
tar -xvf "${RELEASE_DIR}.tar" "${RELEASE_DIR}/res/ollama/"
cd "${BASE_DIR}/res/ollama"

./install_ollama.sh
echo "[OK] Ollama 安装完成"

cd "${BASE_DIR}/res/ollama"
sudo find "${BASE_DIR}/res/ollama" -mindepth 1 ! -name 'uninstall_ollama.sh' -exec rm -rf {} +

echo "[OK] 已删除本地临时目录 res/ollama 下除卸载脚本外的所有文件"

# ========================
# 8 解压主项目并编译 ROS2
# ========================
cd "${HOME}"
tar -xvf "${RELEASE_DIR}.tar" \
    "${RELEASE_DIR}/tkvoice.sh" \
    "${RELEASE_DIR}/version.txt" \
    "${RELEASE_DIR}/res/piper_voices/" \
    "${RELEASE_DIR}/src/"

cd "${BASE_DIR}"
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
