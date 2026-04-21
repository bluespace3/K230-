import asyncio
import logging
from collections import deque
from pathlib import Path

import pygame

logger = logging.getLogger(__name__)

_initialized = False
_queue: deque[Path] = deque()
_playing = False


def _ensure_init():
    global _initialized
    if not _initialized:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        _initialized = True


async def play(audio_path: Path):
    """播放音频文件，如果有正在播放的音频则排队等待。"""
    _queue.append(audio_path)
    await _drain_queue()


async def _drain_queue():
    global _playing
    if _playing:
        return

    _playing = True
    _ensure_init()

    while _queue:
        path = _queue.popleft()
        try:
            await _play_file(path)
        except Exception as e:
            logger.error("播放音频失败 %s: %s", path, e)
        finally:
            # 清理临时文件
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

    _playing = False


async def _play_file(path: Path):
    """播放单个音频文件。"""
    logger.info("播放: %s", path)
    pygame.mixer.music.load(str(path))
    pygame.mixer.music.play()

    # 异步等待播放完成
    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.05)

    logger.info("播放完成")


def stop():
    """停止当前播放并清空队列。"""
    if _initialized:
        pygame.mixer.music.stop()
    _queue.clear()
    logger.info("播放已停止")
