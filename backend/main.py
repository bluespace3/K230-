import asyncio
import logging
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import audio_player
import asr_engine
import openclaw_client
import tts_engine
from config import BACKEND_HOST, BACKEND_PORT, TEMP_DIR

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

app = FastAPI(title="K230 Smart Assistant Backend")

# ── 调试：保存录音到 asr 目录 ─────────────────────────
ASR_DEBUG_DIR = Path(__file__).parent / "temp" / "asr"
ASR_DEBUG_DIR.mkdir(parents=True, exist_ok=True)

# ── 处理锁：正在处理时丢弃新的 event 请求 ────────────
_processing = False

# ── 会话管理 ─────────────────────────────────────────────
SESSION_TIMEOUT = 600  # 10 分钟会话超时


class ConversationSession:
    """管理单次会话的对话历史和状态。"""

    def __init__(self):
        self.history: list[dict] = []  # [{"role": "user/assistant", "content": ..., "ts": float}]
        self.greeted = False
        self.last_active = time.time()

    def is_expired(self) -> bool:
        return time.time() - self.last_active > SESSION_TIMEOUT

    def get_history(self) -> list[dict]:
        """返回最近 10 分钟的对话历史（不含时间戳，供 LLM 使用）。"""
        now = time.time()
        recent = [m for m in self.history if now - m["ts"] < SESSION_TIMEOUT]
        self.history = recent  # 清理过期
        return [{"role": m["role"], "content": m["content"]} for m in recent]

    def add_message(self, role: str, content: str):
        self.history.append({"role": role, "content": content, "ts": time.time()})
        self.last_active = time.time()

    def touch(self):
        self.last_active = time.time()


_session = ConversationSession()


@app.middleware("http")
async def log_all_requests(request, call_next):
    logger.info(">>> %s %s from %s", request.method, request.url.path, request.client.host if request.client else "?")
    response = await call_next(request)
    logger.info("<<< %s %s status=%d", request.method, request.url.path, response.status_code)
    return response


# ── 请求模型 ──────────────────────────────────────────


class EventRequest(BaseModel):
    type: str  # face | gesture | voice
    data: dict


# ── 路由 ──────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/event")
async def handle_event(event: EventRequest):
    """接收 K230 感知事件，收到即返回 200，处理中去重丢弃。"""
    global _processing, _session
    logger.info("处理事件: type=%s data=%s", event.type, event.data)

    # 会话超时则重置
    if _session.is_expired():
        logger.info("会话超时，开启新会话")
        _session = ConversationSession()

    # 人脸到达事件：仅在未打过招呼时触发问候
    if event.type == "face":
        action = event.data.get("action", "detect")
        if action == "arrive":
            if _session.greeted:
                logger.info("会话内已打过招呼，跳过")
                return JSONResponse({"status": "ignored_greeted"}, status_code=200)
            _session.greeted = True
            user_message = "有人来了！主动打个招呼吧，语气要活泼自然，像朋友见面一样，可以主动发起话题（比如聊聊今天天气、最近有趣的事）。不超过40个字。"
            context = "人脸到达-主动问候"
        elif action == "leave":
            user_message = "所有人都离开了。"
            context = "人脸离开"
        else:
            user_message = ""
            context = None

        if not user_message:
            return JSONResponse({"status": "ignored"}, status_code=200)
    else:
        user_message, context = _build_prompt(event)
        if not user_message:
            return JSONResponse({"status": "ignored"}, status_code=200)

    if _processing:
        logger.info("丢弃事件（处理中）: type=%s", event.type)
        return JSONResponse({"status": "dropped"}, status_code=200)

    _processing = True
    _session.touch()
    history = _session.get_history()
    _session.add_message("user", user_message)

    asyncio.create_task(_process_event_bg(user_message, history, context))
    return {"status": "ok", "message": "事件已收到，正在处理"}


async def _process_event_bg(user_message: str, history: list[dict], context: str | None):
    """后台处理事件：LLM → TTS 播放，保存回复到会话历史。"""
    global _processing
    try:
        chunks = []
        async for text_chunk in openclaw_client.chat_stream(user_message, history, context):
            chunks.append(text_chunk)
        reply = "".join(chunks).strip()
        logger.info("LLM 回复: %s", reply[:100])
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return
    finally:
        _processing = False

    if reply:
        _session.add_message("assistant", reply)
        await _speak(reply)


def _strip_markdown(text: str) -> str:
    """去除 LLM 回复中的 markdown 格式符号，确保 TTS 读出来干净。"""
    import re
    # 去掉加粗/斜体标记
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    # 去掉标题标记
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # 去掉列表标记
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    # 去掉有序列表标记
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # 去掉代码块标记
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # 去掉链接，只保留文字
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # 去掉分割线
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    # 清理多余空行
    text = re.sub(r'\n{2,}', '\n', text).strip()
    return text


