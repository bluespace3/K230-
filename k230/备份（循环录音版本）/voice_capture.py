"""K230 语音录制模块（遵循官方模式：每次录音创建/销毁 PyAudio）

参考 CanMV 官方 audio 示例，每次录音完整走一遍：
  PyAudio() → initialize → open → record → close → terminate
不使用全局 PyAudio，避免 VB 块泄漏导致 stream.read() 卡死。
"""
import os
import sys
import time
import gc
import logger

SAVE_DIR = "/sdcard/aiAssitant/voice_cache"
RATE = 44100
CHANNELS = 1
CHUNK = RATE // 25  # 1764
DURATION = 5


def init():
    """仅创建录音目录。PyAudio 按官方模式在每次录音时创建/销毁。"""
    try:
        os.mkdir(SAVE_DIR)
    except OSError:
        pass
    logger.info("Voice", "录音模块就绪")


def record():
    """固定时长录音，每次完整创建/销毁 PyAudio。"""
    gc.collect()

    filepath = SAVE_DIR + "/rec_" + str(time.ticks_ms()) + ".wav"
    logger.info("Voice", "开始录音 " + str(DURATION) + "s -> " + filepath)

    p = None
    stream = None
    try:
        from media.pyaudio import PyAudio, paInt16, LEFT, RIGHT
        import media.wave as wave

        p = PyAudio()
        p.initialize(CHUNK)

        stream = p.open(
            format=paInt16,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK,
        )
        stream.volume(LEFT, 70)
        stream.volume(RIGHT, 70)

        # 预热 500ms
        for _ in range(int(RATE / CHUNK * 0.5)):
            stream.read()

        logger.info("Voice", "录音开始 " + str(DURATION) + "s")
        total_chunks = int(RATE / CHUNK * DURATION)
        frames = []

        for i in range(total_chunks):
            data = stream.read()
            if data:
                frames.append(data)
            if (i + 1) % 25 == 0:
                logger.info("Voice", "录音中... " + str((i + 1) * CHUNK // RATE) + "s/" + str(DURATION) + "s")

        stream.stop_stream()
        stream.close()
        stream = None

        logger.info("Voice", "录音停止，保存文件...")

        wf = wave.open(filepath, "wb")
        wf.set_channels(CHANNELS)
        wf.set_sampwidth(p.get_sample_size(paInt16))
        wf.set_framerate(RATE)
        wf.write_frames(b"".join(frames))
        wf.close()

        p.terminate()
        p = None

        gc.collect()

        size = os.stat(filepath)[6]
        logger.info("Voice", "录音完成: " + filepath + " (" + str(size) + " bytes)")

        if size < 1000:
            logger.warn("Voice", "录音文件过小")
            return None

        return filepath

    except Exception as e:
        logger.error("Voice", "录音失败: " + str(e))
        sys.print_exception(e)
        return None

    finally:
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if p:
            try:
                p.terminate()
            except Exception:
                pass
        gc.collect()
