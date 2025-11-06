#!/bin/bash
set -e  # 出错立即退出

echo "=============================================="
echo "[Startup] $(date '+%Y-%m-%d %H:%M:%S') 启动 FunASR 容器..."
echo "=============================================="

sudo rm -rf /workspace/funasr_server.log || true

# 检查模型目录
if [ ! -d "/workspace/models" ]; then
    echo "[Error] 模型目录 /workspace/models 不存在！"
    exit 1
fi

echo "[Startup] 模型目录检测通过：/workspace/models"
ls -lh /workspace/models || true
echo "----------------------------------------------"

# 启动 WebSocket 服务
echo "[Startup] 启动 FunASR WebSocket 服务..."
/workspace/FunASR/runtime/websocket/build/bin/funasr-wss-server-2pass \
  --certfile /workspace/FunASR/runtime/ssl_key/server.crt \
  --decoder-thread-num 12 \
  --download-model-dir /workspace/models \
  --hotword /workspace/models/hotwords.txt \
  --io-thread-num 1 \
  --itn-dir thuduj12/fst_itn_zh \
  --keyfile /workspace/FunASR/runtime/ssl_key/server.key \
  --lm-dir damo/speech_ngram_lm_zh-cn-ai-wesp-fst \
  --model-dir damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx \
  --model-thread-num 1 \
  --online-model-dir damo/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online-onnx \
  --port 10095 \
  --punc-dir damo/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727-onnx \
  --vad-dir damo/speech_fsmn_vad_zh-cn-16k-common-onnx \
  > /workspace/funasr_server.log 2>&1 &

echo "[Startup] FunASR WebSocket 服务已启动 (PID: $!)"
echo "[Startup] 日志文件：/workspace/funasr_server.log"
echo "----------------------------------------------"

# 启动进度监控脚本
echo "[Startup] 启动进度监控脚本..."
python /workspace/FunASR/funasr/utils/funasr_progress.py \
  > /workspace/funasr_progress.log 2>&1 &

echo "[Startup] 进度脚本已启动 (PID: $!)"
echo "[Startup] 日志文件：/workspace/funasr_progress.log"
echo "----------------------------------------------"

# 保持容器运行
echo "[Startup] 所有服务启动完成，容器进入守护状态。"
echo "[Startup] 使用 'docker logs -f <container>' 查看实时输出。"
echo "=============================================="

tail -f /workspace/funasr_server.log
