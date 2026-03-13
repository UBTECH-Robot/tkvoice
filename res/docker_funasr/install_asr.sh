#!/bin/bash
set -e
export DEBIAN_FRONTEND=noninteractive

# -----------------------------
# 配置变量
# -----------------------------
IMAGE_NAME="asr:latest"
IMAGE_TAR="./asr.latest.tar.gz"
MODELS_DIR="/home/ubuntu/Documents/asr-runtime-resources/models"
STARTUP_SH="/home/ubuntu/Documents/asr-runtime-resources/startup.sh"
CONTAINER_NAME="funasr_container"
HOST_PORT=10097
CONTAINER_PORT=10095

# -----------------------------
# 1. 检查 Docker
# -----------------------------
echo "[1/5] 检查 Docker 环境..."
if ! command -v docker &>/dev/null; then
    echo "❌ 未检测到 Docker，将自动安装..."
    INSTALL_DOCKER=true
else
    echo "✅ 检测到 Docker 命令"
    if ! sudo systemctl is-active --quiet docker; then
        echo "🔄 启动 Docker 服务..."
        sudo systemctl enable docker
        sudo systemctl start docker
    fi

    if ! docker info &>/dev/null; then
        echo "⚠️  Docker 服务似乎无法访问，将尝试重新安装"
        INSTALL_DOCKER=true
    else
        echo "✅ Docker 服务可用"
        INSTALL_DOCKER=false
    fi
fi

download_file() {
    local url="$1"
    local output="$2"
    local max_retries=3
    local count=0

    echo "⬇️  正在下载文件：$output"
    echo "    来源：$url"

    until [ $count -ge $max_retries ]; do
        ((count++))
        if wget -q --show-progress -O "$output" "$url"; then
            echo "✅ 下载成功: $output"
            return 0
        else
            echo "⚠️  下载失败 (第 $count 次)"
            sleep 2
        fi
    done

    echo "⛔ 下载 ${url} 到 ${output} 失败超过 ${max_retries} 次，退出脚本。您可尝试手动下载。"
    exit 1
}

# -----------------------------
# 2. 安装 Docker（如需）
# -----------------------------
if [ "$INSTALL_DOCKER" = true ]; then
    echo "[2/5] 安装 Docker 组件..."

    declare -A DEB_FILES=(
        ["containerd.io_1.6.33-1_amd64.deb"]="https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/containerd.io_1.6.33-1_amd64.deb"
        ["docker-ce-cli_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"]="https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/docker-ce-cli_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"
        ["docker-ce_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"]="https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/docker-ce_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"
        ["docker-buildx-plugin_0.14.1-1~ubuntu.22.04~jammy_amd64.deb"]="https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/docker-buildx-plugin_0.14.1-1~ubuntu.22.04~jammy_amd64.deb"
        ["docker-compose-plugin_2.27.1-1~ubuntu.22.04~jammy_amd64.deb"]="https://download.docker.com/linux/ubuntu/dists/jammy/pool/stable/amd64/docker-compose-plugin_2.27.1-1~ubuntu.22.04~jammy_amd64.deb"
    )

    TARGET_DIR="/home/ubuntu/docker_funasr"
    mkdir -p "$TARGET_DIR"

    for f in "${!DEB_FILES[@]}"; do
        if [ ! -f "$f" ]; then
            download_file "${DEB_FILES[$f]}" "$TARGET_DIR/$f"
        else
            echo "✅ 已存在: $f"
        fi
    done

    echo "🎉 所有安装文件已准备就绪。"
        
    # 要安装的包
    PACKAGES=(ca-certificates curl gnupg lsb-release)

    # 检查包是否已安装
    all_installed=true
    for pkg in "${PACKAGES[@]}"; do
        if ! dpkg -s "$pkg" &> /dev/null; then
            all_installed=false
            break
        fi
    done

    if [ "$all_installed" = true ]; then
        echo "[INFO] 所有依赖包已安装，跳过 apt update 和安装"
    else
        echo "[INFO] 有未安装的包，先更新 apt 缓存，再安装所需包"
        sudo apt update -y
        sudo apt install -y "${PACKAGES[@]}"
    fi

    INSTALL_ORDER=(
        "containerd.io_1.6.33-1_amd64.deb"
        "docker-ce-cli_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"
        "docker-ce_26.1.4-1~ubuntu.22.04~jammy_amd64.deb"
        "docker-buildx-plugin_0.14.1-1~ubuntu.22.04~jammy_amd64.deb"
        "docker-compose-plugin_2.27.1-1~ubuntu.22.04~jammy_amd64.deb"
    )

    for pkg in "${INSTALL_ORDER[@]}"; do
        echo "📦 安装 $pkg ..."
        sudo dpkg -i "$pkg" || sudo apt -f install -y
    done

    sudo systemctl enable docker
    sudo systemctl start docker
    sudo usermod -aG docker "$USER"
    sudo usermod -aG docker ubuntu

    echo "✅ Docker 安装完成"
