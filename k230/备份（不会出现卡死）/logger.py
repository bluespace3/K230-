"""K230 日志模块 - 同时输出到终端和文件（线程安全）"""
import time
import sys
import _thread

LOG_FILE = "/sdcard/aiAssitant/k230.log"

# 日志级别
DEBUG = 0
INFO = 1
WARN = 2
ERROR = 3

_CURRENT_LEVEL = DEBUG  # 默认输出所有级别
_log_lock = _thread.allocate_lock()


def set_level(level):
    global _CURRENT_LEVEL
    _CURRENT_LEVEL = level


def _write_log(level_str, tag, msg):
    # 使用 ticks_ms 作为时间戳（固件不支持 strftime）
    timestamp = str(time.ticks_ms())
    log_line = "[" + timestamp + "] [" + level_str + "] [" + tag + "] " + msg + "\n"

    # 输出到终端
    print(log_line, end="")

    # 写入文件（加锁防止多线程并发写冲突）
    with _log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_line)
        except Exception as e:
            print("[Logger] 写日志文件失败: " + str(e))


def debug(tag, msg):
    if _CURRENT_LEVEL <= DEBUG:
        _write_log("DEBUG", tag, msg)


def info(tag, msg):
    if _CURRENT_LEVEL <= INFO:
        _write_log("INFO", tag, msg)


def warn(tag, msg):
    if _CURRENT_LEVEL <= WARN:
        _write_log("WARN", tag, msg)


def error(tag, msg):
    if _CURRENT_LEVEL <= ERROR:
        _write_log("ERROR", tag, msg)


def clear():
    """清空日志文件"""
    try:
        with open(LOG_FILE, "w") as f:
            f.write("")
        print("[Logger] 日志已清空")
    except Exception as e:
        print("[Logger] 清空日志失败: " + str(e))
