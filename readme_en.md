# tkvoice

Offline voice interaction service.
Wake words "天工天工/天空天空" can interrupt current response.

## Requirements

- ROS2 Jazzy
- Python 3.12
- NVIDIA GPU

## Install (internet required for install, offline after setup)

```bash
# Copy to Orin board (41.2)
scp tkvoice_release_0.3.38_0623_115538.tar nvidia@192.168.41.2:/home/nvidia
tar xf tkvoice_release_0.3.38_0623_115538.tar
cd tkvoice_release_0.3.38_0623_115538
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
