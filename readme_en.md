# Preface

For more details, reference [documentation](https://docs.ubtrobot.com/walker-tienkung/en/docs/tkvoice/offline/1/)

This project integrates offline ASR capability (using Funasr), offline large language models (using Ollama), and offline TTS capability (using piper-tts).

Unless otherwise specified, the entire project is open-sourced under the Apache-2.0 license. Special parts that directly depend on piper-tts are restricted by piper-tts's GPL-3.0 license, so they are also open-sourced under the GPL-3.0 license.

# Development Notes

Note: The following sections 1 to 3 provide a brief introduction on how to separately install various dependencies of this project to enhance understanding. If you only want to know how to quickly install the project, you can directly go to the **Installation** section below. For detailed information about the dependency installation process, please refer to `2.Dependencies_Installation_Guide_EN.md` in the project root directory.

## I. Offline ASR Capability

Using Funasr, the service runs on the 192.168.41.1 x86 machine as a Docker service with image `asr:latest`.

The prerequisite for using the ASR capability of this project is to install Docker service on x86 and pull the `asr:latest` image, then start a Funasr container.

### 1.1 Docker Installation

**Method 1:** You can refer to the `/res/docker_funasr/install_asr.sh` script in the project root directory, which has notes on how to download the Docker offline installation package and how to install it. The current installation script will start the Funasr container and provide service on port 10097.

**Method 2:** Follow these steps:
```bash
curl -O https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/shell/install_docker.sh
sudo bash install_docker.sh
```

Choose one of the following two ways to start the image:

### 1.2.1 Start Container with Existing Image (Option 1)

Use the `/res/docker_funasr/install_asr.sh` script to directly import the Funasr image prepared by the project and start the container.

### 1.2.2 Pull Image and Start (Option 2)

Refer to the official Funasr documentation: https://github.com/modelscope/FunASR/blob/main/runtime/docs/SDK_advanced_guide_offline_zh.md

After installation is complete, pull and start the FunASR Docker image with the following command:

```bash
sudo docker pull \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-cpu-0.4.7
mkdir -p ./funasr-runtime-resources/models
sudo docker run --restart=always -p 10097:10095 -it --privileged=true \
  -v $PWD/funasr-runtime-resources/models:/workspace/models \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-cpu-0.4.7
```

### 1.3 Server Startup (Only required after pulling Funasr image according to official documentation)

After Docker starts, enter the container and start the funasr-wss-server service:

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

Please note that Docker installation is done on the x86 machine at 41.1.

## II. Offline Large Language Models

Using Ollama, the service runs on the 192.168.41.2 Orin board. The Orin board has 275 TOPS of GPU computing power, making it more suitable for running large language models. The prerequisite for using natural language understanding capability of this project is to install the Ollama service on the Orin board at 41.2 and pull the `qwen2.5:1.5b` model, which is the model used by default in the project.

The installation steps for Ollama can be found in the `/res/ollama/install_ollama.sh` script in the project root directory, which also has comments on how to download the Ollama installation package and detailed installation steps. Please note that Ollama installation is done on the Orin board at 41.2.

## III. Offline TTS Capability

Using piper-tts. Its PyPI homepage is: https://pypi.org/project/piper-tts/

Python API usage is documented on GitHub: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md

It is open-sourced under the GPL-3.0 license, and this project also uses the GPL-3.0 license.

## IV. Code Description

The overall application execution flow is:

1. The `tk_audio_publisher` node on the Orin board gets the audio stream from RK3588s and publishes the complete sentence audio stream to the `audio_sentence_frames` topic;

2. The `tk_asr_text_publisher` node on the Orin board subscribes to the `audio_sentence_frames` topic. After receiving the raw audio stream, it sends it to the Funasr service on the x86 board via WebSocket and obtains the corresponding text after speech recognition, publishing it to the `asr_sentence` topic;

3. The `tk_audio_process` node on the Orin board subscribes to the `asr_sentence` topic. After receiving the question text, it sends the question to the Ollama service and streams the answer. Each time an answer text is received, it calls the offline TTS library to convert it to corresponding speech, then puts the speech into the AudioPlayer's playback queue for sequential playback.

## V. Development and Running

First, log in to the Orin board at 41.2:

1. **Build:**
```bash
cd tkvoice_release_0.3.25_0324_101621
rm -rf build install log && colcon build --packages-select audio_message audio_service
```

2. **Environment Setup:**
```bash
source install/setup.bash
```

3. **Start Application via Launch File:**
```bash
ros2 launch audio_service asr_llm_tts_process_launch.py
```

4. **Conversation:**

   The microphone array on TianGong's RK3588s has directional audio reception. It covers approximately a 60-degree cone-shaped space in front of the microphone array. When having a conversation, ensure the audio source is within this space (i.e., the speaker must be within this coverage range), otherwise the microphone array cannot pick up the sound.
   
   During TianGong's speech, it can be interrupted by "TianGong TianGong" (wake-up words), but other sounds will not interrupt TianGong's ongoing speech.

# Installation

release_dir=tkvoice_release_0.3.25_0324_101621

1. Transfer `tkvoice_release_0.3.25_0324_101621.tar` from your local computer to the Orin board at 41.2:

```bash
scp tkvoice_release_0.3.25_0324_101621.tar nvidia@192.168.41.2:/home/nvidia
```

The `install.sh` script in the root directory has integrated `/res/docker_funasr/install_asr.sh`, `/res/ollama/install_ollama.sh`, and .whl package installation. Execute it directly, and if everything goes smoothly, Docker, Funasr, Ollama, and Piper installation will be completed directly.

2. After logging in to the Orin board at 41.2, first extract only the `install.sh` script from `tkvoice_release_0.3.25_0324_101621.tar`. Other extraction will be done by the installation script as needed:

```bash
tar -xvf tkvoice_release_0.3.25_0324_101621.tar tkvoice_release_0.3.25_0324_101621/install.sh
```

3. Enter the directory and run the installation script:

```bash
cd tkvoice_release_0.3.25_0324_101621
chmod +x install.sh
# Note: When executing install.sh, you will be prompted to enter passwords multiple times. 
# Please pay attention to whether you need to enter the password for the ubuntu user on x86 
# or the nvidia user on the Orin board.
# This installation script will perform the following operations:
# 1. Transfer files needed by docker_funasr to x86, install Docker on x86 board, 
#    import image, and start container running Funasr service
# 2. Install Ollama service on Orin board, import qwen2.5_1.5b.tar.gz large language model
# 3. Install necessary Python packages, including piper-tts, onnxruntime-gpu, httpx, websockets
./install.sh
```

4. **Uninstall:**

```bash
cd ~/tkvoice_release_0.3.25_0324_101621
chmod +x uninstall.sh
./uninstall.sh
# Note: When executing uninstall.sh, you will be prompted to enter passwords multiple times. 
# Please pay attention to whether you need to enter the password for the ubuntu user on x86 
# or the nvidia user on the Orin board. The uninstall script will uninstall Ollama on the Orin 
# board and Funasr container and image on x86 as well as Docker service.
# Also note that after executing uninstall.sh, the ~/tkvoice_release_0.3.25_0324_101621 directory 
# will be deleted, including the uninstall script itself. However, the 
# ~/tkvoice_release_0.3.25_0324_101621.tar file will not be deleted.
```

# Testing and Running

First, log in to the Orin board at 41.2 and enter the directory:

```bash
cd tkvoice_release_0.3.25_0324_101621
```

Then you can use the following commands for management:

```bash
# Start service
./tkvoice.sh start

# Stop service
./tkvoice.sh stop

# Restart service
./tkvoice.sh restart

# Check status
./tkvoice.sh status

# View logs
tail -f /home/nvidia/tkvoice_release_0.3.25_0324_101621/tkvoice.log
```
