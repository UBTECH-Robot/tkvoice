#!/bin/bash
# ================================================
# Ollama 模型导入脚本
# 用法: sudo ./import_ollama_model.sh qwen2.5_1.5b.tar.gz
# 在当前目录下执行，无需交互。
# ================================================

set -e

# 参数检查
if [ $# -ne 1 ]; then
    echo "用法: $0 <模型打包文件.tar.gz>"
    exit 1
fi

TAR_FILE="$1"
BASE_DIR="$2"
OLLAMA_DIR="/home/ollama/.ollama/models"
LOG_FILE="./import_model.log"

echo "=============================================="
echo "🔍 模型导入开始：$(date '+%F %T')"
echo "📦 模型文件：$TAR_FILE"
echo "📁 目标目录：$OLLAMA_DIR"
echo "📜 日志文件：$LOG_FILE"
echo "=============================================="
echo ""

# 检查文件存在
if [ ! -f "$TAR_FILE" ]; then
    echo "❌ 错误：找不到文件：$TAR_FILE"
    if ! tar -tf "${BASE_DIR}.tar" | grep -q "${BASE_DIR}/res/ollama/${TAR_FILE}"; then
        echo "[ERROR] 发布包中未找到 ${BASE_DIR}/res/ollama/${TAR_FILE}"
        exit 1
    fi
    echo "📦 从发布包中提取Ollama模型文件 ${TAR_FILE}..."

    tar -xvf "${BASE_DIR}.tar" \
        "${BASE_DIR}/res/ollama/${TAR_FILE}"
fi

# 确保 Ollama 模型目录存在
echo "🗂️ 确保目标目录存在..."
sudo mkdir -p "$OLLAMA_DIR" || { echo "Failed to create dir"; }
sudo tar -zxvf "$TAR_FILE" -C "$OLLAMA_DIR" || { echo "Failed to extract"; }
sudo chown -R ollama:ollama "$OLLAMA_DIR" || { echo "Failed to chown"; }
sudo rm -rf "$TAR_FILE"

MAX_RETRIES=3
RETRY_DELAY=5  # 每次重试间隔秒数
attempt=1

while (( attempt <= MAX_RETRIES )); do
    echo "[INFO] 第 ${attempt}/${MAX_RETRIES} 次尝试下载模型..."
    if sudo -u ollama ollama pull qwen2.5:1.5b; then
        echo "✅ 模型 qwen2.5:1.5b 下载完成。"
        break
    else
        echo "⚠️ ollama pull 失败（第 ${attempt} 次）。"
        if (( attempt < MAX_RETRIES )); then
            echo "⏳ 等待 ${RETRY_DELAY} 秒后重试..."
            sleep "${RETRY_DELAY}"
        fi
    fi
    ((attempt++))
done

# 检查最终是否成功
if (( attempt > MAX_RETRIES )); then
    echo "❌ 模型下载失败，请检查网络或稍后手动执行：ollama pull qwen2.5:1.5b"
    exit 1
fi


# 输出导入结果
echo ""
echo "✅ 模型导入完成！"
echo "📂 导入后的模型目录结构："
sudo -u ollama ls -lh "$OLLAMA_DIR/manifests/registry.ollama.ai/library/" | tee -a "$LOG_FILE"

echo ""
echo "✅ 完成：$(date '+%F %T')"
echo "📜 日志已保存到 $LOG_FILE"
echo "=============================================="
