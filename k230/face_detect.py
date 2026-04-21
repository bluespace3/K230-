"""K230 人脸检测 + 识别模块

CanMV v1.4.3 (Yahboom K230) API
使用 nncase_runtime 进行 AI 推理，AI2D 做预处理，aidemo 做后处理
"""
import time
import nncase_runtime as nn
import ulab.numpy as np
import aidemo

import http_client
import logger

# ── 模型路径 ───────────────────────────────────
DETECT_MODEL = "/sdcard/kmodel/face_detection_320.kmodel"
RECOG_MODEL = "/sdcard/kmodel/face_recognition.kmodel"

# ── Anchors 路径 ───────────────────────────────
ANCHOR_LEN = 4200
DET_DIM = 4

# ── 人脸库 ────────────────────────────────────
face_db = {}
SIMILARITY_THRESHOLD = 0.75

# ── 预处理相关（模块级缓存）──────────────────
_anchors = None
_ai2d_builder = None
_ai2d_output_tensor = None

# ── 上报状态 ──────────────────────────────────
_last_report_time = 0
_last_face_count = 0
_no_face_count = 0
_face_arrived_flag = False
REPORT_INTERVAL = 10.0
NO_FACE_THRESHOLD = 30

SENSOR_W = 320
SENSOR_H = 240
MODEL_SIZE = 320


def _load_anchors():
    """加载 anchors 数据（后处理必需）。"""
    global _anchors
    if _anchors is not None:
        return _anchors
    paths = [
        "/sdcard/examples/utils/prior_data_320.bin",
        "/sdcard/app/utils/prior_data_320.bin",
        "/sdcard/utils/prior_data_320.bin",
    ]
    for p in paths:
        try:
            _anchors = np.fromfile(p, dtype=np.float)
            _anchors = _anchors.reshape((ANCHOR_LEN, DET_DIM))
            logger.info("Face", "Anchors 已加载: " + p)
            return _anchors
        except Exception as e:
            logger.debug("Face", "尝试 " + p + " 失败: " + str(e))
    logger.warn("Face", "未找到 anchors 文件")
    return None


