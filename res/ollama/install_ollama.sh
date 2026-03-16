#!/bin/bash
set -e

echo "[0/11] 检查 Ollama 服务状态..."
PARENT_DIR="$1"
RELEASE_DIR="$2"
BASE_DIR="${PARENT_DIR}/${RELEASE_DIR}"

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

if systemctl is-active --quiet ollama; then
    echo "✅ Ollama 服务正在运行。"

    if curl -fs http://127.0.0.1:11434/api/tags | grep -q '"qwen2.5:1.5b"'; then
        echo "✅ 模型 qwen2.5:1.5b 已存在。"
        echo "✅ 系统状态正常，无需重新安装。"
        exit 0
    else
        echo "⚠️ 模型 qwen2.5:1.5b 不存在，准备下载..."
        ollama pull qwen2.5:1.5b || {
            echo "❌ 模型下载失败，请检查网络或稍后手动执行：ollama pull qwen2.5:1.5b"
            exit 1
        }
        echo "✅ 模型 qwen2.5:1.5b 下载完成。"
        echo "✅ 无需重新安装。"
        exit 0
    fi
else
    echo "⚠️ Ollama 服务未运行，开始执行安装流程..."
fi

echo "[1/11] 先尝试停止并禁用旧服务..."
sudo systemctl stop ollama 2>/dev/null || true
sudo systemctl disable ollama 2>/dev/null || true

