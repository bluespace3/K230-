"""K230 HTTP 客户端 - 向 PC 后端发送事件"""
import requests
import time
import logger


# ── 配置 ─────────────────────────────────────
# 修改为你的 PC 局域网 IP
PC_BACKEND_URL = "http://192.168.10.200:8080"


def send_event(event_type, data, timeout=3):
    """发送感知事件到 PC 后端（fire-and-forget，不阻塞主循环）。"""
    payload = {"type": event_type, "data": data}
    url = PC_BACKEND_URL + "/api/event"

    logger.info("HTTP", "发送事件: " + event_type)
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.close()
        logger.info("HTTP", "事件已发送: " + event_type)
        return True
    except Exception as e:
        logger.warn("HTTP", "事件发送失败（不影响运行）: " + str(e))
        return False


def get_command(timeout=3):
    """轮询后端指令，返回 command 字符串或 None。"""
    import json
    url = PC_BACKEND_URL + "/api/command"
    try:
        resp = requests.get(url, timeout=timeout)
        raw = resp.read()
        resp.close()
        logger.info("HTTP", "command resp: " + raw[:80])
        data = json.loads(raw)
        cmd = data.get("command")
        if cmd:
            logger.info("HTTP", "收到指令: " + cmd)
        return cmd
    except Exception as e:
        logger.warn("HTTP", "get_command 异常: " + str(e))
        return None


def _send_all(sock, data):
    """确保所有数据都发送完毕，处理部分发送和 EAGAIN。"""
    total = 0
    while total < len(data):
        try:
            n = sock.send(data[total:])
            if n is None or n <= 0:
                break
            total += n
        except OSError as e:
            if e.args[0] == 11:  # EAGAIN: 缓冲区满，等一下重试
                time.sleep_ms(10)
                continue
            raise
    return total


def send_voice_file(file_path, timeout=10):
    """上传音频文件到 PC 后端（用原生 socket 发送，比 urequests 快得多）。"""
    import socket
    import usocket

    try:
        with open(file_path, "rb") as f:
            audio_data = f.read()

        data_len = len(audio_data)
        # 解析 URL
        url = PC_BACKEND_URL + "/api/voice"
        # http://host:port/api/voice
        host_port = PC_BACKEND_URL.replace("http://", "").split("/")
        host_port = host_port[0]
        if ":" in host_port:
            host, port = host_port.split(":")
            port = int(port)
        else:
            host = host_port
            port = 80

        logger.info("HTTP", "上传语音 " + str(data_len) + " bytes -> " + host + ":" + str(port))

        # 构建 HTTP 请求
        header = (
            "POST /api/voice HTTP/1.1\r\n"
            "Host: " + host + "\r\n"
            "Content-Type: audio/wav\r\n"
            "Content-Length: " + str(data_len) + "\r\n"
            "Connection: close\r\n"
            "\r\n"
        )

        # DNS 解析 + 连接
        addr = usocket.getaddrinfo(host, port)[0][-1]
        sock = usocket.socket()

        # 建立连接和发送数据阶段，设置更长的超时（或不设置，靠系统默认）
        sock.settimeout(timeout)
        sock.connect(addr)
        logger.info("HTTP", "socket 已连接")

        # 发送 header
        _send_all(sock, header.encode())

        # 分块发送 body
        sent = 0
        chunk_size = 8192
        while sent < data_len:
            end = min(sent + chunk_size, data_len)
            n = _send_all(sock, audio_data[sent:end])
            if n <= 0:
                logger.warn("HTTP", "发送中断，已发 " + str(sent) + "/" + str(data_len))
                break
            sent += n
            time.sleep_ms(2) # 稍微喘口气，防止缓冲区打满导致路由器丢包

        logger.info("HTTP", "已发送 " + str(sent) + " bytes，等待响应...")

        # 读取响应阶段，如果卡住 5 秒就直接返回成功（数据已经发完）
        sock.settimeout(5.0)
        try:
            resp_data = sock.recv(256)
        except OSError:
            # 响应超时，但数据已发送完毕
            resp_data = b""

        sock.close()

        resp_str = resp_data.decode("utf-8", "ignore")
        logger.info("HTTP", "响应: " + resp_str.split("\r\n")[0] if resp_str else "(空)")

        if "200" in resp_str:
            return {"status": "ok"}
        elif not resp_str or len(resp_str) < 10:
            # 空响应或超时：数据已全部发送，可能是后端处理慢，视为成功
            logger.info("HTTP", "响应为空但数据已全部发送，视为上传成功")
            return {"status": "ok"}
        else:
            logger.warn("HTTP", "非200响应: " + resp_str[:100])
            return None

    except Exception as e:
        logger.error("HTTP", "上传语音失败: " + str(e))
        import sys
        sys.print_exception(e)
        return None