fi

# -----------------------------
# 3. 确保 startup.sh 存在
# -----------------------------
echo "[3/5] 检查 startup.sh ..."
if [ -f "./startup.sh" ]; then
    sudo rm -rf "$STARTUP_SH"
    sudo mkdir -p "$(dirname "$STARTUP_SH")"
    sudo cp ./startup.sh "$STARTUP_SH"
    sudo chmod +x "$STARTUP_SH"
    echo "✅ startup.sh 已复制到目标路径"
else
    echo "❌ 当前目录下缺少 startup.sh"
    exit 1
fi


# -----------------------------
# 4. 加载镜像
# -----------------------------
echo "[4/5] 检查镜像 $IMAGE_NAME ..."
if ! sudo docker image inspect "$IMAGE_NAME" &>/dev/null; then
    if [ -f "$IMAGE_TAR" ]; then
        echo "🗜️  加载镜像中..."
        sudo docker load -i "$IMAGE_TAR"
        echo "✅ 镜像加载完成"
    else
        echo "❌ 未找到镜像文件 $IMAGE_TAR"
        exit 1
    fi
else
    echo "✅ 镜像已存在"
fi

# -----------------------------
# 5. 启动容器
# -----------------------------
echo "[5/5] 启动容器 $CONTAINER_NAME ..."

if sudo docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "⚙️  删除旧容器..."
    sudo docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

mkdir -p "$(dirname "$MODELS_DIR")"
sudo chown root:docker "$(dirname "$MODELS_DIR")"

if [ -f "models.tar.gz" ]; then
    # 计算压缩包解压后的预期大小
    tar_size=$(tar -tzvf models.tar.gz | awk '{sum+=$3} END {printf "%.0f", sum}')

    # 检查是否需要解压
    need_extract=true
    if [ -d "$MODELS_DIR" ] && [ -n "$tar_size" ] && [ "$tar_size" -gt 0 ]; then
        dir_size=$(du -sb "$MODELS_DIR" 2>/dev/null | awk '{print $1}')
        # 允许 5% 的误差范围（文件系统开销可能导致细微差异）
        diff=$((dir_size > tar_size ? dir_size - tar_size : tar_size - dir_size))
        threshold=$((tar_size / 20))  # 5%
        if [ "$diff" -le "$threshold" ]; then
            echo "✅ 模型目录已存在且大小匹配 ($dir_size vs $tar_size)，跳过解压"
            need_extract=false
        fi
    fi

    if [ "$need_extract" = true ]; then
        if [ -d "$MODELS_DIR" ]; then
            echo "清空旧模型目录 $MODELS_DIR ..."
            sudo rm -rf "$MODELS_DIR"
        fi
        echo "📂 解压模型文件..."
        sudo tar -zxvf models.tar.gz -C "$(dirname "$MODELS_DIR")"
        sudo chmod -R 777 "$MODELS_DIR"
    fi
else
    echo "⚠️  未找到 models.tar.gz，跳过模型解压。"
fi

if ! sudo docker image inspect "$IMAGE_NAME" &>/dev/null; then
    echo "❌ 未找到 funasr 镜像 $IMAGE_TAR，无法启动 Funasr 容器"
    exit 1
else        
    sudo docker run -d --name "$CONTAINER_NAME" --privileged \
        -v "$MODELS_DIR:/workspace/models" \
        -v "$STARTUP_SH:/workspace/startup.sh" \
        -w /workspace \
        -p $HOST_PORT:$CONTAINER_PORT \
        --restart=on-failure:3 \
        "$IMAGE_NAME" \
        bash /workspace/startup.sh

    echo "✅ 容器已启动，端口映射 $HOST_PORT -> $CONTAINER_PORT"
fi
