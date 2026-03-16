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
import subprocess
import httpx
import os
import json
import multiprocessing
import queue
import time
from datetime import datetime
from collections import deque
from openai import OpenAI
# pip install openai==2.7.1
from audio_service.log_config import setup_logger
logging = setup_logger(__name__)

class LLMClient:
    """
    大语言模型客户端类

    封装了与LLM API的交互逻辑，支持流式输出和智能断句。
    通过子进程执行HTTP请求，使用multiprocessing.Queue实现进程间通信。

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
        process (Process): 当前运行的子进程
        queue (Queue): 进程间通信队列
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

        # 控制字段
        self.mp_context = multiprocessing.get_context("spawn")  # 使用spawn方式创建子进程，兼容Windows
        self.process = None  # 当前运行的子进程
        self.queue = None    # 进程间通信队列

        self.set_system_message(self.sys_message)
        self.load_model()

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

    def load_model(self, model_name=None):
        """
        加载模型（预留接口）

        当前实现为空，因为本客户端使用远程API而非本地模型。
        预留此方法以便未来扩展支持本地模型。

        Args:
            model_name (str, optional): 模型名称，当前未使用

        Returns:
            None
        """
        return

    @staticmethod
    def _stream_worker(base_url, model, messages_payload, queue, api_key):
        """
        子进程工作函数：执行流式HTTP请求

        在独立的子进程中执行OpenAI API调用，将流式返回的文本内容
        通过队列发送给主进程。这种设计避免了HTTP请求阻塞主进程。

        子进程的生命周期：
        1. 创建OpenAI客户端并发起流式请求
        2. 循环读取流式响应，将每个chunk的内容放入队列
        3. 请求完成后放入None作为结束信号
        4. 子进程自动退出

        Args:
            base_url (str): LLM API的基础URL
            model (str): 使用的模型名称
            messages_payload (list[dict]): 消息载荷列表
            queue (multiprocessing.Queue): 用于向主进程发送数据的队列
            api_key (str): API认证密钥

        Note:
            队列中放入None表示流式输出结束，主进程据此判断子进程已完成
        """
        try:
            logging.info(f'[Subprocess] 开始请求 {base_url}')
            with OpenAI(api_key=api_key, base_url=base_url) as client:
                completion = client.chat.completions.create(
                    model=model,
                    messages=messages_payload,
                    stream=True,
                    stream_options={"include_usage": True}  # 在流式响应末尾包含token使用统计
                )
                logging.info(f'[Subprocess] 请求已发起，等待输出')
                for chunk in completion:
                    if chunk.choices:
                        # 获取内容增量并放入队列
                        content = chunk.choices[0].delta.content or ""
                        queue.put(content)
                    elif chunk.usage:
                        # 最后一个chunk包含token使用统计
                        logging.debug(f"[Subprocess] 总计 Tokens: {chunk.usage.total_tokens}")

        except Exception as e:
            logging.info(f'[Subprocess] 出错: {e}', exc_info=True)
        finally:
            queue.put(None)  # 发送结束信号
            logging.debug("[Subprocess] 数据发送完成，等待主进程处理。")

    def stream_sentence(self, user_input):
        """
        流式生成句子并返回（生成器函数）

        这是主要的外部调用接口。该函数会：
        1. 启动子进程执行LLM API请求
        2. 从队列中读取流式输出的文本块
        3. 根据标点符号和长度限制智能断句
        4. 通过生成器逐句返回结果

        断句策略：
        - 硬断句：遇到句号、问号、感叹号时立即断句返回
        - 软断句：当缓冲区超过max_len字符且遇到逗号等软分割标点时断句
        - 剩余处理：流结束后将缓冲区中剩余的文本作为最后一句返回

        Args:
            user_input (str): 用户的输入文本

        Yields:
            str: 生成的句子片段，每次yield一个完整的句子

        Example:
            >>> for sentence in client.stream_sentence("你好"):
            ...     print(sentence)  # 逐句打印生成的回复

        Note:
            - 每次调用会终止之前未完成的子进程
            - 调用完成后会自动记录对话历史
        """
        # 若存在上一个子进程，则先终止
        self.set_interrupted(True)

        messages_payload = self.get_messages_payload(user_input)
        q = self.mp_context.Queue()
        p = self.mp_context.Process(
            target=self._stream_worker,
            args=(self.llm_endpoint, self.llm_model, messages_payload, q, self.api_key),
            daemon=True,  # 设置为守护进程，主进程退出时自动终止
        )
        self.process = p
        self.queue = q
        p.start()
        logging.info(f'[NLP] Started subprocess PID={p.pid}, streaming output for [{user_input}]')

        assistant_response = ""  # 完整的助手回复，用于记录历史
        buffer = ""  # 句子缓冲区，用于断句

        while True:
            try:
                # 从队列获取数据，设置超时以便检测子进程状态
                chunk = q.get(timeout=0.5)
                if chunk is None:
                    logging.debug("[NLP] Received None from queue, stream complete")
                    break  # 子进程结束
                assistant_response += chunk
                buffer += chunk

                # 硬断句：遇到句子结束标点时立即断句
                while any(punc in buffer for punc in self.sentence_endings):
                    # 找到最早出现的结束标点位置
                    idx = min(
                        [buffer.find(punc) for punc in self.sentence_endings if punc in buffer]
                    )
                    sentence = buffer[: idx + 1].strip()
                    logging.info(f"[NLP] Stream output sentence: {sentence}")
                    yield sentence
                    buffer = buffer[idx + 1:]

                # 软断句：缓冲区过长时，在软分割标点处断句
                if len(buffer) >= self.max_len:
                    for punc in self.soft_endings:
                        if punc in buffer:
                            idx = buffer.find(punc)
                            sentence = buffer[: idx + 1].strip()
                            logging.info(f"[NLP] Stream output sentence (soft split): {sentence}")
                            yield sentence
                            buffer = buffer[idx + 1:]
                            break

            except queue.Empty:
                # 队列为空时检查子进程是否存活
                if not p.is_alive():
                    logging.debug("[NLP] Subprocess ended, stream output complete")
                    break
                continue
            except KeyboardInterrupt:
                logging.info("[NLP] Caught KeyboardInterrupt, terminating subprocess")
                self.set_interrupted(True)
                break

        # 处理缓冲区中残留的文本
        if buffer.strip():
            remaining = buffer.strip()
            logging.info(f"[NLP] Stream output remaining: {remaining}")
            yield remaining

        # 记录对话历史（用于多轮对话上下文）
        self.add_message("user", user_input)
        self.add_message("assistant", assistant_response)

        # 确保子进程完全退出
        if p.is_alive():
            p.join(timeout=1)
        if p.exitcode is not None:
            logging.info(f'[NLP] Question [{user_input}] completed, exitcode={p.exitcode}.')

    def set_interrupted(self, interrupted=True):
        """
        终止当前正在运行的子进程

        当需要中断当前LLM请求（如用户打断、开始新对话）时调用此方法。
        会安全地终止子进程并清理队列资源。

        Args:
            interrupted (bool): True表示终止子进程，当前仅支持True

        Note:
            此方法会：
            1. 终止正在运行的子进程
            2. 等待子进程退出（最多1秒）
            3. 关闭并清理队列资源
            4. 重置process和queue属性为None
        """
        if interrupted:
            process = getattr(self, "process", None)
            stream_queue = getattr(self, "queue", None)
            if process is not None and process.is_alive():
                logging.debug(f"[MainProcess] Subprocess PID={process.pid} terminating...")
                process.terminate()
                process.join(timeout=1)
            if stream_queue is not None:
                try:
                    stream_queue.close()
                    stream_queue.join_thread()
                except Exception:
                    pass
            self.process = None
            self.queue = None

    def close(self):
        """
        关闭客户端，释放资源

        清理所有资源，包括终止子进程和关闭队列。
        在不再使用客户端时应调用此方法。

        Example:
            >>> client = LLMClient()
            >>> # ... 使用客户端 ...
            >>> client.close()  # 使用完毕后关闭
        """
        self.set_interrupted(True)

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
