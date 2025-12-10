#!/bin/bash
set -e

echo "[INFO] 小版本打包可直接执行本脚本，版本号会在最后一位进行自增："
echo "   ./build.sh"
echo "[INFO] 大版本打包请提供版本号，例如："
echo "   ./build.sh 1.0.0"

SETUP_FILE="src/audio_service/setup.py"

# --- 1. 处理版本号 ---
# ========== 1.1 获取传入版本号或读取现有版本号 ==========
if [ $# -eq 0 ]; then
    CURRENT_VERSION=$(grep -Eo 'version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"' "$SETUP_FILE" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+')
    if [ -z "$CURRENT_VERSION" ]; then
        echo "[ERROR] 无法从 $SETUP_FILE 中读取版本号"
        exit 1
    fi

    # 拆分主次补版本号（major.minor.patch）
    IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"
    NEW_VERSION="${MAJOR}.${MINOR}.$((PATCH + 1))"
    echo "[INFO] 未传入版本号，自动递增版本号：${CURRENT_VERSION} -> ${NEW_VERSION}"
else
    NEW_VERSION="$1"
    echo "[INFO] 使用传入版本号：${NEW_VERSION}"
fi

# ========== 1.2 更新 setup.py 内的版本号 ==========
sed -i "s/version\s*=\s*\"[0-9]\+\.[0-9]\+\.[0-9]\+\"/version=\"${NEW_VERSION}\"/" "$SETUP_FILE"
echo "[OK] 已更新 $SETUP_FILE 内版本号为 ${NEW_VERSION}"

VERSION="${NEW_VERSION}"
# --- 2. 生成时间戳与目标目录 ---
TIMESTAMP=$(date +"%m%d_%H%M%S")
RELEASE_DIR="tkvoice_release_${VERSION}_${TIMESTAMP}"
RELEASE_PATH="$(pwd)/${RELEASE_DIR}"

echo "[INFO] 创建发布目录: ${RELEASE_PATH}"
mkdir -p "${RELEASE_PATH}"

# --- 3. 写入版本号文件 ---
echo "[INFO] 写入版本号文件 version.txt"
echo "${VERSION}" > "${RELEASE_PATH}/version.txt"

# --- 3.1 更新 readme.md 中的 release_dir ---
README_FILE="readme.md"
README_FILE_EN="readme_en.md"
MD_FILE_1="1.项目简介.md"
MD_FILE_2="2.项目各依赖安装过程详细说明.md"
MD_FILE_3="3.项目详细讲解.md"
MD_FILE_1_EN="1.Project_Overview_EN.md"
MD_FILE_2_EN="2.Dependencies_Installation_Guide_EN.md"
MD_FILE_3_EN="3.Comprehensive_Technical_Guide_EN.md"
STARTUP_FILE="tkvoice.sh"
INSTALL_FILE="install.sh"
INSTALL_FILE2="install_for_regions_outside_of_China.sh"
if [ -f "$README_FILE" ]; then
    # 读取旧的 release_dir 值
    old_dir=$(grep -E '^release_dir=' "$README_FILE" | head -n1 | cut -d'=' -f2)
    
    if [ -n "$old_dir" ]; then
        echo "[INFO] 将 $README_FILE 中的所有 ${old_dir} 替换为 ${RELEASE_DIR}"
        # 替换整个文件中所有 old_dir 为新 RELEASE_DIR
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$README_FILE"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$README_FILE_EN"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_1"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_2"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_3"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_1_EN"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_2_EN"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$MD_FILE_3_EN"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$STARTUP_FILE"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$INSTALL_FILE"
        sed -i -E "s,${old_dir},${RELEASE_DIR},g" "$INSTALL_FILE2"
    else
        echo "[WARN] 未找到 release_dir= 行，跳过替换"
    fi
else
    echo "[WARN] 未找到 $README_FILE，跳过更新 release_dir"
fi

# --- 4. 打包整个发布目录 ---
echo "[INFO] 生成最终压缩包 ${RELEASE_DIR}.tar ..."

tar -cvf "${RELEASE_DIR}.tar" \
    -C . src \
    res/docker_funasr/asr.latest.tar.gz \
    res/docker_funasr/model.tar.gz \
    res/docker_funasr/install_asr.sh \
    res/docker_funasr/uninstall_asr.sh \
    res/docker_funasr/startup.sh \
    res/ollama/install_ollama.sh \
    res/ollama/uninstall_ollama.sh \
    res/piper_voices/zh/zh_CN-huayan-medium.onnx.json \
    res/piper_voices/zh/zh_CN-huayan-medium.onnx \
    res/onnxruntime_gpu-1.20.1-cp310-cp310-linux_aarch64.whl \
    install.sh uninstall.sh tkvoice.sh --transform="s,^,${RELEASE_DIR}/," \
    -C "${RELEASE_DIR}" version.txt

echo "[OK] 打包完成: ${RELEASE_DIR}.tar"

rm -rf "${RELEASE_DIR}"
echo "[OK] 已删除打包临时目录: ${RELEASE_DIR}"