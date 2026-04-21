import asyncio
import logging
import uuid
from pathlib import Path

import edge_tts

from config import TEMP_DIR, TTS_FALLBACK_OFFLINE, TTS_RATE, TTS_VOICE

logger = logging.getLogger(__name__)

_offline_engine = None


def _get_offline_engine():
    """懒加载 pyttsx3 离线引擎。"""
    global _offline_engine
    if _offline_engine is None:
        import pyttsx3
        _offline_engine = pyttsx3.init()
        _offline_engine.setProperty("rate", 200)
        # 尝试设置中文语音
        voices = _offline_engine.getProperty("voices")
        for voice in voices:
            if "chinese" in voice.name.lower() or "zh" in voice.id.lower():
                _offline_engine.setProperty("voice", voice.id)
                break
    return _offline_engine


async def synthesize(text: str, output_path: Path | None = None) -> Path:
    """将文本合成为语音文件，返回 MP3 文件路径。

    优先使用 edge-tts（在线），失败时回退到 pyttsx3（离线）。
    """
    if output_path is None:
        output_path = TEMP_DIR / f"tts_{uuid.uuid4().hex[:8]}.mp3"

    try:
        return await _synthesize_edge_tts(text, output_path)
    except Exception as e:
        logger.warning("edge-tts 合成失败: %s", e)
        if TTS_FALLBACK_OFFLINE:
            logger.info("回退到 pyttsx3 离线合成")
            return await _synthesize_offline(text, output_path)
        raise


async def _synthesize_edge_tts(text: str, output_path: Path) -> Path:
    """使用 edge-tts 在线合成。"""
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
    await communicate.save(str(output_path))
    logger.info("edge-tts 合成完成: %s", output_path)
    return output_path


async def _synthesize_offline(text: str, output_path: Path) -> Path:
    """使用 pyttsx3 离线合成。"""
    wav_path = output_path.with_suffix(".wav")
    engine = _get_offline_engine()
    engine.save_to_file(text, str(wav_path))
    engine.runAndWait()
    logger.info("pyttsx3 合成完成: %s", wav_path)
    return wav_path


async def synthesize_stream(text: str):
    """流式合成，逐块 yield 音频数据。用于边合成边播放。"""
    try:
        communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    except Exception as e:
        logger.warning("edge-tts 流式合成失败: %s，回退到一次性合成", e)
        if TTS_FALLBACK_OFFLINE:
            path = await _synthesize_offline(text, TEMP_DIR / f"tts_{uuid.uuid4().hex[:8]}.wav")
            with open(path, "rb") as f:
                yield f.read()
        else:
            raise
