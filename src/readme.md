如何从3588s接收音频流

audio_message 包定义了音频消息AudioFrame.msg，如下：
std_msgs/Header header
uint8 vad
<!-- 1：开始说话，2：持续说话，3：结束说话 -->

uint32 frame_id
<!-- 暂时没用 -->

uint32 sample_rate
<!-- 采样率 -->

uint8 channels
<!-- 声道 -->

uint8 bit_depth
<!-- 位宽 -->

uint8[] data
<!-- 二进制原生音频数据 -->


audio_service 包定义了原生音频数据发布服务和一个接收并保存的示例

先在项目根目录(src目录是其惟一子目录)构建工程：
colcon build --packages-select audio_message audio_service

在一个终端启动音频发布节点：
. install/setup.bash
ros2 run audio_service audio_publisher
会发布如下两个话题：

/audio_frames
每次从aiui收到原生音频数据马上发布到这个话题

/audio_sentence_frames
从aiui收到vad为1和2的音频数据时会暂时缓存起来，等收到vad为3，也就是结束说话的数据时，再将这一段时间以来收到的1，2，3类型的音频数据组合成一个完整句子的音频再发送到这个话题


在另一个终端启动示例音频接收保存节点：
. install/setup.bash
ros2 run audio_service audio_publisher --ros-args -p save_audio:=true 