"""K230 手势识别模块

CanMV v1.4.3 (Yahboom K230) API
使用 nncase_runtime 进行 AI 推理
"""
import time
import nncase_runtime as nn

import http_client
import logger

# ── 手势标签映射 ──────────────────────────────
GESTURE_LABELS = [
    "fist", "one", "two", "three", "four",
    "five", "six", "rock", "ok",
]

GESTURE_CN = {
    "fist": "握拳", "one": "比一", "two": "比二",
    "three": "比三", "four": "比四", "five": "张开手掌",
    "six": "比六", "rock": "摇滚手势", "ok": "OK手势",
}

CONFIDENCE_THRESHOLD = 0.7
REPORT_INTERVAL = 2.0
_last_report_time = 0


def init_detector(model_path="/sdcard/kmodel/gesture.kmodel"):
    """加载手势识别模型。"""
    logger.info("Gesture", "正在加载手势识别模型...")
    kpu = nn.kpu()
    kpu.load_kmodel(model_path)
    logger.info("Gesture", "手势识别模型已加载")
    return kpu


def run_frame(kpu, ai_img):
    """处理一帧图像，做手势识别，上报事件。

    Args:
        kpu: 手势识别 KPU 对象
        ai_img: AI 通道的图像
    """
    global _last_report_time

    try:
        # 将图像转为 numpy 再转为 tensor，设置 KPU 输入
        img_np = ai_img.to_rgb888().to_numpy_ref()
        kpu_input = nn.from_numpy(img_np)
        kpu.set_input_tensor(0, kpu_input)
        logger.debug("Gesture", "KPU 输入已设置")

        kpu.run()
        output = kpu.get_output_tensor(0)
        plist = output.to_numpy().flatten().tolist()
        logger.debug("Gesture", "推理完成, plist长度=" + str(len(plist)))

        if not plist:
            logger.warn("Gesture", "plist 为空")
            return

        max_idx = plist.index(max(plist))
        confidence = plist[max_idx]

        logger.info("Gesture", "最高置信度: " + str(confidence) + " idx=" + str(max_idx))

        if confidence >= CONFIDENCE_THRESHOLD:
            gesture = GESTURE_LABELS[max_idx] if max_idx < len(GESTURE_LABELS) else "unknown"
            cn_name = GESTURE_CN.get(gesture, gesture)

            ai_img.draw_string_advanced(10, 10, 32, "{}: {:.0%}".format(cn_name, confidence),
                                        color=(255, 0, 0))

            now = time.time()
            if now - _last_report_time >= REPORT_INTERVAL:
                _last_report_time = now
                logger.info("Gesture", "准备上报手势: " + gesture + " (" + cn_name + ")")
                http_client.send_event("gesture", {
                    "gesture": gesture,
                    "gesture_cn": cn_name,
                    "confidence": confidence,
                })
            else:
                logger.debug("Gesture", "防抖中, 距离上次上报: " + str(now - _last_report_time) + "s")
        else:
            logger.debug("Gesture", "置信度不够: " + str(confidence) + " < " + str(CONFIDENCE_THRESHOLD))

    except Exception as e:
        logger.error("Gesture", "run_frame 异常: " + str(e))
