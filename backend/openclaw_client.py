import json
import logging

import httpx

from config import (
    OPENCLAW_API_KEY,
    OPENCLAW_GATEWAY_URL,
    OPENCLAW_MODEL,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


def _build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if OPENCLAW_API_KEY:
        headers["Authorization"] = f"Bearer {OPENCLAW_API_KEY}"
    return headers


def build_messages(
    user_message: str,
    history: list[dict] | None = None,
    context: str | None = None,
) -> list[dict]:
    """构建完整 messages 列表：system + 历史对话 + 当前消息。"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": f"当前感知上下文：{context}"})
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    return messages


def _extract_text(data: dict) -> str:
    """从 OpenAI 兼容响应中提取纯文本，过滤掉工具调用。"""
    choice = data.get("choices", [{}])[0]
    message = choice.get("message", {})

    # 只取 content，忽略 tool_calls
    return message.get("content", "") or ""


def _extract_stream_text(delta: dict) -> str:
    """从流式 delta 中提取纯文本，过滤工具调用相关字段。

    OpenAI 兼容流式响应的 delta 结构：
    - delta.content: 正常文本（需要）
    - delta.tool_calls: 工具调用 JSON（不需要，不播报）
    - delta.role: 角色标记（跳过）
    """
    # 如果有 tool_calls 字段，说明是工具调用阶段，跳过
    if "tool_calls" in delta:
        logger.debug("跳过工具调用 delta")
        return ""

    return delta.get("content", "") or ""


async def chat_stream(
    user_message: str,
    history: list[dict] | None = None,
    context: str | None = None,
):
    """流式调用 OpenClaw，逐块 yield 纯文本片段（已过滤工具调用）。"""
    url = f"{OPENCLAW_GATEWAY_URL}/v1/chat/completions"
    payload = {
        "model": OPENCLAW_MODEL,
        "messages": build_messages(user_message, history, context),
        "stream": True,
    }

    logger.info("请求 OpenClaw: url=%s payload=%s", url, json.dumps(payload, ensure_ascii=False)[:200])

    async with httpx.AsyncClient(timeout=60.0, proxy=None) as client:
        async with client.stream("POST", url, json=payload, headers=_build_headers()) as response:
            if response.status_code >= 400:
                error_body = await response.aread()
                logger.error("OpenClaw 错误 %d: %s", response.status_code, error_body.decode())
                response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                chunk = json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = _extract_stream_text(delta)
                if text:
                    yield text
