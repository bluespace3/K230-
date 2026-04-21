"""K230 WiFi 连接模块"""
import network
import time
import logger


def connect(ssid, password):
    """连接 WiFi，每 5 秒重试，直到成功才返回。返回本机 IP 地址。"""
    logger.info("WiFi", "正在初始化网络接口...")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    attempt = 0
    while True:
        attempt += 1

        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            logger.info("WiFi", "已连接: " + ip)
            return ip

        logger.info("WiFi", "正在连接 " + ssid + "... (第 " + str(attempt) + " 次)")
        try:
            wlan.disconnect()
            time.sleep(0.3)
            wlan.connect(ssid, password)

            start = time.ticks_ms()
            while not wlan.isconnected():
                if time.ticks_diff(time.ticks_ms(), start) > 10000:
                    raise RuntimeError("连接超时")
                time.sleep(0.3)

            ip = wlan.ifconfig()[0]
            logger.info("WiFi", "已连接: " + ip)
            return ip
        except Exception as e:
            logger.warn("WiFi", "第 " + str(attempt) + " 次失败: " + str(e))
            wlan.disconnect()
            logger.info("WiFi", "5 秒后重试...")
            time.sleep(5)
