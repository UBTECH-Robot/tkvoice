"""
LLM客户端模块

该模块提供了一个基于OpenAI SDK的LLM（大语言模型）客户端封装类，
支持流式输出和智能断句功能。主要特点：
1. 使用子进程执行HTTP请求，避免阻塞主进程
2. 支持流式输出，实时返回生成的句子
3. 智能断句：根据标点符号和长度限制切分句子
4. 支持对话历史记录管理

使用方式：
    client = LLMClient()
    for sentence in client.stream_sentence("你好"):
        print(sentence)
    client.close()
"""
import os
from collections import deque
from openai import OpenAI
# pip install openai==2.7.1
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class LLMClient:
    """
    大语言模型客户端类

    封装了与LLM API的交互逻辑，支持流式输出和智能断句。

    Attributes:
        max_history (int): 最大保存的对话轮数
        history (deque): 对话历史记录队列
        system_message (dict): 系统提示消息
        api_key (str): LLM API密钥
        llm_endpoint (str): LLM API端点URL
        llm_model (str): 使用的模型名称
        sys_message (str): 默认系统提示词
        sentence_endings (str): 句子结束标点符号
        soft_endings (str): 软分割标点符号
        max_len (int): 最大缓冲长度，超过时触发软分割
    """

    def __init__(self, max_history=1):
        """
        初始化LLM客户端

        Args:
            max_history (int): 保存的最大对话轮数，默认为1轮。
                              实际保存的消息数量为 max_history * 2（用户消息+助手消息）

        Raises:
            ValueError: 当环境变量LLM_KEY、LLM_ENDPOINT、LLM_MODEL未设置时抛出
        """
        self.max_history = max_history
        self.history = deque(maxlen=max_history * 2)  # 双端队列，自动丢弃最旧的消息
        self.system_message = None

        # 从环境变量加载配置
        self.api_key = os.environ.get("LLM_KEY")
        self.llm_endpoint = os.environ.get("LLM_ENDPOINT")
        self.llm_model = os.environ.get("LLM_MODEL")
        self.sys_message = os.environ.get("SYS_MESSAGE", '你是优必选开发的智能助手，名叫天工形者。回答简洁明了，尽量100个字以内，用中文回答。')
        if not self.api_key or not self.llm_endpoint or not self.llm_model:
            raise ValueError("LLM_ENDPOINT, LLM_MODEL, and LLM_KEY must be set in the .env file in the project root directory, and the corresponding LLM service needs to support invocation using the OpenAI SDK.")

        # 句子切分配置
        # sentence_endings: 遇到这些标点时立即断句返回
        self.sentence_endings = "。！？.!?"
        # soft_endings: 当缓冲区超过max_len时，在这些标点处断句
        self.soft_endings = "，、;；,"
        # max_len: 最大缓冲长度，超过此长度且存在soft_endings时触发断句
        self.max_len = 70

        self._current_stream = None   # 当前流式响应，用于中断
        self._client = self._build_client()

        self.set_system_message(self.sys_message)

    def set_system_message(self, content):
        """
        设置系统提示消息

        系统消息用于设定AI助手的角色和行为规范。

        Args:
            content (str): 系统提示消息的内容
        """
        self.system_message = {"role": "system", "content": content}

    def add_message(self, role, content):
        """
        添加一条消息到对话历史

        Args:
            role (str): 消息角色，可选值为 "user"（用户）或 "assistant"（助手）
            content (str): 消息内容
        """
        self.history.append({"role": role, "content": content})

    def get_messages_payload(self, user_input):
        """
        构建发送给LLM API的消息载荷

        消息格式为OpenAI API标准的消息列表格式，包含：
        1. 系统消息（如果已设置）
        2. 历史对话消息
        3. 当前用户输入

        Args:
            user_input (str): 当前用户的输入文本

        Returns:
            list[dict]: 符合OpenAI API格式的消息列表
        """
        messages = []
        if self.system_message:
            messages.append(self.system_message)
        messages.extend(list(self.history))
        messages.append({"role": "user", "content": user_input})
        return messages

    def _build_client(self) -> 'OpenAI | None':
        """创建 OpenAI 客户端（指向本地 Ollama）。"""
        if not self.llm_endpoint:
            return None
        return OpenAI(api_key=self.api_key, base_url=self.llm_endpoint)
    
    def stream_sentence(self, user_input):
        """直接在 NLP 线程内流式请求 LLM，通过关闭 stream 实现中断。"""
        # 关闭上一次未完成的流式请求
        self.set_interrupted(True)

        if not self.llm_endpoint or self._client is None:
            logging.error("[NLP] 无可用的 LLM 服务，无法处理请求")
            yield "抱歉，当前无法连接到语言模型服务。"
            return
        
        messages_payload = self.get_messages_payload(user_input)

        assistant_response = ""  # 完整的助手回复，用于记录历史
        buffer = ""  # 句子缓冲区，用于断句
        stream = None
        try:
            stream = self._client.chat.completions.create(
                model=self.llm_model,
                messages=messages_payload,
                stream=True,
                stream_options={"include_usage": True}
            )
            self._current_stream = stream
            logging.info(f'[NLP] Start streaming, user=[{user_input}]')

            for chunk in stream:
                if chunk.choices:
                    content = chunk.choices[0].delta.content or ""
                    assistant_response += content
                    buffer += content

                    # 句号断句
                    while any(punc in buffer for punc in self.sentence_endings):
                        idx = min(
                            [buffer.find(punc) for punc in self.sentence_endings if punc in buffer]
                        )
                        sentence = buffer[: idx + 1].strip()
                        logging.info(f"[NLP] Stream output sentence: {sentence}")
                        yield sentence
                        buffer = buffer[idx + 1:]

                    # 软分割（超过 max_len）
                    if len(buffer) >= self.max_len:
                        for punc in self.soft_endings:
                            if punc in buffer:
                                idx = buffer.find(punc)
                                sentence = buffer[: idx + 1].strip()
                                logging.info(f"[NLP] Stream output sentence (soft split): {sentence}")
                                yield sentence
                                buffer = buffer[idx + 1:]
                                break

                elif chunk.usage:
                    logging.debug(f"[NLP] Total Tokens: {chunk.usage.total_tokens}")

        except Exception as e:
            logging.info(f'[NLP] Streaming request interrupted: {e}')
            return
        finally:
            self._current_stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

        # 处理缓冲区中残留的文本
        if buffer.strip():
            remaining = buffer.strip()
            logging.info(f"[NLP] Stream output remaining: {remaining}")
            yield remaining

        # 记录对话历史（用于多轮对话上下文）
        self.add_message("user", user_input)
        self.add_message("assistant", assistant_response)

        logging.info(f'[NLP] Question [{user_input}] completed.')

    def set_interrupted(self, interrupted=True):
        """关闭当前流式响应，使 NLP 线程的迭代立即退出。"""
        if interrupted:
            stream = self._current_stream
            self._current_stream = None
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    def close(self):
        self.set_interrupted(True)
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

def main():
    """
    模块入口函数 - 用于测试LLM客户端

    演示如何使用LLMClient进行对话：
    1. 创建客户端实例
    2. 进行第一轮对话
    3. 进行第二轮对话（测试历史记录功能）
    4. 关闭客户端释放资源

    注意：运行前需要设置环境变量：
    - LLM_KEY: API密钥
    - LLM_ENDPOINT: API端点URL
    - LLM_MODEL: 模型名称
    """
    client = LLMClient()

    # 第一轮对话
    for s in client.stream_sentence("天空为什么是蓝色的？"):
        print(">>>", s)

    # 第二轮对话，测试历史记录是否生效
    print("---- 再问第二个 ----")
    for s in client.stream_sentence("这与米氏散射有何不同？"):
        print(">>>", s)

    # 释放资源
    client.close()


if __name__ == "__main__":
    main()
