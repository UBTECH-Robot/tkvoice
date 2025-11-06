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
OLLAMA_DIR="/home/ollama/.ollama/models"
TMP_DIR="./ollama_import_tmp_$$"
LOG_FILE="./import_model.log"

echo "=============================================="
echo "🔍 模型导入开始：$(date '+%F %T')"
echo "📦 模型文件：$TAR_FILE"
echo "📁 目标目录：$OLLAMA_DIR"
echo "🧩 临时目录：$TMP_DIR"
echo "📜 日志文件：$LOG_FILE"
echo "=============================================="
echo ""

# 检查文件存在
if [ ! -f "$TAR_FILE" ]; then
    echo "❌ 错误：找不到文件：$TAR_FILE"
    exit 1
fi

# 创建临时目录
mkdir -p "$TMP_DIR"

# 解压模型到临时目录（避免直接污染目标目录）
echo "🧰 正在解压模型包..."
tar -xzvf "$TAR_FILE" -C "$TMP_DIR"

# 确保 Ollama 模型目录存在
echo "🗂️ 确保目标目录存在..."
sudo -u ollama mkdir -p "$OLLAMA_DIR"

# 移动 manifests 目录
if [ -d "$TMP_DIR/manifests" ]; then
    echo "[INFO] 移动 manifests 到 $OLLAMA_DIR ..."
    sudo mv -v "$TMP_DIR/manifests" "$OLLAMA_DIR/" | tee -a "$LOG_FILE"
else
    echo "[WARN] 未找到 $TMP_DIR/manifests 目录，跳过。"
fi

# 移动 blobs 目录
if [ -d "$TMP_DIR/blobs" ]; then
    echo "[INFO] 移动 blobs 到 $OLLAMA_DIR ..."
    sudo mv -v "$TMP_DIR/blobs" "$OLLAMA_DIR/" | tee -a "$LOG_FILE"
else
    echo "[WARN] 未找到 $TMP_DIR/blobs 目录，跳过。"
fi

sudo chown -R ollama:ollama "$OLLAMA_DIR"

# 删除临时目录
echo "🧹 清理临时目录..."
sudo rm -rf "$TMP_DIR"

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
