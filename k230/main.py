"""K230 智能助手主入口

CanMV v1.4.3 (Yahboom K230) MicroPython

状态机：
DETECTING → 人脸检测 + 轮询后端指令
RECORDING → 收到后端录音指令，蜂鸣 + 录音
UPLOADING → 录音结束，上传到后端
"""
import os
import sys
import time
import image
from media.sensor import Sensor
from media.display import Display
from media.media import MediaManager

sys.path.insert(0, '/sdcard/aiAssitant')

import wifi_connect
import face_detect
import http_client
import voice_capture
import buzzer
import logger

logger.clear()
logger.info("Main", "========== K230 设备启动 ==========")

# ── WiFi 配置 ─────────────────────────────────
WIFI_SSID = "田老板家的Wi-Fi"
WIFI_PASSWORD = "Tian1024"

# ── PC 后端地址 ────────────────────────────────
http_client.PC_BACKEND_URL = "http://192.168.10.200:8080"

# ── 分辨率 ─────────────────────────────────────
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
AI_WIDTH = 320
AI_HEIGHT = 240

RECORD_DURATION = 5  # 录音秒数
DETECT_INTERVAL_MS = 5000  # 人脸检测间隔 5 秒

# ── 状态 ───────────────────────────────────────
DETECTING = 0
RECORDING = 1
UPLOADING = 2
_last_detect_time = [0]  # 上次人脸检测时间
_last_report_time = [0]  # 上次上报人脸事件时间
_last_poll_time = [0]    # 上次轮询时间
POLL_INTERVAL_MS = 3000  # 轮询间隔 3 秒
REPORT_INTERVAL_MS = 15000  # 上报人脸间隔 15 秒


def _sensor_pause(sensor):
    """暂停传感器，释放 DMA 资源给录音。"""
    sensor.stop()


def _sensor_resume(sensor):
    """恢复传感器：reset + 重新配置 + 启动。"""
    sensor.reset()
    sensor.set_framesize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, chn=0)
    sensor.set_pixformat(Sensor.YUV420SP, chn=0)
    sensor.set_framesize(width=AI_WIDTH, height=AI_HEIGHT, chn=1)
    sensor.set_pixformat(Sensor.RGBP888, chn=1)
    Display.bind_layer(**sensor.bind_info(x=0, y=0, chn=0), layer=Display.LAYER_VIDEO1)
    sensor.run()
    logger.info("Main", "传感器已恢复")


