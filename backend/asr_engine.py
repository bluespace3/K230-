import os
import logging
from pathlib import Path

# 使用国内镜像下载模型
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_model = None

# 本地模型路径（通过魔搭下载）
_LOCAL_MODEL_PATH = str(Path(__file__).parent / "models" / "Systran" / "faster-whisper-medium")


def _get_model() -> WhisperModel:
    """懒加载 faster-whisper 模型（首次调用时加载）。"""
    global _model
    if _model is None:
        logger.info("加载 faster-whisper 模型 (medium)...")
        _model = WhisperModel(_LOCAL_MODEL_PATH, device="cpu", compute_type="int8")
        logger.info("faster-whisper 模型加载完成")
    return _model


def transcribe(audio_path: Path, language: str = "zh") -> str:
    """将音频文件转为文字。

    Args:
        audio_path: 音频文件路径 (WAV/MP3/OGG 等)
        language: 语言代码，默认 "zh" (中文)

    Returns:
        识别出的文字内容
    """
    model = _get_model()
    segments, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
            threshold=0.3,
        ),
    )

    # 收集每个 segment 的详细信息
    segment_list = list(segments)
    logger.info(
        "ASR 详情: 时长=%.2fs, 语言=%s, VAD概率=%.2f, segments=%d",
        info.duration, info.language, info.language_probability, len(segment_list),
    )
    for i, seg in enumerate(segment_list):
        logger.info("  segment[%d]: [%.1f-%.1f] %s", i, seg.start, seg.end, seg.text.strip())

    text = "".join(seg.text for seg in segment_list).strip()
    logger.info("ASR 最终结果 (%s): '%s'", info.language, text)
    return text
