# Introduction
The entire project includes offline ASR capabilities (using Funasr), offline large language models (using Ollama), and offline TTS capabilities (using piper-tts).

Unless otherwise specified, all parts of this project are released under the Apache License 2.0.
The specific parts that directly depend on Piper-TTS are subject to the GPL-3.0 license due to Piper-TTS's licensing, and are therefore released under the GPL-3.0 license.

# Development Notes
## 1. Offline ASR Capability
The ASR capability uses Funasr, and the service runs on an x86 machine with the IP address 192.168.41.1. It is a Docker service, and the image used is asr:latest.

Therefore, the prerequisite for using the ASR functionality in this project is to have Docker installed on the x86 machine, pull the asr:latest image, and then start a Funasr container.

### 1.1 docker installation

#### Method 1
You can refer to the script /res/docker/install.sh in the project root directory. It provides instructions on how to download the offline Docker installation package and how to install it. The current installation script will start the Funasr container and provide the service on port 10097.

#### Method 2
Follow the steps below:
```bash
curl -O https://isv-data.oss-cn-hangzhou.aliyuncs.com/ics/MaaS/ASR/shell/install_docker.sh；
sudo bash install_docker.sh
```

#### Method 3
Or you can just follow the docker official installation guides: https://docs.docker.com/engine/install/ubuntu/


下面两种启动镜像的方式可选一种：

### 1.2.1 Start the Container Using the Existing Image (Option 1)
Load docker image：
```bash
# First, transfer the asr.latest.tar.gz file from the /res/docker/ directory to the current directory on the x86 machine, and then execute the following command:
docker load < asr.latest.tar.gz
```

Start container：
```bash
sudo docker run -d --privileged=true \
  -v /home/ubuntu/Documents/asr-runtime-resources/models:/workspace/models \
  -v /home/ubuntu/Documents/asr-runtime-resources/startup.sh:/workspace/startup.sh \
  -w /workspace -p 10097:10095 --restart=on-failure:3 \
  asr:latest \
  bash /workspace/startup.sh
```

### 1.2.2 Pull the Image and Start the Container (Option 2)
Reference：https://github.com/modelscope/FunASR/blob/main/runtime/docs/SDK_advanced_guide_offline_en.md


Please note that Docker installation is on the x86 machine with the IP address 192.68.41.1.

## 2. Offline Large Language Model
The llm service we used is Ollama, and the service runs on the Jetson AGX Orin with the IP address 192.168.41.2. The Jetson AGX Orin offering up to 275 TOPS of AI performance with power configurable between 15W and 60W, making it more suitable for running large language models. Therefore, the prerequisite for using the natural language understanding in this project is that Ollama service must be installed on the Jetson AGX Orin with IP address 41.2, and the qwen2.5:1.5b model must be pulled. This model is the default model used in the project. If you you want to use another model, you may need to change the code of this project accordingly.

The installation steps for Ollama can be found in the /res/ollama/install.sh script in the project root directory. The script also includes comments on how to download the Ollama installation package and detailed installation steps. Please note that Ollama installation is done on the Jetson AGX Orin with the IP address 41.2.


## 3. Offline TTS Capability

The TTS capability used is piper-tts, and its PyPI page can be found at: https://pypi.org/project/piper-tts/

The Python API documentation for its usage is available on GitHub: https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/API_PYTHON.md

It uses the GPL-3.0 open-source license, and this project will also adopt the GPL-3.0 license.

## 4. Code Explanation

The overall flow of the application is as follows:

1. The tk_audio_publisher node on the Jetson AGX Orin obtains the audio stream from the RK3588s and publishes the audio stream in full sentences to the audio_sentence_frames topic.

2. The tk_asr_text_publisher node on the Jetson AGX Orin subscribes to the audio_sentence_frames topic. After receiving the raw audio stream, it sends the data via WebSocket to the Funasr service on the x86 machine and retrieves the transcribed text. This text is then published to the asr_sentence topic.

