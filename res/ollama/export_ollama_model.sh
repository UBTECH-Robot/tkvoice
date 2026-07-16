#!/bin/bash
# export_ollama_model.sh
# 用法: sudo ./export_ollama_model.sh <模型名:tag>
# 示例: sudo ./export_ollama_model.sh qwen2.5:1.5b
# 输出 tar.gz 在当前目录，完整日志

set -e
set -o pipefail

if [ $# -ne 1 ]; then
    echo "用法: $0 <模型名:tag>"
    exit 1
fi

MODEL_FULL="$1"
MODEL_NAME="${MODEL_FULL%%:*}"  # 冒号前
MODEL_TAG="${MODEL_FULL##*:}"   # 冒号后

OLLAMA_DIR="/home/ollama/.ollama/models"
CUR_DIR=$(pwd)
OUTPUT_FILE="$CUR_DIR/${MODEL_NAME}_${MODEL_TAG}.tar.gz"

echo "=============================="
echo "导出 Ollama 模型: $MODEL_NAME:$MODEL_TAG"
echo "当前目录: $CUR_DIR"
echo "输出文件: $OUTPUT_FILE"
echo "=============================="

# 创建临时目录
TMP_DIR=$(mktemp -d "$CUR_DIR/ollama_export_tmp.XXXX")
echo "临时目录: $TMP_DIR"

# 复制 manifest
echo "复制 manifest..."
mkdir -p "$TMP_DIR/manifests/registry.ollama.ai/library/$MODEL_NAME"
cp -rv "$OLLAMA_DIR/manifests/registry.ollama.ai/library/$MODEL_NAME/$MODEL_TAG" \
    "$TMP_DIR/manifests/registry.ollama.ai/library/$MODEL_NAME/" 2>&1

MANIFEST_FILE="$OLLAMA_DIR/manifests/registry.ollama.ai/library/$MODEL_NAME/$MODEL_TAG"

# 解析 manifest 获取 blobs（冒号替换为横杠）
echo "解析 manifest 获取 blobs..."
DIGESTS=$(jq -r '.layers[].digest' "$MANIFEST_FILE" | sed 's/:/-/')
echo "找到 blobs: $DIGESTS"

# 复制 blobs
echo "复制 blobs..."
mkdir -p "$TMP_DIR/blobs"
for DIGEST in $DIGESTS; do
    SRC_BLOB="$OLLAMA_DIR/blobs/$DIGEST"
    if [ ! -f "$SRC_BLOB" ]; then
        echo "警告：找不到 blob 文件 $SRC_BLOB"
        continue
    fi
    cp -v "$SRC_BLOB" "$TMP_DIR/blobs/" 2>&1 | tee -a /tmp/export_blobs.log
done

# 打包 tar.gz
echo "打包为 tar.gz..."
tar -czvf "$OUTPUT_FILE" -C "$TMP_DIR" manifests blobs 2>&1 | tee /tmp/export_tar.log

# 清理临时目录
echo "清理临时目录..."
rm -rf "$TMP_DIR"

echo "=============================="
echo "导出完成: $OUTPUT_FILE"
echo "日志文件:"
echo "  Manifest 复制: /tmp/export_manifest.log"
echo "  Blobs 复制   : /tmp/export_blobs.log"
echo "  打包 tar.gz  : /tmp/export_tar.log"
echo "=============================="
