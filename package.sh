#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VERSION_FILE="version.txt"

# ========== 1. 处理版本号 ==========
if [ $# -ge 1 ]; then
    NEW_VERSION="$1"
    echo "[INFO] 使用传入版本号: ${NEW_VERSION}"
else
    if [ -f "$VERSION_FILE" ]; then
        CURRENT_VERSION=$(cat "$VERSION_FILE")
    else
        CURRENT_VERSION="0.0.0"
    fi
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
    NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
    echo "[INFO] 版本自增: ${CURRENT_VERSION} -> ${NEW_VERSION}"
fi

echo "$NEW_VERSION" > "$VERSION_FILE"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
PKG_FILE="tkvoice_v${NEW_VERSION}.tar"

echo "=== 打包 tkvoice v${NEW_VERSION} ==="

tar -cvf "$PKG_FILE" \
    --exclude="tkvoice_venv" \
    --exclude=".git" \
    --exclude="*.tar" \
    --exclude="pipeline.log" \
    --exclude="cam_test_*.jpg" \
    --exclude="__pycache__" \
    --exclude="*/__pycache__" \
    --exclude=".gitignore" \
    --exclude=".gitattributes" \
    --exclude="整体流程图*.png" \
    --exclude="build.sh" \
    --exclude="uninstall.sh" \
    cosyvoice src matcha CosyVoice2-0.5B \
    container_pipeline.py container_main.sh \
    audio_bridge.sh run_asr_bridge.sh \
    setup_robot.sh version.txt

echo ""
echo "[OK] 打包完成: ${PKG_FILE}  ($(ls -lh "$PKG_FILE" | awk '{print $5}'))"
echo ""
echo "========== 部署步骤 =========="
echo ""
echo "1. 拷贝到机器人:"
echo "   scp ${PKG_FILE} walker@<ROBOT_IP>:/tmp/"
echo ""
echo "2. 解压部署:"
echo "   ssh walker@<ROBOT_IP> \"rm -rf /debug/tkvoice && mkdir -p /debug/tkvoice && tar -xf /tmp/${PKG_FILE} -C /debug/tkvoice && bash /debug/tkvoice/setup_robot.sh\""
echo ""
echo "3. 启动 (如果 setup_robot.sh 已完成):"
echo "   bash /debug/tkvoice/audio_bridge.sh &"
echo "   # ASR bridge 和 pipeline 已由 setup_robot.sh 启动"
echo "================================"
