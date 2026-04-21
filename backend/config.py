import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# 项目根目录
BASE_DIR = Path(__file__).parent

# OpenClaw Gateway
OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
OPENCLAW_API_KEY = os.getenv("OPENCLAW_API_KEY", "")
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openclaw/default")

# 后端服务
BACKEND_HOST = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# TTS
TTS_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_RATE = os.getenv("TTS_RATE", "+20%")
TTS_FALLBACK_OFFLINE = os.getenv("TTS_FALLBACK_OFFLINE", "true").lower() == "true"

# 临时音频目录
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# 系统提示词（K230 感知上下文）
SYSTEM_PROMPT = """你是一个智能语音助手，运行在用户的桌面上。用户通过 K230 设备的摄像头和麦克风与你交互。
你会收到来自 K230 设备的感知信息：
- 人脸检测：有人靠近、识别到特定用户
- 手势识别：用户做出的手势（挥手、比数字等）
- 语音指令：用户的语音转文字内容

请用简短的中文回复（不超过50字），因为回复会通过 TTS 语音播报。回复要自然、友好。
直接对话，不要输出任何 markdown 格式、链接或特殊符号，只输出纯文本。"""
