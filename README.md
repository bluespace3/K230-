# K230 智能助手 - 项目文档

## 1. 项目概述

基于 K230 AI 视觉设备和本地 PC 的智能语音助手系统。K230 作为前端传感器（人脸检测+识别、手势识别、语音采集），PC 后端集成 OpenClaw AI 平台处理交互，通过 TTS 语音播报回答。

## 2. 系统架构

```
┌─────────────────────────┐         WiFi/LAN          ┌─────────────────────────────────────┐
│     K230 设备 (前端)      │    ◄──────────────►       │       Windows PC (后端)               │
│                          │       HTTP JSON           │                                      │
│  GC2093 摄像头            │                           │  FastAPI 服务 (:8080)                 │
│  板载麦克风               │ ─── POST /api/event ──►  │    ├── openclaw_client.py             │
│  6 TOPS KPU NPU          │                           │    │     ↓ HTTP SSE                   │
│  1GB RAM                  │                           │    │  OpenClaw Gateway (:18790)        │
│  CanMV MicroPython       │                           │    │     ↓                            │
│                          │                           │    │  vllm/Qwen3.6-35B-A3B-AWQ         │
│  运行模块:                │                           │    │     ↓                            │
│   ├─ face_detect.py      │                           │    ├── tts_engine.py (edge-tts)       │
│   │  ├─ 人脸检测          │                           │    │     ↓ MP3                        │
│   │  └─ 人脸识别(身份)    │                           │    ├── asr_engine.py (faster-whisper) │
│   ├─ gesture_recog.py    │                           │    │     ↑ WAV                        │
│   ├─ voice_capture.py    │ ─── POST /api/voice ──►  │    └── audio_player.py (pygame)       │
│   └─ http_client.py      │                           │          ↓ → 音箱播放                 │
└─────────────────────────┘                           └─────────────────────────────────────┘
```

## 3. 技术栈

| 组件 | 技术 | 版本/说明 |
|------|------|----------|
| **K230 固件** | CanMV MicroPython | 基于 Kendryte K230 SDK |
| **K230 AI** | KPU NPU (6 TOPS) | YOLOv2 人脸检测、特征提取人脸识别、分类模型手势识别 |
| **PC 后端** | Python 3.11 + FastAPI | 异步 HTTP 服务 |
| **AI 平台** | OpenClaw Gateway v2026.4 | 本地部署，OpenAI 兼容 API |
| **AI 模型** | vllm/Qwen3.6-35B-A3B-AWQ | 本地 vLLM 推理，262K 上下文 |
| **语音识别** | faster-whisper (large-v3) | 本地 ASR，int8 量化，中文优化 |
| **TTS 在线** | edge-tts | 微软 Edge TTS，中文语音 zh-CN-XiaoxiaoNeural |
| **TTS 离线** | pyttsx3 | 无网络时的降级方案 |
| **音频播放** | pygame 2.6 | MP3/WAV 播放，播放队列 |
| **HTTP 客户端** | httpx | 异步，支持 SSE 流式响应 |
| **K230 HTTP** | urequests | MicroPython 内置 HTTP 库 |

## 4. 项目目录结构

```
D:\code\py\AIassistant\
│
├── README.md                    ← 本文件
│
├── backend/                     # PC 端 Python 后端
│   ├── venv/                    # Python 虚拟环境
│   ├── .env                     # 环境变量配置 (不提交到版本控制)
│   ├── .env.example             # 环境变量模板
│   ├── .gitignore
│   ├── requirements.txt         # Python 依赖
│   ├── config.py                # 全局配置
│   ├── main.py                  # FastAPI 入口 + 路由
│   ├── openclaw_client.py       # OpenClaw Gateway API 客户端
│   ├── asr_engine.py            # 语音识别 (faster-whisper)
│   ├── tts_engine.py            # TTS 语音合成 (edge-tts + pyttsx3)
│   ├── audio_player.py          # 音频播放 (pygame)
│   └── temp/                    # 临时音频文件目录
│
└── k230/                        # K230 MicroPython 脚本
    ├── main.py                  # K230 主入口
    ├── wifi_connect.py          # WiFi 连接
    ├── http_client.py           # HTTP 事件上报 + 音频上传
    ├── face_detect.py           # KPU 人脸检测 + 识别
    ├── gesture_recog.py         # KPU 手势识别
    └── voice_capture.py         # 板载麦克风录音
```

## 5. K230 模型文件

所有 kmodel 文件部署在 `/sdcard/kmodel/` 目录（PC 端通过 `此电脑\CanMV\sdcard\kmodel` 访问）：

| 模型文件 | 功能 | 说明 |
|----------|------|------|
| `face_detection_320.kmodel` | 人脸检测 | YOLOv2，检测人脸位置和边界框 |
| `face_recognition.kmodel` | 人脸识别 | 特征提取，提取人脸特征向量用于身份比对 |
| `gesture.kmodel` | 手势识别 | 分类模型，识别握拳/数字/OK等手势 |

