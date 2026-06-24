# tkvoice

Offline voice interaction solution with ASR, LLM, and TTS pipeline.

## Architecture

```
User Speech → VAD → ASR(SenseVoice) → LLM(Ollama + qwen2.5:1.5b) → TTS(CosyVoice2) → Speaker
```

- **ASR**: SenseVoice (local model, no Docker required)
- **LLM**: Ollama + qwen2.5:1.5b
- **TTS**: CosyVoice2-0.5B (24000Hz, fp16 accelerated)
- **Interrupt**: Wake words "天工天工/天空天空" to interrupt current response

## Quick Install

```bash
# 1. Extract release
tar xf tkvoice_release_X.tar
cd tkvoice_release_X

# 2. One-click install (Python deps + Ollama + LLM model + build)
./install.sh

# 3. Start service
./tkvoice.sh start

# 4. View logs
tail -f tkvoice.log
```

## Requirements

- ROS2 Jazzy
- Python 3.12
- NVIDIA GPU (Thor/Orin series recommended)
- Microphone + Speaker (managed via PipeWire)

## Directory Structure

```
tkvoice_release_X/
├── CosyVoice2-0.5B/          # TTS model
├── cosyvoice/                 # TTS Python source
├── matcha/                    # matcha-tts shim
├── src/                       # ROS2 source
│   └── audio_service/         # VAD / ASR / LLM / TTS nodes
├── res/
│   └── ollama/                # Ollama binary + qwen2.5 model
├── install.sh                 # Install script
├── tkvoice.sh                 # Service manager (start/stop/restart/status)
└── requirements_tkvoice.txt   # Python dependencies
```

## Service Management

```bash
./tkvoice.sh start     # Start
./tkvoice.sh stop      # Stop
./tkvoice.sh restart   # Restart
./tkvoice.sh status    # View status
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PRIMARY_MODEL` | `qwen2.5:1.5b` | LLM model |
| `TTS_WORKERS` | `1` | TTS worker count |
| `TTS_GAIN` | `2.5` | TTS volume gain |
| `TTS_SPEED` | `1.05` | Speech speed |
| `COSYVOICE_FP16` | `1` | TTS fp16 acceleration |