def main():
    sensor = None
    state = DETECTING
    try:
        # 1. 初始化传感器
        logger.info("Main", "正在初始化传感器...")
        sensor = Sensor(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT)
        sensor.reset()
        sensor.set_framesize(width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, chn=0)
        sensor.set_pixformat(Sensor.YUV420SP, chn=0)
        sensor.set_framesize(width=AI_WIDTH, height=AI_HEIGHT, chn=1)
        sensor.set_pixformat(Sensor.RGBP888, chn=1)

        # 2. 初始化显示 + 绑定摄像头画面
        sensor_bind_info = sensor.bind_info(x=0, y=0, chn=0)
        Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)
        Display.init(Display.ST7701, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT, to_ide=True)

        # 3. 初始化媒体管理器
        MediaManager.init()
        sensor.run()
        logger.info("Main", "传感器和显示已初始化")

        # 3.5 初始化录音模块（仅创建目录，PyAudio 按官方模式每次录音时创建/销毁）
        voice_capture.init()

        # 4. 连接 WiFi
        ip = "0.0.0.0"
        logger.info("Main", "正在连接 WiFi...")
        try:
            ip = wifi_connect.connect(WIFI_SSID, WIFI_PASSWORD)
            logger.info("Main", "WiFi 已连接: " + str(ip))
        except Exception as e:
            logger.warn("Main", "WiFi 连接失败（继续离线运行）: " + str(e))

        # 5. 加载人脸检测模型
        logger.info("Main", "正在加载人脸检测模型...")
        try:
            detect_task = face_detect.init_detector()
        except Exception as e:
            logger.error("Main", "人脸检测模型加载失败: " + str(e))
            sys.print_exception(e)
            return

        logger.info("Main", "人脸检测已启动")

        # 测试蜂鸣器
        logger.info("Main", "测试蜂鸣器...")
        buzzer.beep(200)
        time.sleep_ms(200)

        http_client.send_event("startup", {
            "device": "K230",
            "ip": ip,
            "models": ["face_detection"],
        })

        # 6. 主循环（状态机）
        clock = time.clock()
        frame_count = 0
        # 创建 OSD 图像（ARGB8888 格式，用于绘制检测框）
        osd_img = image.Image(DISPLAY_WIDTH, DISPLAY_HEIGHT, image.ARGB8888)
        logger.info("Main", "主循环开始...")

        while True:
            try:
                os.exitpoint()

                if state == DETECTING:
                    # ── 人脸检测（每 5 秒检测一次，仅上报事件）──
                    now = time.ticks_ms()
                    detect_ok = time.ticks_diff(now, _last_detect_time[0]) > DETECT_INTERVAL_MS

                    if detect_ok:
                        _last_detect_time[0] = now
                        clock.tick()
                        ai_img = sensor.snapshot(chn=1)
                        frame_count += 1

                        face_list = face_detect.run_frame(detect_task, ai_img)
                        if face_list:
                            logger.info("Main", "人脸检测: 发现 " + str(len(face_list)) + " 张脸")
                            # 定期上报人脸事件（不依赖 face_detect 内部逻辑）
                            if time.ticks_diff(now, _last_report_time[0]) > REPORT_INTERVAL_MS:
                                _last_report_time[0] = now
                                http_client.send_event("face", {
                                    "action": "present",
                                    "face_count": len(face_list),
                                })

                        # 绘制检测框
                        osd_img.clear()
                        for face in face_list:
                            if len(face) >= 4:
                                x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                                osd_img.draw_rectangle(
                                    x * DISPLAY_WIDTH // AI_WIDTH,
                                    y * DISPLAY_HEIGHT // AI_HEIGHT,
                                    w * DISPLAY_WIDTH // AI_WIDTH,
                                    h * DISPLAY_HEIGHT // AI_HEIGHT,
                                    color=(0, 255, 0, 255), thickness=2,
                                )
                        Display.show_image(osd_img, 0, 0, Display.LAYER_OSD1)

                    # ── 轮询后端指令（仅 DETECTING 空闲时，3 秒一次）──
                    if state == DETECTING and time.ticks_diff(now, _last_poll_time[0]) > POLL_INTERVAL_MS:
                        _last_poll_time[0] = now
                        cmd = http_client.get_command()
                        if cmd == "record":
                            logger.info("Main", "收到后端录音指令")
                            buzzer.beep_twice()
                            state = RECORDING

                    time.sleep_ms(1000)  # 统一限速 1 秒

                elif state == RECORDING:
                    # ── 录音：暂停摄像头释放 DMA ──
                    _sensor_pause(sensor)
                    filepath = voice_capture.record()
                    buzzer.beep()

                    if filepath:
                        state = UPLOADING
                    else:
                        logger.warn("Main", "录音失败，恢复摄像头")
                        _sensor_resume(sensor)
                        detect_task = face_detect.init_detector()
                        _last_detect_time[0] = 0
                        state = DETECTING

                elif state == UPLOADING:
                    # ── 同步上传，完成后恢复摄像头 ──
                    logger.info("Main", "上传语音到后端...")
                    result = http_client.send_voice_file(filepath)
                    if result:
                        logger.info("Main", "上传成功")
                    else:
                        logger.warn("Main", "上传失败")
                    try:
                        os.remove(filepath)
                    except Exception:
                        pass
                    _sensor_resume(sensor)
                    detect_task = face_detect.init_detector()
                    _last_detect_time[0] = 0  # 立即恢复人脸检测
                    logger.info("Main", "上传完成，恢复检测")
                    state = DETECTING

                if frame_count % 100 == 0:
                    logger.info("Main", "帧=" + str(frame_count) + " fps=" + str(clock.fps()) + " 状态=" + str(state))

            except Exception as e:
                logger.error("Main", "主循环异常: " + str(e))
                sys.print_exception(e)
                state = DETECTING
                time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Main", "用户停止")
    except BaseException as e:
        sys.print_exception(e)
        logger.error("Main", "异常: " + str(e))
    finally:
        logger.info("Main", "清理资源...")
        if sensor:
            sensor.stop()
        Display.deinit()
        os.exitpoint(os.EXITPOINT_ENABLE_SLEEP)
        time.sleep_ms(100)
        MediaManager.deinit()
        logger.info("Main", "程序已退出")


if __name__ == "__main__":
    main()