## 6. 后端 API 接口文档

### 6.1 健康检查

```
GET /api/health
```

**响应**：
```json
{ "status": "ok" }
```

### 6.2 感知事件上报

```
POST /api/event
Content-Type: application/json
```

**请求体**：
```json
{
  "type": "face | gesture | voice",
  "data": { ... }
}
```

**事件类型及 data 格式**：

| type | data 字段 | 说明 |
|------|----------|------|
| `face` | `face_id`, `face_count`, `registered_count` | 人脸事件，`face_id` 为识别到的人名或 `"unknown"` |
| `gesture` | `gesture`, `gesture_cn`, `confidence` | 手势识别事件 |
| `voice` | `text` | 语音转文字内容 |

**请求示例**：

```bash
# 语音事件
curl -X POST http://192.168.x.x:8080/api/event \
  -H "Content-Type: application/json" \
  -d '{"type":"voice","data":{"text":"今天天气怎么样"}}'

# 人脸事件（已识别身份）
curl -X POST http://192.168.x.x:8080/api/event \
  -H "Content-Type: application/json" \
  -d '{"type":"face","data":{"face_id":"张三","face_count":1,"registered_count":3}}'

# 人脸事件（未知人脸）
curl -X POST http://192.168.x.x:8080/api/event \
  -H "Content-Type: application/json" \
  -d '{"type":"face","data":{"face_id":"unknown","face_count":1,"registered_count":3}}'

# 手势事件
curl -X POST http://192.168.x.x:8080/api/event \
  -H "Content-Type: application/json" \
  -d '{"type":"gesture","data":{"gesture":"five","gesture_cn":"张开手掌","confidence":0.92}}'
```

**响应**：
```json
{
  "status": "ok",
  "reply": "今天天气不错，阳光明媚。"
}
```

**处理流程**：
1. 收到事件 → `_build_prompt()` 根据 type 构建用户消息和上下文
2. 调用 `openclaw_client.chat_stream()` 流式请求 OpenClaw Gateway
3. 流式过程中过滤 `tool_calls` delta（不播报工具调用信息）
4. 收集完整回复文本
5. 后台任务 `_speak()` → `tts_engine.synthesize()` → `audio_player.play()`
6. 立即返回 JSON 给 K230（不等 TTS 完成）

### 6.3 语音文件上传（完整 ASR 流程）

```
POST /api/voice
Content-Type: multipart/form-data
```

**请求**：multipart 文件上传，字段名 `file`（WAV/MP3 格式）

**处理流程**：
1. 保存音频文件到 `temp/`
2. `asr_engine.transcribe()` — faster-whisper 本地语音识别转文字
3. 将识别文字发送到 OpenClaw 进行对话
4. TTS 合成回复并播放
5. 清理临时文件

**响应**：
```json
{
  "status": "ok",
  "asr_text": "你好，今天天气怎么样",
  "reply": "今天天气不错，阳光明媚，适合出门散步。"
}
```

## 7. 后端模块详细设计

### 7.1 config.py — 全局配置

通过 `.env` 文件管理所有配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `OPENCLAW_GATEWAY_URL` | `http://127.0.0.1:18790` | OpenClaw Gateway 地址 |
| `OPENCLAW_API_KEY` | 空 | Gateway 认证 token |
| `OPENCLAW_MODEL` | `openclaw/default` | 模型标识（API 层面使用 `openclaw/default`） |
| `BACKEND_HOST` | `0.0.0.0` | 后端监听地址 |
| `BACKEND_PORT` | `8080` | 后端监听端口（注意：8000 被 vllm 占用） |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 语音 |
| `TTS_RATE` | `+20%` | 语速（加快以降低延迟体感） |
| `TTS_FALLBACK_OFFLINE` | `true` | edge-tts 失败时是否回退到 pyttsx3 |

`SYSTEM_PROMPT` 定义了 AI 助手的角色和行为约束（简短中文回复、不超过50字）。

### 7.2 openclaw_client.py — OpenClaw 客户端

**调用方式**：HTTP SSE 流式请求 OpenClaw Gateway 的 OpenAI 兼容 API

```
POST http://127.0.0.1:18790/v1/chat/completions
Authorization: Bearer <token>
```

**请求体**：
```json
{
  "model": "openclaw/default",
  "messages": [
    {"role": "system", "content": "系统提示词..."},
    {"role": "system", "content": "当前感知上下文：语音输入"},
    {"role": "user", "content": "用户消息"}
  ],
  "stream": true
}
```

