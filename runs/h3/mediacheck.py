#!/usr/bin/env python3
"""mediacheck — 共享图片有效性校验（全异常捕获，永不向外抛异常）。

供 ui_app.py（UI 上传）、upload_watch.py（看门狗扫描）、refimage.py（prune）
共同使用，确保无效图片（过小/损坏/非图片）不进入素材池。
"""
from __future__ import annotations

from pathlib import Path

MIN_IMAGE_BYTES = 1024
MIN_IMAGE_DIM = 32


def check_image_bytes(data: bytes) -> tuple:
    """校验图片字节数据是否有效。返回 (ok: bool, reason: str)。

    检查项：
    1. 字节数 >= MIN_IMAGE_BYTES (1KB)
    2. PIL Image.open + verify（格式合法性）
    3. PIL Image.open + load（强制像素解码，捕获截断/损坏）
    4. 最短边 >= MIN_IMAGE_DIM (32px)

    任何异常均被捕获并返回 (False, 原因描述)，绝不向外抛异常。
    """
    try:
        if len(data) < MIN_IMAGE_BYTES:
            return False, f'过小({len(data)}B)'
        from PIL import Image
        from io import BytesIO
        buf = BytesIO(data)
        im = Image.open(buf)
        im.verify()
        im2 = Image.open(BytesIO(data))
        im2.load()
        if min(im2.size) < MIN_IMAGE_DIM:
            return False, f'尺寸过小({im2.size})'
        return True, ''
    except Exception as e:
        return False, f'无法解码: {type(e).__name__}'


def check_image_file(path) -> tuple:
    """校验图片文件。返回 (ok: bool, reason: str)。"""
    try:
        data = Path(path).read_bytes()
        return check_image_bytes(data)
    except Exception as e:
        return False, f'读取失败: {e}'
