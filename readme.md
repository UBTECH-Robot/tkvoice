# tkvoice

离线语音交互解决方案，集成 ASR、LLM、TTS 全链路。

## 架构

```
用户说话 → VAD → ASR(SenseVoice) → LLM(Ollama + qwen2.5:1.5b) → TTS(CosyVoice2) → 音箱
```

- **ASR**: SenseVoice（本地加载，无需 Docker）
- **LLM**: Ollama + qwen2.5:1.5b
- **TTS**: CosyVoice2-0.5B（24000Hz，fp16 加速）
- **中断**: 唤醒词"天工天工/天空天空"可打断当前回答

## 快速安装

```bash
# 1. 解压发布包
tar xf tkvoice_release_X.tar
cd tkvoice_release_X

# 2. 一键安装（Python依赖 + Ollama + LLM模型 + 编译）
./install.sh

# 3. 启动服务
./tkvoice.sh start

# 4. 查看日志
tail -f tkvoice.log
```

## 环境要求

- ROS2 Jazzy
- Python 3.12
- NVIDIA GPU（推荐 Thor/Orin 系列）
- 麦克风 + 音箱（通过 PipeWire 管理）

## 目录结构

```
tkvoice_release_X/
├── CosyVoice2-0.5B/          # TTS 模型
├── cosyvoice/                 # TTS Python 源码
├── matcha/                    # matcha-tts shim
├── src/                       # ROS2 源码
│   └── audio_service/         # VAD / ASR / LLM / TTS 节点
├── res/
│   └── ollama/                # Ollama 二进制 + qwen2.5 模型
├── install.sh                 # 安装脚本
├── tkvoice.sh                 # 服务管理（start/stop/restart/status）
└── requirements_tkvoice.txt   # Python 依赖清单
```

## 服务管理

```bash
./tkvoice.sh start     # 启动
./tkvoice.sh stop      # 停止
./tkvoice.sh restart   # 重启
./tkvoice.sh status    # 查看状态
```

## 配置

通过环境变量配置：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PRIMARY_MODEL` | `qwen2.5:1.5b` | LLM 模型 |
| `TTS_WORKERS` | `1` | TTS 并行数 |
| `TTS_GAIN` | `2.5` | TTS 音量增益 |
| `TTS_SPEED` | `1.05` | 语速 |
| `COSYVOICE_FP16` | `1` | TTS fp16 加速 |