**关键设计**：
- 使用 `httpx.AsyncClient.stream()` 处理 SSE 响应
- `_extract_stream_text()` 过滤 `delta.tool_calls`（OpenClaw 工具调用阶段产生的 JSON 不播报）
- 只 yield `delta.content` 的纯文本内容
- 错误处理：捕获 4xx/5xx 并记录完整错误 body

**SSE 响应格式**：
```
data: {"choices":[{"delta":{"role":"assistant"}}]}
data: {"choices":[{"delta":{"content":"你"},"finish_reason":null}]}
data: {"choices":[{"delta":{"content":"好"},"finish_reason":null}]}
data: [DONE]
```

### 7.3 asr_engine.py — 语音识别

**模型**：faster-whisper `large-v3`，int8 量化，CPU 推理

**关键设计**：
- 懒加载：首次调用时才加载模型，避免启动阻塞
- 使用 `asyncio.to_thread()` 在后台线程运行 ASR（不阻塞事件循环）
- VAD 过滤：自动过滤静音片段
- 中文优化：`language="zh"` + `beam_size=5`

**API**：
- `transcribe(audio_path, language="zh")` → `str`：音频转文字

### 7.4 tts_engine.py — TTS 语音合成

**优先级链**：
1. **edge-tts**（在线）：微软 Edge TTS 服务，高质量中文语音，生成 MP3
2. **pyttsx3**（离线回退）：系统本地 TTS，生成 WAV，音质一般

**API**：
- `synthesize(text, output_path?)` → `Path`：合成语音文件
- `synthesize_stream(text)` → `AsyncGenerator[bytes]`：流式合成（预留）

### 7.5 audio_player.py — 音频播放

**特性**：
- pygame.mixer 播放 MP3/WAV
- 播放队列（`deque`），防止多个回复重叠
- 异步等待播放完成（`asyncio.sleep` 轮询）
- 播放完成后自动删除临时文件

**API**：
- `play(audio_path)` → 异步播放
- `stop()` → 停止当前播放并清空队列

### 7.6 main.py — FastAPI 主服务

**事件处理流程** (`/api/event`)：
```
K230 POST /api/event
    ↓
handle_event()
    ↓ _build_prompt() → 构建 user_message + context
    ↓
openclaw_client.chat_stream() → 流式收集完整回复
    ↓
asyncio.create_task(_speak(reply)) → 后台 TTS + 播放
    ↓
返回 {"status":"ok","reply":"..."} → K230 立即收到响应
```

**语音处理流程** (`/api/voice`)：
```
K230 POST /api/voice (WAV 文件)
    ↓
handle_voice()
    ↓ asyncio.to_thread(asr_engine.transcribe) → ASR 转文字
    ↓
openclaw_client.chat_stream() → OpenClaw 对话
    ↓
asyncio.create_task(_speak(reply)) → TTS + 播放
    ↓
返回 {"status":"ok","asr_text":"...","reply":"..."}
```

**事件到提示词的映射**：

| 事件 | 生成的用户消息 | 上下文 |
|------|--------------|--------|
| face (已知) | `检测到人脸：张三。请打个招呼。` | `人脸检测: id=张三, registered_count=3` |
| face (未知) | `检测到人脸：未知。请打个招呼。` | `人脸检测: id=unknown, registered_count=3` |
| gesture | `检测到手势：five（置信度 92%）。请回应。` | `手势识别: gesture=five, confidence=0.92` |
| voice | 原始文字内容 | `语音输入` |

## 8. K230 端模块设计

### 8.1 通信协议

K230 通过 HTTP JSON 与 PC 后端通信：

| 方向 | 接口 | 数据格式 |
|------|------|---------|
| K230 → PC | `POST /api/event` | `{"type":"face|gesture|voice","data":{...}}` |
| K230 → PC | `POST /api/voice` | multipart/form-data 音频文件 |

### 8.2 http_client.py — HTTP 客户端

- `send_event(event_type, data)` — JSON POST 到 `/api/event`
- `send_voice_file(file_path)` — multipart POST 到 `/api/voice`
- 超时和错误由 `urequests` 异常处理

**配置**：`PC_BACKEND_URL` 需要修改为 PC 的局域网 IP（默认 `http://192.168.1.200:8080`）

### 8.3 face_detect.py — 人脸检测 + 识别

**两阶段流程**：

```
摄像头帧 → face_detection_320.kmodel → 检测人脸位置
                                        ↓ 裁剪人脸区域 (128x128)
                face_recognition.kmodel → 提取特征向量
                                        ↓ 余弦相似度比对
                人脸库 (face_db)        → 返回身份或 "unknown"
```

**关键设计**：
- `face_db`：已注册人脸的特征向量字典 `{name: [float, ...]}`
- 相似度阈值：0.75（余弦相似度）
- `register_face(name, feature)`：注册新人脸到库
- LCD 显示：已知人脸绿色显示名字，未知人脸黄色显示 "face"
- 防抖：3 秒内只上报一次
- 降级：识别模型加载失败时退化为纯检测模式