async def _speak(text: str):
    """TTS 合成并播放（后台任务），自动过滤 markdown。"""
    text = _strip_markdown(text)
    if not text:
        return
    try:
        audio_path = await tts_engine.synthesize(text)
        await audio_player.play(audio_path)
    except Exception as e:
        logger.error("TTS/播放失败: %s", e)


@app.post("/api/voice")
async def handle_voice(request: Request):
    """接收 K230 音频文件，流式写入磁盘，收到即返回 200。"""
    content_length = int(request.headers.get("content-length", 0))
    logger.info("语音上传开始: Content-Length=%d", content_length)

    save_path = TEMP_DIR / f"voice_{int(asyncio.get_event_loop().time() * 1000)}.wav"

    async def _read_body():
        total = 0
        with open(save_path, "wb") as f:
            async for chunk in request.stream():
                f.write(chunk)
                total += len(chunk)
        return total

    try:
        # 60 秒超时保护，防止 K230 数据不完整导致无限等待
        total = await asyncio.wait_for(_read_body(), timeout=60)
    except asyncio.TimeoutError:
        logger.error("语音上传超时 (60s), 已放弃")
        _cleanup_file(save_path)
        return JSONResponse({"status": "error", "detail": "上传超时"}, status_code=408)
    except Exception as e:
        logger.error("读取语音流失败: %s", e)
        _cleanup_file(save_path)
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)

    if total == 0:
        _cleanup_file(save_path)
        return JSONResponse({"status": "error", "detail": "空音频数据"}, status_code=400)

    if content_length and total != content_length:
        logger.warning("语音数据不完整: 收到 %d bytes, 预期 %d bytes", total, content_length)

    logger.info("收到语音文件: %s (%d bytes)", save_path, total)

    # 后台异步处理，立即返回
    asyncio.create_task(_process_voice(save_path))

    return {"status": "ok", "message": "语音已收到，正在处理"}


async def _process_voice(save_path: Path):
    """后台处理语音：ASR → LLM（带历史）→ TTS 播放。"""
    global _session

    # 会话超时则重置
    if _session.is_expired():
        logger.info("会话超时，开启新会话")
        _session = ConversationSession()

    # 保存录音到 asr 调试目录
    debug_path = ASR_DEBUG_DIR / save_path.name
    try:
        import shutil
        shutil.copy2(save_path, debug_path)
        logger.info("录音已备份: %s", debug_path)
    except Exception as e:
        logger.warning("备份录音失败: %s", e)

    try:
        text = await asyncio.to_thread(asr_engine.transcribe, save_path)
    except Exception as e:
        logger.error("ASR 识别失败: %s (文件: %s)", e, debug_path)
        return

    logger.info("ASR 识别结果 [%s]: '%s' (文件: %s)", "有内容" if text else "空", text, debug_path.name)

    if not text:
        logger.info("ASR 未识别到语音内容，录音已保存: %s", debug_path)
        return

    _session.touch()
    _session.add_message("user", text)
    history = _session.get_history()

    try:
        chunks = []
        async for text_chunk in openclaw_client.chat_stream(text, history, "语音输入"):
            chunks.append(text_chunk)
        reply = "".join(chunks).strip()
    except Exception as e:
        logger.error("LLM 调用失败: %s", e)
        return

    if reply:
        _session.add_message("assistant", reply)
        await _speak(reply)


def _cleanup_file(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


# ── 辅助函数 ──────────────────────────────────────────


def _build_prompt(event: EventRequest) -> tuple[str, str | None]:
    """根据事件类型构建用户消息和上下文。"""
    event_type = event.type
    data = event.data
    context = None

    if event_type == "face":
        action = data.get("action", "detect")
        face_count = data.get("face_count", 0)

        if action == "leave":
            user_message = "所有人都离开了。"
            context = "人脸离开"
        else:
            user_message = f"检测到 {face_count} 张人脸。请打个招呼。"
            context = f"人脸检测: count={face_count}"

    elif event_type == "gesture":
        gesture = data.get("gesture", "未知")
        confidence = data.get("confidence", 0)
        user_message = f"检测到手势：{gesture}（置信度 {confidence:.0%}）。请回应。"
        context = f"手势识别: gesture={gesture}"

    elif event_type == "voice":
        text = data.get("text", "")
        if not text:
            return "", None
        user_message = text
        context = "语音输入"

    else:
        user_message = ""
        context = None

    return user_message, context


# ── 入口 ──────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=BACKEND_HOST, port=BACKEND_PORT, reload=True)
