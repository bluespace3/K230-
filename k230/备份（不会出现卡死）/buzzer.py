"""K230 蜂鸣器模块

使用 Yahboom 官方 YbBuzzer 库控制板载蜂鸣器。
库位置: /sdcard/ybUtils/YbBuzzer.py
"""
import time
import logger

_buzzer = None


def _get_buzzer():
    """获取或创建蜂鸣器实例。"""
    global _buzzer
    if _buzzer is not None:
        return _buzzer
    try:
        from ybUtils.YbBuzzer import YbBuzzer
        _buzzer = YbBuzzer()
        logger.info("Buzzer", "YbBuzzer 初始化成功")
        return _buzzer
    except Exception as e:
        logger.warn("Buzzer", "YbBuzzer 不可用: " + str(e))
        return None


def beep(duration_ms=150):
    """滴一声。"""
    b = _get_buzzer()
    if b is None:
        return
    try:
        b.on(2000, 50, duration_ms / 1000.0)
        logger.info("Buzzer", "beep " + str(duration_ms) + "ms")
    except Exception as e:
        logger.warn("Buzzer", "beep 失败: " + str(e))


def beep_twice(interval_ms=100, duration_ms=100):
    """滴两声（录音开始提示）。"""
    b = _get_buzzer()
    if b is None:
        return
    try:
        b.on(2000, 50, duration_ms / 1000.0)
        time.sleep_ms(interval_ms)
        b.on(2000, 50, duration_ms / 1000.0)
        logger.info("Buzzer", "beep_twice")
    except Exception as e:
        logger.warn("Buzzer", "beep_twice 失败: " + str(e))


def off():
    """关闭蜂鸣器。"""
    b = _get_buzzer()
    if b:
        try:
            b.off()
        except Exception:
            pass
