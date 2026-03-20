# 前言

更详细介绍，可参考[【文档】](https://docs.ubtrobot.com/walker-tienkung/docs/tkvoice/offline/1)

整个项目包含离线ASR能力（使用的Funasr），离线大语言模型（使用的Ollama），离线TTS能力（使用的piper-tts）。

整个项目无特殊说明的部分都是以 Apache-2.0 license 开源的，特殊部分为直接依赖 piper-tts 的代码，因为受 piper-tts 的 GPL-3.0 license 的限制，因此也以 GPL-3.0 license 开源。

# 开发需知

注意：以下一到三仅是对本项目的各部分依赖如何单独安装进行了简单介绍，以增加对项目的了解，如果只是想知道如何快速进行安装，可以直接看下面的 **安装** 步骤。如果想详细了解各依赖安装过程，请参考项目根目录下的 `2.项目各依赖安装过程详细说明.md`

## 一、离线ASR能力
使用的Funasr，服务运行在 192.168.41.1 x86 机器，是一个docker服务，镜像是 asr:latest 。

所以使用本项目asr能力的前提是需要在 x86 上安装docker服务并且拉取下 asr:latest 镜像，然后启动一个Funasr的容器。

### 1.1 docker的安装

方法一、可参考项目根目录下 `/res/docker/install_asr.sh` 脚本，里面标注了应该如何下载docker的离线安装包，以及如何进行安装。当前安装脚本，会启动funasr容器，并在 10097 端口提供服务。

方法二、参考如下步骤：
```bash
curl -O https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/shell/install_docker.sh；
sudo bash install_docker.sh
```

下面两种启动镜像的方式可选一种：

### 1.2.1 使用现有镜像启动容器（选项1）
使用 `/res/docker/install_asr.sh` 脚本，直接导入项目准备好的funasr镜像，并启动容器。

### 1.2.2 拉取镜像并启动（选项2）
参考Funasr官方文档：https://github.com/modelscope/FunASR/blob/main/runtime/docs/SDK_advanced_guide_offline_zh.md
安装完成后，通过下述命令拉取并启动FunASR软件包的docker镜像：

```bash
sudo docker pull \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-cpu-0.4.7
mkdir -p ./funasr-runtime-resources/models
sudo docker run --restart=always -p 10097:10095 -it --privileged=true \
  -v $PWD/funasr-runtime-resources/models:/workspace/models \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-cpu-0.4.7
```

### 1.3 服务端启动（仅在参考Funasr官方文档拉取Funasr镜像后需要执行）
docker启动之后，进入到docker里边启动 funasr-wss-server服务程序：
```bash
cd FunASR/runtime
nohup bash run_server.sh \
  --download-model-dir /workspace/models \
  --vad-dir damo/speech_fsmn_vad_zh-cn-16k-common-onnx \
  --model-dir damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-onnx  \
  --punc-dir damo/punc_ct-transformer_cn-en-common-vocab471067-large-onnx \
  --lm-dir damo/speech_ngram_lm_zh-cn-ai-wesp-fst \
  --itn-dir thuduj12/fst_itn_zh \
  --hotword /workspace/models/hotwords.txt > log.txt 2>&1 &
```

请注意 docker 的安装是在41.1的 x86 机器上。

## 二、离线大语言模型
使用的Ollama，服务运行在 192.168.41.2 Orin板，Orin板有275 tops的GPU算力，相对而言更适合运行大语言模型。所以使用本项目自然语言理解的前提是需要在 41.2 Orin板上安装了Ollama服务，并且拉取下来 qwen2.5:1.5b 模型，项目内默认使用的是这个模型。

ollama的安装步骤可参考项目根目录下 `/res/ollama/install_ollama.sh` 脚本，里面也有注释标明如何下载 ollama 的安装包，以及详细安装步骤。请注意 ollama 的安装是在41.2的 Orin 板机器上。

## 三、离线TTS能力
使用的piper-tts，其 pypi 主页为：https://pypi.org/project/piper-tts/

其 Python API 使用介绍在 github: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md

其使用 GPL-3.0 license 开源协议，本项目也将使用 GPL-3.0 协议。


## 四、代码说明

整个应用的运行流程是：
1. Orin板上 tk_audio_publisher 节点从RK3588s获取音频流，按整句的音频流发布到 audio_sentence_frames 话题；

2. Orin板上的节点 tk_asr_text_publisher 订阅 audio_sentence_frames 话题，获取到原生音频流后通过websocket发送到 x86 板子上的Funasr服务，并获取到语音识别后对应的文本，将其发布到 asr_sentence 话题；

3. Orin板上的节点 tk_audio_process 订阅 asr_sentence 话题，获取到提问文本后，将提问发送到Ollama服务，流式获取回答。每获取到一个回答文本，就调用离线TTS库转为对应的语音，然后将语音放入AudioPlayer的播放队列，按顺序播放。

## 五、开发运行
先登录到 41.2 的 Orin 板
1. 编译：
```bash
cd tkvoice_release_0.3.19_0320_175549
rm -rf build install log && colcon build --packages-select audio_message audio_service
```

2. 环境变量：
```bash
source install/setup.bash
```

3. 通过launch文件启动应用：
```bash
ros2 launch audio_service asr_llm_tts_process_launch.py
```

4. 对话

    天工所搭载的3588s上的麦克风阵列，收音是有方向性的，大约是麦克风阵列前方一个60度角的圆锥空间区域内，对话的时候需要让音源在这个空间内（也就是说话的人要在这个空间范围内），要不然麦克风阵列收不到音。
    
    天工在说话的过程中，可以被“天工天工”的声音打断，其他声音不会打断天工正在说的话。


# 安装

release_dir=tkvoice_release_0.3.19_0320_175549

1. 先从本地电脑上将 tkvoice_release_0.3.19_0320_175549.tar 传到 41.2 的 Orin 板：
```bash
scp tkvoice_release_0.3.19_0320_175549.tar nvidia@192.168.41.2:/home/nvidia
```

根目录的 `install.sh` 脚本已整合了 `/res/docker/install_asr.sh` 和 `/res/ollama/install_ollama.sh` 以及 .whl 包的安装，直接执行，顺利的话就可直接完成docker，funasr，ollama，piper的安装。

2. 登录到 41.2 的 Orin 板后，先只解压 tkvoice_release_0.3.19_0320_175549.tar 内的安装脚本 install.sh，其他的解压工作由安装脚本按需完成：
```bash
tar -xvf tkvoice_release_0.3.19_0320_175549.tar tkvoice_release_0.3.19_0320_175549/install.sh

```

3. 进入目录，执行安装脚本：
```bash
cd tkvoice_release_0.3.19_0320_175549
chmod +x install.sh
# 注意，执行 install.sh 的时候会多次要求输入密码，注意看清楚是需要输入 x86 上 ubuntu 用户的密码还是 Orin 板上 nvidia 用户的密码
# 该安装脚本会做以下操作：
# 1、将 docker_funasr 需要的文件传到 x86上，并在 x86 板上安装 docker, 导入镜像，启动容器运行 Funasr 服务
# 2、在 orin 板上安装 ollama 服务，导入 qwen2.5_1.5b.tar.gz 大语言模型
# 3、安装必要的 Python 包，包括 piper-tts, onnxruntime-gpu, httpx, websockets
./install.sh
```

4. 卸载
```bash
cd ~/tkvoice_release_0.3.19_0320_175549
chmod +x uninstall.sh
./uninstall.sh
# 注意，执行 uninstall.sh 的时候会多次要求输入密码，注意看清楚是需要输入 x86 上 ubuntu 用户的密码还是 Orin 板上 nvidia 用户的密码，卸载脚本会卸载 Orin 板上的 ollama 和 x86 上的 Funasr 容器和镜像以及 docker 服务
# 再注意，执行uninstall.sh 后 ~/tkvoice_release_0.3.19_0320_175549 目录会删除掉，也就是卸载脚本自身也会删除掉，但是 ~/tkvoice_release_0.3.19_0320_175549.tar 文件不会删除
```


# 测试运行
先登录到 41.2 的 Orin 板，进入目录：
```bash
cd tkvoice_release_0.3.19_0320_175549

然后可用如下命令进行管理:
# 启动服务
./tkvoice.sh start

# 停止服务
./tkvoice.sh stop

# 重启服务
./tkvoice.sh restart

# 查看状态
./tkvoice.sh status

# 查看日志"
tail -f /home/nvidia/tkvoice_release_0.3.19_0320_175549/tkvoice.log

```
