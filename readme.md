# tkvoice

离线语音交互服务。
唤醒词"天工天工/天空天空"可打断当前回答

## 依赖

- ROS2 Jazzy
- Python 3.12
- NVIDIA GPU

## 安装(必须联网，安装好后不用联网)
#拷贝到 41.2 的 Orin 板
scp tkvoice_release_0.3.38_0623_115538.tar nvidia@192.168.41.2:/home/nvidia
tar xf tkvoice_release_0.3.38_0623_115538.tar
cd tkvoice_release_0.3.38_0623_115538
chmod +x install.sh
./install.sh
# 注意，执行 install.sh 的时候会多次要求输入密码， Orin 板上 nvidia 用户的密码nvidia
```

## 启动

```
chmod +x tkvoice.sh
./tkvoice.sh start
```

## 管理

```
./tkvoice.sh stop      # 停止
./tkvoice.sh restart   # 重启
./tkvoice.sh status    # 查看状态
tail -f tkvoice.log    # 查看日志
```

## ROS2 节点

| 节点 | 说明 |
|------|------|
| `tk_audio_publisher` | 麦克风音频采集 + VAD |
| `tk_asr_text_publisher` | ASR 语音识别（SenseVoice） |
| `tk_audio_process` | LLM（Ollama）+ TTS（CosyVoice2） |


