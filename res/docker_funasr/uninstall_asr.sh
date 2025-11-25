#!/bin/bash
set -e

sudo -n true 2>/dev/null && echo "✅ 无需输入密码" || echo "⚠️ 执行 sudo 时会提示输入密码"

# -----------------------------
# 配置变量（与 install.sh 保持一致）
# -----------------------------
IMAGE_NAME="asr:latest"
CONTAINER_NAME="funasr_container"
MODELS_DIR="/home/ubuntu/Documents/asr-runtime-resources/models"
STARTUP_SH="/home/ubuntu/Documents/asr-runtime-resources/startup.sh"

echo "=============================="
echo "🧹 Docker 与容器自动清理脚本"
echo "=============================="

# -----------------------------
# 1. 停止并删除容器
# -----------------------------
if command -v docker &>/dev/null; then
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "停止容器 $CONTAINER_NAME ..."
        docker stop "$CONTAINER_NAME" || true

        echo "删除容器 $CONTAINER_NAME ..."
        docker rm -f "$CONTAINER_NAME" || true
    else
        echo "容器 $CONTAINER_NAME 不存在，跳过。"
    fi
else
    echo "Docker 未安装，跳过容器删除步骤。"
fi

# -----------------------------
# 2. 删除镜像
# -----------------------------
if command -v docker &>/dev/null; then
    if docker image inspect "$IMAGE_NAME" &>/dev/null; then
        echo "删除镜像 $IMAGE_NAME ..."
        docker rmi -f "$IMAGE_NAME" || true
    else
        echo "镜像 $IMAGE_NAME 不存在，跳过。"
    fi
else
    echo "Docker 未安装，跳过镜像删除步骤。"
fi

# -----------------------------
# 3. 清理未使用的资源
# -----------------------------
if command -v docker &>/dev/null; then
    echo "清理未使用的卷、网络、镜像 ..."
    docker system prune -a -f --volumes || true
fi

# -----------------------------
# 4. 停止并禁用 Docker 服务
# -----------------------------
if systemctl list-units --type=service | grep -q docker.service; then
    echo "停止 Docker 服务 ..."
    sudo systemctl stop docker || true

    echo "禁用 Docker 开机启动 ..."
    sudo systemctl disable docker || true
fi

# -----------------------------
# 5. 卸载 Docker 相关组件
# -----------------------------
if command -v docker &>/dev/null; then
    echo "检测到 Docker 命令，准备卸载 Docker 软件包 ..."

    echo "执行 Docker 卸载 ..."
    if ! sudo apt purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; then
        echo "⚠️ 卸载过程中出现依赖错误，尝试自动修复 ..."
        sudo apt --fix-broken install -y
        echo "再次尝试卸载 Docker ..."
        sudo apt purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || true
    fi

    echo "清理 apt 缓存（安全操作）..."
    sudo apt autoclean -y

    echo "✅ Docker 已卸载完成。"
else
    echo "Docker 命令不存在，跳过卸载。"
fi


# -----------------------------
# 6. 删除 Docker 数据目录
# -----------------------------
echo "删除 Docker 数据目录 ..."
sudo rm -rf /var/lib/docker /var/lib/containerd /etc/docker /run/docker.sock
sudo rm -rf $MODELS_DIR $STARTUP_SH

# -----------------------------
# 7. 清理 docker 用户组配置
# -----------------------------
if getent group docker >/dev/null; then
    echo "从 docker 用户组中移除当前用户 $USER ..."
    sudo gpasswd -d "$USER" docker || true

    echo "删除 docker 用户组 ..."
    sudo groupdel docker || true
fi

# -----------------------------
# 8. 保留资源文件与安装包
# -----------------------------
# echo "保留资源目录与安装包（未删除任何文件）"

# -----------------------------
# 9. 最终状态检查
# -----------------------------
hash -r

echo ""
echo "=============================="
echo "✅ 清理完成！当前状态："
echo "=============================="
if command -v docker >/dev/null; then
    echo "⚠️ Docker 命令仍存在（可能部分组件未清除）"
else
    echo "✅ Docker 命令已删除"
fi
echo "=============================="
# rm -rf /home/ubuntu/docker_funasr
# echo "✅ 已删除 docker_funasr 目录"