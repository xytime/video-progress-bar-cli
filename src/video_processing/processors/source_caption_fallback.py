"""原字幕外观预检、局部修补质量和整片 B 方案的保守几何边界。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | 实心底板/彩字选择 B；从原片规划全片统一上方或下方避让。 |
"""
from __future__ import annotations

import cv2
import numpy as np


class RepairUnsuitable(ValueError):
    """定位可信，但 A 的外观/修补质量不合格，可以从原片评估 B。"""


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def padded(box, margin=.025):
    return [max(0, box[0]-margin), max(0, box[1]-margin),
            min(1, box[2]+margin), min(1, box[3]+margin)]


def appearance(frame, boxes):
    """亮色底板、反色字和彩色字不能交给白字掩膜；误拒绝时安全进入 B。"""
    h, w = frame.shape[:2]
    for x0, y0, x1, y1 in boxes:
        roi = frame[int(y0*h):int(y1*h)+1, int(x0*w):int(x1*w)+1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        light = (hsv[:, :, 2] > 190) & (hsv[:, :, 1] < 80)
        if np.mean(light) > .48:
            raise RepairUnsuitable('原字幕有亮色实心底板或反色字')
        # 彩色物体也可能被误拒绝，但不能冒险只擦掉彩色字幕中的白色部分。
        colorful = (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 140)
        if np.mean(colorful) > .08:
            raise RepairUnsuitable('原字幕范围含多色字或无法分离的彩色内容')
        region = padded([x0, y0, x1, y1], .04)
        cut = frame[int(region[1]*h):int(region[3]*h)+1, int(region[0]*w):int(region[2]*w)+1]
        gray = cv2.cvtColor(cut, cv2.COLOR_BGR2GRAY)
        # 实心暗底板通常表现为跨越字幕宽度的平直强边；自然边缘误命中也进入 B。
        dy = np.abs(np.diff(gray.astype(float), axis=0))
        if dy.size and np.any(np.mean(dy > 35, axis=1) > .80):
            raise RepairUnsuitable('原字幕附近有实心底板边界或强水平遮挡')


def repair_quality(original, fixed, mask):
    """限制改动面积及不可逆纹理损失；OCR 无残字并不构成视觉合格。"""
    selected = mask > 0
    if not np.any(selected):
        return
    if np.mean(selected) > .035:
        raise RepairUnsuitable('修补面积超过画面的保守上限')
    halo = cv2.dilate(mask, np.ones((5, 5), np.uint8)) > 0
    ring = halo & ~selected
    gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
    texture = np.abs(cv2.Laplacian(gray, cv2.CV_32F))
    if np.any(ring) and np.percentile(texture[ring], 75) > 65:
        raise RepairUnsuitable('原字幕周边纹理复杂，局部修补不能可靠恢复')
    if np.any(original[~selected] != fixed[~selected]):
        raise RepairUnsuitable('修补改动超出字形掩膜')


def fallback_geometry(rows, observations, canvas_height, fps=30):
    """汇总整片原字幕边界和人脸/其它文字；不使用修补后的画面。"""
    boxes = [b for frame in rows for b in frame]
    if not boxes:
        raise ValueError('没有可靠原字幕位置，不能生成 B')
    band = [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]
    # 包含底板上下边距，中文/英文原字幕换行都计入整块高度。
    band = padded(band, .035)
    obstacles = []
    for captions, observation in zip(rows, observations, strict=True):
        obstacles.extend(padded(b, .025) for b in observation['faces'])
        obstacles.extend(padded(r['box'], .012) for r in observation['rows']
                         if r.get('confidence', 1) >= .75
                         and not any(overlap(r['box'], b) for b in captions))
    return {'original_band': band, 'obstacles': obstacles, 'canvas_height': canvas_height,
            'fps': fps, 'frames': [{'captions': c, 'faces': o['faces'],
                'text': [r['box'] for r in o['rows'] if r.get('confidence',1) >= .75
                         and not any(overlap(r['box'], b) for b in c)]}
                for c, o in zip(rows, observations, strict=True)]}


def place_fallback(geometry, height, *, canvas_height, video_y=0, center_x=540, width=940, start=None, end=None, side=None):
    """同一句完整避让；调用者先检验全片上方，再检验全片下方，不逐句混用方向。"""
    band = geometry['original_band']
    obstacles = geometry['obstacles']
    if start is not None and geometry.get('frames'):
        frames = geometry['frames'][int(start*geometry['fps']):max(int(start*geometry['fps'])+1,int(np.ceil(end*geometry['fps']))) ]
        captions = [b for f in frames for b in f['captions']]
        if captions:
            band = padded([min(b[0] for b in captions),min(b[1] for b in captions),
                           max(b[2] for b in captions),max(b[3] for b in captions)],.035)
        obstacles = [padded(b,.025) for f in frames for b in f['faces']]
        obstacles += [padded(b,.012) for f in frames for b in f['text']]
    top_edge = band[1]*canvas_height + video_y
    bottom_edge = band[3]*canvas_height + video_y
    for candidate, top in [('above', top_edge-24-height), ('below', bottom_edge+24)]:
        if side and candidate != side:
            continue
        if top < 350 or top+height > min(1700, video_y+canvas_height):
            continue
        rectangle = [(center_x-width/2)/1080, (top-video_y)/canvas_height,
                     (center_x+width/2)/1080, (top+height-video_y)/canvas_height]
        if any(overlap(rectangle, b) for b in obstacles):
            continue
        return candidate, float(top)
    raise ValueError('B 方案上、下均无法避开原字幕、人脸、其它文字及平台安全边界，需人工处理')


def caption_width(rendered, outline):
    """按 ASS 使用的实际字体估算每句宽度，加 10% 及描边余量；无字体时保守占满安全宽。"""
    import re
    from PIL import ImageFont
    fonts = {'Georgia': '/System/Library/Fonts/Supplemental/Georgia.ttf',
             'Hiragino Sans GB': '/Library/Fonts/Hiragino Sans GB.ttc'}
    name, size, maximum = 'Georgia', rendered.en_size, 0
    try:
        for line in rendered.ass_text.split(r'\N'):
            names = re.findall(r'\\fn([^}\\]+)', line)
            sizes = re.findall(r'\\fs([0-9.]+)', line)
            if names:name=names[-1]
            if sizes:size=float(sizes[-1])
            plain=re.sub(r'\{[^}]*\}', '', line).strip()
            if plain:
                font=ImageFont.truetype(fonts[name],round(size))
                maximum=max(maximum,font.getlength(plain)*1.10+outline*2+12)
    except (OSError, KeyError):
        return 940
    return max(1,maximum)
