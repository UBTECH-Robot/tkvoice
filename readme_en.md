# Preface
The entire project includes the following capabilities:

ASR (Automatic Speech Recognition) — powered by Microsoft Azure Speech Service.

Large Language Model (LLM) — supports only LLM services that can be accessed through the OpenAI SDK.

TTS (Text-to-Speech) — powered by Microsoft Azure Speech Service.

## 1. Code Description

The overall workflow of the application is as follows:
1. On the Orin board, the tk_audio_publisher node receives an audio stream from the RK3588s device and publishes complete sentence-level audio streams to the audio_sentence_frames topic.

2. On the Orin board, the tk_asr_text_publisher node subscribes to the audio_sentence_frames topic. After receiving the raw audio stream, it sends the data to Azure Speech Service using the SpeechRecognizer classes and methods from the azure.cognitiveservices.speech SDK. The recognized text is then published to the asr_sentence topic.

3. The tk_audio_process node on the Orin board subscribes to the asr_sentence topic. After receiving the recognized question text, it sends the query to the configured LLM service using the OpenAI SDK, retrieving the response in a streaming manner. The specific LLM service is configured in the .env file located in the project’s root directory.
    
    Note: The current implementation only uses the OpenAI SDK for requests, so only LLM services compatible with the OpenAI SDK are supported at this stage.

4. During the streaming output of the LLM’s response, whenever enough characters are received to form a complete sentence, the SpeechSynthesizer classes and methods from the azure.cognitiveservices.speech SDK are invoked to convert that sentence into speech. The generated audio is then added to the AudioPlayer playback queue and played sequentially.

5. The .env file located in the project’s root directory contains critical configuration parameters. Properly setting up this file is essential for enabling the ASR, LLM, and TTS functionalities throughout the entire project. You may create this file if the file does not exist.

```bash
LLM_KEY=sk-xxx
LLM_ENDPOINT=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-flash
# All LLM service providers that are compatible with the OpenAI SDK will provide the three parameters mentioned above.
# The LLM_KEY may also be referred to as an API Key (for example, on Alibaba Cloud’s Bailian platform). The exact naming may vary depending on the service provider.
# The LLM_ENDPOINT may also be referred to as the Base URL (for example, on Alibaba Cloud’s Bailian platform). It specifies the endpoint or node of the LLM service to be used. For instance, on the Alibaba Cloud Bailian platform, two nodes are available:
#   1. Beijing node (for users in China): https://github.com/UBTEDU-OPEN/tkvoice
#   2. ingapore node (for users outside China): https://dashscope-intl.aliyuncs.com/compatible-mode/v1
# Other providers such as Microsoft, Amazon, or OpenAI typically offer globally distributed nodes for selection.

# The LLM_MODEL specifies the name of the model to be used. For example, on the Alibaba Cloud Bailian platform, available options include qwen3-max, qwen-plus, qwen-flash, and others. For details, refer to: https://help.aliyun.com/zh/model-studio/models. Similarly, providers such as Microsoft, Amazon, and OpenAI also offer various model options to choose from.
# For Microsoft LLM, refer to: https://learn.microsoft.com/en-us/azure/ai-foundry/openai/supported-languages?tabs=dotnet-secure%2Csecure%2Cpython-entra&pivots=programming-language-python

SPEECH_KEY="xxx"
ENDPOINT=https://westeurope.api.cognitive.microsoft.com/
# The ASR and TTS services currently integrate with Azure and require two parameters:
# SPEECH_KEY is the key required to access (authenticate) the Azure speech services.
# ENDPOINT refers to the service endpoint (region node). Generally, it’s best to use the geographically closest endpoint to reduce latency.

LANGUAGE=zh-CN
# This parameter specifies the language for Microsoft ASR recognition. Available options can be found here: https://learn.microsoft.com/zh-cn/azure/ai-services/speech-service/language-support?tabs=stt

VOICE_NAME=sl-SI-RokNeural
# This parameter specifies the language for speech synthesis. You can refer to the supported options here: https://learn.microsoft.com/zh-cn/azure/ai-services/speech-service/language-support?tabs=tts

SYS_MESSAGE="你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量100个单词以内，用斯洛文尼亚语回答。"
# This parameter is used within the project to set the system prompt (system message) for the LLM.

INTERRUPT_WORDS="天工,天空,天宫"
# "Interrupt words" mean that while the system is playing audio, it is still listening. If the ASR detects any of the configured interrupt words in the recognized text, the playback will stop immediately and the system will switch back to listening mode, waiting for the user’s question. If none of the interrupt words are detected, the current utterance will be ignored. Multiple interrupt words can be configured, separated by commas.
```

## 2. Develope
First, log in to the Orin board with IP 192.168.41.2.

1. Clone:
```bash
cd ~ && git clone https://github.com/UBTEDU-OPEN/tkvoice.git
```

2. Install python package, compile:
```bash
cd tkvoice
pip install azure-cognitiveservices-speech==1.47.0 openai==2.7.1
rm -rf build install log && colcon build --packages-select audio_message audio_service
```

3. Source:
```bash
source install/setup.bash
```

4. Start the application using the launch file：
```bash
ros2 launch audio_service asr_llm_tts_process_launch.py
```

5. Chat:

    The microphone array mounted on the 3588s by Tienkung is directional, capturing sound primarily within a roughly 60-degree conical area in front of the array. During conversations, the sound source (i.e., the speaker) needs to be within this spatial range; otherwise, the microphone array will not pick up the audio.
    

# Run
First, log in to the Orin board with IP 192.168.41.2.
```bash
cd ~/tkvoice

# start
./tkvoice.sh start

# stop
./tkvoice.sh stop

# restart
./tkvoice.sh restart

# status
./tkvoice.sh status

# log"
tail -f /home/nvidia/tkvoice/tkvoice.log

```