### 8.4 gesture_recog.py — 手势识别

- 模型路径：`/sdcard/kmodel/gesture.kmodel`
- 使用 KPU 分类（`KPU.forward` + `KPU.fmap_to_list`）
- 置信度阈值：0.7
- 手势映射：fist/one/two/three/four/five/six/rock/ok → 中文

### 8.5 voice_capture.py — 语音录制

- 使用板载麦克风，采样率 16000
- 录制 5 秒 WAV 文件后上传到 PC `/api/voice`
- PC 端 faster-whisper 完成语音识别

### 8.6 wifi_connect.py — WiFi 连接

- 使用 `network.WLAN(network.STA_IF)`
- 超时 15 秒
- 返回本机 IP

**注意**：K230 WiFi 仅支持 2.4GHz，不支持 5GHz。

### 8.7 main.py — K230 主入口

启动顺序：
1. LCD 初始化
2. WiFi 连接
3. 摄像头初始化
4. 加载人脸检测模型（必须成功）
5. 加载人脸识别模型（失败则降级为纯检测模式）
6. 运行人脸检测+识别主循环

## 9. 环境配置

### 9.1 PC 端

```bash
# 1. 创建虚拟环境
cd D:\code\py\AIassistant\backend
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置

# 4. 确保 OpenClaw Gateway 已启动并启用 HTTP API
# openclaw.json 中 gateway.http.endpoints.chatCompletions.enabled 需为 true

# 5. 启动后端（注意不要用 reload=True）
python main.py
```

### 9.2 K230 端

1. 确保 kmodel 文件已部署到 `/sdcard/kmodel/`：
   - `face_detection_320.kmodel`
   - `face_recognition.kmodel`
   - `gesture.kmodel`
2. 将 `k230/` 目录下的脚本上传到 K230 设备
3. 修改 `wifi_connect.py` 中的 WiFi SSID/密码
4. 修改 `http_client.py` 中的 `PC_BACKEND_URL` 为 PC 局域网 IP
5. 通过 CanMV IDE 运行 `main.py`

### 9.3 OpenClaw 配置

关键配置项（`~/.openclaw/openclaw.json`）：

```json
{
  "gateway": {
    "port": 18790,
    "http": {
      "endpoints": {
        "chatCompletions": { "enabled": true }
      }
    },
    "auth": {
      "token": "your_token"
    }
  }
}
```

- `18789`：WebUI 控制面板端口
- `18790`：Gateway API 端口（HTTP SSE）

## 10. 数据流时序

### 10.1 语音交互（完整链路）

```
K230                    PC Backend              OpenClaw Gateway         TTS/Speaker
 │                          │                         │                      │
 │── POST /api/voice ─────►│                         │                      │
 │   (WAV audio file)       │                         │                      │
 │                          │── faster-whisper ──────►│                      │
 │                          │   ASR: "你好"            │                      │
 │                          │── POST /v1/chat/... ──►│                      │
 │                          │   stream: true          │                      │
 │                          │◄── SSE: "你好！👋" ──────│                      │
 │                          │◄── [DONE] ──────────────│                      │
 │◄── {asr_text:"你好",     │                         │                      │
 │     reply:"你好！"} ─────│                         │                      │
 │                          │── async _speak() ───────┼──────────────────────│
 │                          │                         │   edge-tts 合成 MP3   │
 │                          │                         │──► pygame 播放 ──────►│ 🔊
```

### 10.2 人脸识别事件

```
K230                    PC Backend              OpenClaw Gateway         TTS/Speaker
 │                          │                         │                      │
 │── POST /api/event ──────►│                         │                      │
 │  {type:"face",           │                         │                      │
 │   data:{face_id:"张三",  │                         │                      │
 │    face_count:1}}        │── POST /v1/chat/... ──►│                      │
 │                          │◄── SSE: "张三你好！" ───│                      │
 │◄── {reply:"张三你好！"}──│── async _speak() ──────┼──────────────────────│
 │                          │                         │──► pygame 播放 ──────►│ 🔊
```

## 11. 已知限制和 TODO

| 项目 | 状态 | 说明 |
|------|------|------|
| 人脸注册 | 需实现 | `register_face()` API 已定义，需加按键触发注册逻辑 |
| 语音唤醒词 | TODO | K230 端做唤醒词检测，唤醒后才开始录音 |
| uvicorn reload | BUG | `reload=True` 时 httpx stream 行为异常，当前设为 `False` |
| 多事件并发 | 未处理 | 同时来人脸+手势事件时可能冲突，需要事件合并逻辑 |
| K230 WiFi | 注意 | 仅支持 2.4GHz，5GHz WiFi 无法连接 |
| 人脸库持久化 | TODO | 当前人脸库存在内存，重启后丢失，需保存到文件 |