3. The tk_audio_process node on the Jetson AGX Orin subscribes to the asr_sentence topic. Upon receiving the transcribed question text, it sends the question to the Ollama service and streams the response. For each response received, the offline TTS library is called to convert the text into speech. The generated speech is then placed into the AudioPlayer's playback queue and played in sequence.


## 5. Development and Execution
First, log in to the Jetson AGX Orin with the IP address 192.168.41.2.
1. Compile：
```bash
cd tkvoice_release_0.2.18_1125_104556
rm -rf build install log && colcon build --packages-select audio_message audio_service
```

2. source：
```bash
source install/setup.bash
```

3. Start the application by launching the launch file：
```bash
ros2 launch audio_service asr_llm_tts_process_launch.py
```

4. Chat

    The microphone array on the 3588s mounted on the Tienkung system has directional audio capture. It covers a cone-shaped area with a 60-degree angle in front of the microphone array. During conversations, the sound source must be within this space (i.e., the person speaking should be within this area), otherwise, the microphone array will not pick up the sound.

    While Tienkung is speaking, it can be interrupted by the sound of "Tienkung Tienkung," but other sounds will not interrupt its speech.

# Installation

release_dir=tkvoice_release_0.2.18_1125_104556

1. First, transfer the tkvoice_release_0.2.18_1125_104556.tar from your local computer to the Orin with the IP address 192.168.41.2:
```bash
scp tkvoice_release_0.2.18_1125_104556.tar nvidia@192.168.41.2:/home/nvidia
```

2. After logging into the Orin with IP address 41.2, first extract only the installation script install.sh from the tkvoice_release_0.2.18_1125_104556.tar file. The rest of the extraction process will be handled by the installation script as needed:
```bash
tar -xvf tkvoice_release_0.2.18_1125_104556.tar tkvoice_release_0.2.18_1125_104556/install.sh

```

3. Navigate to the directory and execute the installation script:
```bash
cd tkvoice_release_0.2.18_1125_104556
chmod +x install.sh
# Note that when executing install.sh, you will be prompted multiple times to enter a password. Be sure to pay attention to whether the password required is for the Ubuntu user on the x86 machine or for the Nvidia user on the Orin.
# The installation script will perform the following actions:
# 1. Transfer the required files for docker_funasr to the x86 machine, install Docker on the x86 machine, import the image, and start the container to run the Funasr service.
# 2. Install the Ollama service on the Jetson AGX Orin and import the qwen2.5_1.5b.tar.gz large language model.
# 3. Install the necessary Python packages, including piper-tts, onnxruntime-gpu, httpx, and websockets.
./install.sh
```

4. Uninstallation
```bash
cd ~/tkvoice_release_0.2.18_1125_104556
chmod +x uninstall.sh
./uninstall.sh
# Note that when executing uninstall.sh, you will be prompted multiple times to enter a password. Be sure to pay attention to whether the password required is for the Ubuntu user on the x86 machine or for the Nvidia user on the Jetson AGX Orin. The uninstall script will remove the Ollama service on the Jetson AGX Orin, as well as the Funasr container and image, and Docker service on the x86 machine.
# Additionally, note that after executing uninstall.sh, the ~/tkvoice_release_0.2.18_1125_104556 directory will be deleted, meaning the uninstall script itself will also be removed. However, the ~/tkvoice_release_0.2.18_1125_104556.tar file will not be deleted.
```


# Startup
First, log in to the Jetson AGX Orin with IP address 41.2, and navigate to the directory:
```bash
cd tkvoice_release_0.2.18_1125_104556

# You can then use the following commands for management:
# start the service
./tkvoice.sh start

# stop the service
./tkvoice.sh stop

# restart the service
./tkvoice.sh restart

# check the status
./tkvoice.sh status

# check the logs"
tail -f /home/nvidia/tkvoice_release_0.2.18_1125_104556/tkvoice.log

```

The project currently supports chatting in Chinese.
English conversation support has not been fully tested yet.

### ✅ Done
- Chinese conversation support

### 🚧 To Do
- Full validation of English conversation