echo "[2/11] 删除旧服务文件与缓存..."
sudo rm -f /etc/systemd/system/ollama.service /var/log/ollama.log
sudo systemctl daemon-reload
sudo rm -f /usr/bin/ollama /usr/local/bin/ollama
sudo rm -rf /usr/share/ollama /usr/lib/ollama
sudo rm -rf ~/.ollama
sudo rm -rf /home/ollama
sudo rm -rf /home/*/.ollama 2>/dev/null || true

echo "[3/11] 删除旧用户和组..."
sudo userdel -r ollama 2>/dev/null || true
sudo groupdel ollama 2>/dev/null || true


# 安装包文件名
BASE_TGZ="ollama-linux-arm64.tar.zst"
JETPACK6_TGZ="ollama-linux-arm64-jetpack6.tar.zst"
BASE_URL="https://github.com/ollama/ollama/releases/download/v0.17.7/ollama-linux-arm64.tar.zst"
JETPACK6_URL="https://github.com/ollama/ollama/releases/download/v0.17.7/ollama-linux-arm64-jetpack6.tar.zst"

if [ ! -f "$BASE_TGZ" ]; then
    if ! tar --zstd -tf "${BASE_DIR}.tar.zst" | grep -q "/res/ollama/${BASE_TGZ}"; then
        echo "[WARN] 发布包中未找到 /res/ollama/${BASE_TGZ}，尝试下载..."
        download_file "$BASE_URL" "$BASE_TGZ"
    else
        echo "📦 从发布包中提取Ollama基础包 ${BASE_TGZ}..."
        tar -C "${PARENT_DIR}" --zstd -xvf "${BASE_DIR}.tar.zst" \
            "${RELEASE_DIR}/res/ollama/${BASE_TGZ}"
        # tar --delete -f "${BASE_DIR}.tar" "${RELEASE_DIR}/res/ollama/${BASE_TGZ}"
    fi
else
    echo "✅ 已存在: $BASE_TGZ"
fi
echo "[4/11] 安装基础 Ollama..."
sudo tar -C /usr -I zstd -xvf "$BASE_TGZ"
sudo rm -rf "$BASE_TGZ"

if [ ! -f /usr/bin/ollama ]; then
    echo "❌ 错误: /usr/bin/ollama 未找到，请检查 $BASE_TGZ 内容"
    exit 1
fi


if [ ! -f "$JETPACK6_TGZ" ]; then
    if ! tar --zstd -tf "${BASE_DIR}.tar.zst" | grep -q "/res/ollama/${JETPACK6_TGZ}"; then
        echo "[WARN] 发布包中未找到 /res/ollama/${JETPACK6_TGZ}，尝试下载..."
        download_file "$JETPACK6_URL" "$JETPACK6_TGZ"
    else
        echo "📦 从发布包中提取Ollama JetPack6包 ${JETPACK6_TGZ}..."
        tar -C "${PARENT_DIR}" --zstd -xvf "${BASE_DIR}.tar.zst" \
            "${RELEASE_DIR}/res/ollama/${JETPACK6_TGZ}"
        # tar --delete -f "${BASE_DIR}.tar" "${RELEASE_DIR}/res/ollama/${JETPACK6_TGZ}"
    fi
else
    echo "✅ 已存在: $JETPACK6_TGZ"
fi

echo "[5/11] 覆盖安装 JetPack6 GPU 优化版本..."
sudo tar -C /usr -I zstd -xvf "$JETPACK6_TGZ"
sudo rm -rf "$JETPACK6_TGZ"

echo "[6/11] 创建 Ollama 用户与主目录..."
sudo useradd -m -d /home/ollama -s /usr/sbin/nologin -U ollama 2>/dev/null || true
sudo mkdir -p /usr/lib/ollama
sudo mkdir -p /home/ollama/.ollama
sudo chown -R ollama:ollama /home/ollama

echo "[7/11] 创建 Ollama 工作目录..."
sudo mkdir -p /usr/share/ollama
sudo chown -R ollama:ollama /usr/share/ollama
sudo touch /var/log/ollama.log
sudo chown ollama:ollama /var/log/ollama.log
sudo usermod -aG video,render ollama
sudo chown -R root:ollama /usr/lib/ollama/cuda_jetpack6
sudo chmod -R 755 /usr/lib/ollama/cuda_jetpack6 
# 重要，确保组权限正确，否则Ollama服务无法访问Orin板的GPU

echo "[8/11] 安装 systemd 服务..."
sudo tee /etc/systemd/system/ollama.service >/dev/null <<'EOF'
[Unit]
Description=Ollama Service
After=network-online.target

[Service]
ExecStart=/usr/bin/ollama serve
User=ollama
Group=ollama
WorkingDirectory=/usr/share/ollama
Restart=always
RestartSec=3
StandardOutput=append:/var/log/ollama.log
StandardError=append:/var/log/ollama.log
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Environment="LD_LIBRARY_PATH=/usr/lib/ollama/cuda_jetpack6:/usr/local/cuda/lib64:/usr/lib"
Environment="OLLAMA_HOST=0.0.0.0:11434"

[Install]
WantedBy=multi-user.target
EOF

echo "[9/11] 启动服务..."
sudo systemctl daemon-reload
sudo systemctl enable ollama
sudo systemctl start ollama

echo "✅ Ollama 已成功安装并启动。"
systemctl status ollama --no-pager


echo "[10/11] 等待 Ollama 服务启动..."
for i in {1..10}; do
    if curl -fs http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "✅ Ollama 服务已就绪。"
        break
    fi
    echo "等待 Ollama 启动中... ($i/10)"
    sleep 1
done

sudo chmod +x import_ollama_model.sh
sudo ./import_ollama_model.sh qwen2.5_1.5b.tar.gz "${PARENT_DIR}" "${RELEASE_DIR}"

if curl -fs http://127.0.0.1:11434/api/tags | grep -q '"qwen2.5:1.5b"'; then
    echo "✅ 模型 qwen2.5:1.5b 导入成功。"
else
    echo "⚠️ 模型 qwen2.5:1.5b 不存在，现准备下载..."

    MAX_RETRIES=3
    RETRY_DELAY=5  # 每次重试间隔秒数
    attempt=1

    while (( attempt <= MAX_RETRIES )); do
        echo "[INFO] 第 ${attempt}/${MAX_RETRIES} 次尝试下载模型..."
        if ollama pull qwen2.5:1.5b; then
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
fi


echo "💡 查看 Ollama 日志："
echo "tail -n 100 -f /var/log/ollama.log"
echo "💡 检查 GPU 使用情况："
echo "sudo tegrastats"

# listen on port:10095