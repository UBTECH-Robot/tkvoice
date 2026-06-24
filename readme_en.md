# tkvoice

Offline voice interaction service.

## Requirements

- ROS2 Jazzy
- Python 3.12
- NVIDIA GPU

## Install

```bash
# Copy to Orin board (41.2)
scp tkvoice_release_X.tar nvidia@192.168.41.2:/home/nvidia
tar xf tkvoice_release_X.tar
cd tkvoice_release_X
chmod +x install.sh
./install.sh
# Note: install.sh will prompt for passwords (nvidia user password: nvidia)
```

## Start

```bash
chmod +x tkvoice.sh
./tkvoice.sh start
```

## Manage

```bash
./tkvoice.sh stop      # Stop
./tkvoice.sh restart   # Restart
./tkvoice.sh status    # Status
tail -f tkvoice.log    # Logs
```

## ROS2 Nodes

| Node | Description |
|------|-------------|
| `tk_audio_publisher` | Mic capture + VAD |
| `tk_asr_text_publisher` | ASR (SenseVoice) |
| `tk_audio_process` | LLM (Ollama) + TTS (CosyVoice2) |