def _setup_ai2d():
    """配置 AI2D 预处理：把 320x240 resize 到 320x320。"""
    global _ai2d_builder, _ai2d_output_tensor

    ai2d = nn.ai2d()
    ai2d.set_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
    ai2d.set_resize_param(True, nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
    _ai2d_builder = ai2d.build(
        [1, 3, SENSOR_H, SENSOR_W],
        [1, 3, MODEL_SIZE, MODEL_SIZE]
    )

    # 预分配输出缓冲区
    output_np = np.zeros((1, 3, MODEL_SIZE, MODEL_SIZE), dtype=np.uint8)
    _ai2d_output_tensor = nn.from_numpy(output_np)

    logger.info("Face", "AI2D 预处理已配置: " + str(SENSOR_W) + "x" + str(SENSOR_H) + " -> " + str(MODEL_SIZE) + "x" + str(MODEL_SIZE))


def init_detector(model_path=DETECT_MODEL):
    """加载人脸检测模型，返回 KPU 对象。"""
    logger.info("Face", "正在加载人脸检测模型...")
    kpu = nn.kpu()
    kpu.load_kmodel(model_path)
    logger.info("Face", "人脸检测模型已加载")

    _setup_ai2d()
    _load_anchors()

    return kpu


def init_recognizer(model_path=RECOG_MODEL):
    """加载人脸识别（特征提取）模型，返回 KPU 对象。"""
    logger.info("Face", "正在加载人脸识别模型...")
    kpu = nn.kpu()
    kpu.load_kmodel(model_path)
    logger.info("Face", "人脸识别模型已加载")
    return kpu


def register_face(name, feature):
    """注册一个人脸到人脸库。"""
    face_db[name] = feature
    logger.info("Face", "注册人脸: " + name + " (库中共 " + str(len(face_db)) + " 人)")


def _report_if_needed(face_list, now):
    """智能上报：只在人脸数量变化时上报，避免重复请求后端。"""
    global _last_report_time, _last_face_count, _no_face_count

    face_count = len(face_list)

    # 没有人脸：累计帧数，连续消失才上报
    if face_count == 0:
        _no_face_count += 1
        if _no_face_count == NO_FACE_THRESHOLD and _last_face_count > 0:
            _last_face_count = 0
            _no_face_count = 0
            logger.info("Face", "所有人都离开了")
            http_client.send_event("face", {
                "action": "leave",
                "face_count": 0,
            })
        return

    _no_face_count = 0

    # 防抖：距离上次上报不够则跳过
    if now - _last_report_time < REPORT_INTERVAL:
        return

    # 人脸数量没变化且没人脸库注册的人，不上报
    if face_count == _last_face_count and len(face_db) == 0:
        return

    # 上报：人脸数量变化 或 有注册人脸
    _last_report_time = now
    _last_face_count = face_count

    logger.info("Face", "上报事件: face_count=" + str(face_count))
    http_client.send_event("face", {
        "action": "detect",
        "face_count": face_count,
        "registered_count": len(face_db),
    })


def face_just_arrived():
    """检查是否刚检测到新人脸（从0变>0），调用后自动清除。"""
    global _face_arrived_flag
    if _face_arrived_flag:
        _face_arrived_flag = False
        return True
    return False


_frame_count = 0
_DEBUG_LOG_INTERVAL = 200  # 每 200 帧打一次 debug 日志


def run_frame(detect_kpu, ai_img, recog_kpu=None):
    """处理一帧图像，做人脸检测，返回检测到的人脸列表。"""
    global _last_report_time, _face_arrived_flag, _frame_count, _last_face_count
    _frame_count += 1
    verbose = (_frame_count % _DEBUG_LOG_INTERVAL == 0)

    try:
        # 1. 获取传感器图像 numpy（planar CHW 格式）
        img_np = ai_img.to_numpy_ref()
        if verbose:
            logger.debug("Face", "frame=" + str(_frame_count) + " shape=" + str(img_np.shape))

        # 2. AI2D 预处理：resize 到模型输入 320x320
        img_4d = img_np.reshape((1, 3, SENSOR_H, SENSOR_W))
        ai2d_input = nn.from_numpy(img_4d)
        _ai2d_builder.run(ai2d_input, _ai2d_output_tensor)

        # 3. KPU 推理
        detect_kpu.set_input_tensor(0, _ai2d_output_tensor)
        detect_kpu.run()

        # 4. 收集所有输出
        output_count = detect_kpu.outputs_size()
        results = []
        for i in range(output_count):
            t = detect_kpu.get_output_tensor(i)
            results.append(t.to_numpy())

        # 5. 后处理
        if _anchors is not None:
            faces = aidemo.face_det_post_process(
                0.5, 0.2, MODEL_SIZE, _anchors,
                [SENSOR_W, SENSOR_H], results
            )
        else:
            faces = aidemo.face_det_post_process(
                0.5, 0.2, MODEL_SIZE, [],
                [SENSOR_W, SENSOR_H], results
            )

        # 6. 解析结果
        if not faces or len(faces) == 0:
            return []

        face_list = faces[0] if isinstance(faces[0], list) else faces
        if not face_list:
            return []

        # 检测人脸从0变>0，设置标志供主循环使用
        if _last_face_count == 0:
            _face_arrived_flag = True
            _last_face_count = len(face_list)  # 防止下一帧重复触发
            _no_face_count = 0
            logger.info("Face", "新人脸到达!")
            # 立即上报，让后端主动打招呼
            http_client.send_event("face", {
                "action": "arrive",
                "face_count": len(face_list),
            })
            return []

        if verbose:
            logger.debug("Face", "检测到 " + str(len(face_list)) + " 张人脸")

        # 7. 上报逻辑（只在人脸数量变化或新人出现时上报）
        now = time.time()
        _report_if_needed(face_list, now)

        return face_list

    except Exception as e:
        logger.error("Face", "run_frame 异常: " + str(e))
        return []
