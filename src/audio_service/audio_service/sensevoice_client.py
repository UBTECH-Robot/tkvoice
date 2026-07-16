import os
import re
import time
from audio_service.log_config import setup_logger

logging = setup_logger(__name__)

_TAG_PATTERN = re.compile(r'<\|[^|]+\|>')


class SenseVoiceClient:
    def __init__(self, language="zh", use_itn=True, model_name="iic/SenseVoiceSmall"):
        self.language = language
        self.use_itn = use_itn
        self.model_name = model_name
        self.model = None
        self._load_model()

    def _load_model(self):
        from funasr import AutoModel

        start = time.time()
        logging.info(f"[ASR] 加载 SenseVoice 模型: {self.model_name}")
        self.model = AutoModel(
            model=self.model_name,
            vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            punc_model="iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch",
            disable_update=True,
            disable_pbar=True,
        )
        elapsed = time.time() - start
        logging.info(f"[ASR] SenseVoice 模型加载完成, 耗时 {elapsed:.1f}s")

    def to_text(self, audio_bytes: bytes) -> str:
        if self.model is None:
            logging.error("[ASR] 模型未加载")
            return ""

        try:
            start = time.time()
            result = self.model.generate(
                input=audio_bytes,
                cache={},
                language=self.language,
                use_itn=self.use_itn,
                batch_size_s=0,
            )
            elapsed = time.time() - start
            logging.debug(f"[ASR] 识别耗时 {elapsed:.2f}s")

            if result and len(result) > 0:
                text = result[0].get("text", "").strip()
                if text:
                    text = _TAG_PATTERN.sub('', text).strip()
                    if text:
                        return text
            return ""
        except Exception as e:
            logging.error(f"[ASR] 识别失败: {e}")
            return ""

    def close(self):
        self.model = None
        logging.info("[ASR] SenseVoice 资源已释放")
