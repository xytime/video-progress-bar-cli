"""武器造价对比视频《Cost in Units of RTX 5090.mp4》英文文字转中文全自动高保真渲染脚本

# Modification History
| 1.0.0 | 2026-09-02 | Gemini_3.7_Flash_planning | 初始创建：实现8类武器中英对照、双黑边遮罩重绘、下三分之一羽化暗角合成与60FPS无损压制 |
"""

import os
import sys
import subprocess
import time
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# [Gemini_3.7_Flash_planning] 视频参数与场景时间区间定义
INPUT_VIDEO = "/Volumes/EXT2T/Download_at_EXT2T/Cost in Units of RTX 5090.mp4"
OUTPUT_VIDEO = "/Volumes/EXT2T/Download_at_EXT2T/Cost in Units of RTX 5090_中文版.mp4"

W, H = 1080, 1920
FPS = 60.0

# 8个场景对应的帧区间 (0-indexed, [start_frame, end_frame, price, name_line1, name_line2])
SCENES = [
    (0, 128, "$6,466 / 发", "57 毫米", "“3P” 可编程多用途炮弹"),
    (129, 303, "$27,801 / 发", "120 毫米", "坦克贫铀穿甲弹"),
    (304, 399, "$127,341 / 枚", "“标枪”反坦克导弹", "(Javelin)"),
    (400, 639, "$249,506 / 枚", "JAGM 联合空地导弹", "(Joint Air-to-Ground Missile)"),
    (640, 836, "$903,113 / 枚", "“滚体”近程防空导弹", "(Rolling Airframe Missile)"),
    (837, 1068, "$2,540,615 / 枚", "“战斧”巡航导弹", "Block V 型 (Tomahawk)"),
    (1069, 1304, "$4,395,473 / 枚", "“爱国者”防空导弹", "PAC-3 MSE 型 (Patriot)"),
    (1305, 999999, "$28,686,000 / 枚", "“标准-3”防空反导拦截弹", "Block IIA 型 (SM-3)")
]


def build_overlay_images():
    """生成8个场景的 RGBA 叠加图层"""
    font_path = "/System/Library/Fonts/Hiragino Sans GB.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
    
    font_top = ImageFont.truetype(font_path, 50, index=1)
    font_bot = ImageFont.truetype(font_path, 32, index=1)
    font_price = ImageFont.truetype(font_path, 52, index=1)
    font_w1 = ImageFont.truetype(font_path, 72, index=1)
    font_w2 = ImageFont.truetype(font_path, 48, index=1)

    green_title = (0, 255, 0, 255)
    green_price = (0, 255, 30, 255)

    overlays = []
    for _, _, price, w1, w2 in SCENES:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 1. 顶部纯黑区域遮罩 (y: 0..145)，避开 y=155+ 处的显卡图标与跳动计数器
        draw.rectangle([0, 0, W, 145], fill=(0, 0, 0, 255))
        t1 = "武器单价折合"
        t2 = "RTX 5090 显卡数量："
        w_t1 = draw.textbbox((0, 0), t1, font=font_top)[2] - draw.textbbox((0, 0), t1, font=font_top)[0]
        w_t2 = draw.textbbox((0, 0), t2, font=font_top)[2] - draw.textbbox((0, 0), t2, font=font_top)[0]
        draw.text(((W - w_t1) // 2, 16), t1, fill=green_title, font=font_top, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        draw.text(((W - w_t2) // 2, 76), t2, fill=green_title, font=font_top, stroke_width=2, stroke_fill=(0, 0, 0, 255))

        # 2. 底部纯黑区域遮罩 (y: 1840..1920)
        draw.rectangle([0, 1840, W, 1920], fill=(0, 0, 0, 255))
        bot_text = "RTX 5090 32GB 官方参考价：约 $4,899 (约合 ¥3.55万)"
        w_bot = draw.textbbox((0, 0), bot_text, font=font_bot)[2] - draw.textbbox((0, 0), bot_text, font=font_bot)[0]
        draw.text(((W - w_bot) // 2, 1862), bot_text, fill=(255, 255, 255, 255), font=font_bot)

        # 3. 画面下三分之一平滑羽化暗角遮罩 (y: 1330..1800)
        mask_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        m_draw = ImageDraw.Draw(mask_layer)
        for y in range(1330, 1800):
            if y < 1370:
                alpha = int(255 * (y - 1330) / 40)
            elif y > 1750:
                alpha = int(255 * (1800 - y) / 50)
            else:
                alpha = 255
            m_draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha), width=1)

        img = Image.alpha_composite(img, mask_layer)
        draw = ImageDraw.Draw(img)

        # 渲染绿色价格
        w_p = draw.textbbox((0, 0), price, font=font_price)[2] - draw.textbbox((0, 0), price, font=font_price)[0]
        px = (W - w_p) // 2
        py = 1370
        draw.text((px, py), price, fill=green_price, font=font_price, stroke_width=4, stroke_fill=(0, 0, 0, 255))

        # 渲染武器主名称 (白色大粗体 + 柔和重阴影)
        w_w1 = draw.textbbox((0, 0), w1, font=font_w1)[2] - draw.textbbox((0, 0), w1, font=font_w1)[0]
        w1_x = (W - w_w1) // 2
        w1_y = 1445
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4), (0, -4), (4, 0), (-4, 0), (0, 6)]:
            draw.text((w1_x + dx, w1_y + dy), w1, fill=(0, 0, 0, 240), font=font_w1)
        draw.text((w1_x, w1_y), w1, fill=(255, 255, 255, 255), font=font_w1, stroke_width=3, stroke_fill=(0, 0, 0, 255))

        # 渲染武器副名称/型号
        if w2:
            w_w2 = draw.textbbox((0, 0), w2, font=font_w2)[2] - draw.textbbox((0, 0), w2, font=font_w2)[0]
            w2_x = (W - w_w2) // 2
            w2_y = 1545
            for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, 3), (0, -3), (3, 0), (-3, 0), (0, 5)]:
                draw.text((w2_x + dx, w2_y + dy), w2, fill=(0, 0, 0, 240), font=font_w2)
            draw.text((w2_x, w2_y), w2, fill=(240, 240, 240, 255), font=font_w2, stroke_width=2, stroke_fill=(0, 0, 0, 255))

        # 转换为 NumPy array 以便高效批量合成 (BGR + Alpha)
        np_overlay = np.array(img)
        overlays.append(np_overlay)

    return overlays


def process_video():
    """执行完整的逐帧合成与 FFmpeg 高清转码压制"""
    if not os.path.exists(INPUT_VIDEO):
        print(f"Error: Input video not found at {INPUT_VIDEO}")
        sys.exit(1)

    print(f"Loading input video: {INPUT_VIDEO}")
    cap = cv2.VideoCapture(INPUT_VIDEO)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    print(f"Video info: {W}x{H} @ {fps}fps, Total frames: {total_frames}")

    print("Pre-rendering 8 scene Chinese overlays...")
    raw_overlays = build_overlay_images()

    # 提取各 overlay 的 BGR 与 Alpha 归一化权重
    precomputed = []
    for ov in raw_overlays:
        # ov shape: (H, W, 4) -> RGBA
        bgr = cv2.cvtColor(ov, cv2.COLOR_RGBA2BGR)
        alpha = ov[:, :, 3].astype(np.float32) / 255.0
        alpha_3d = np.dstack([alpha, alpha, alpha])
        precomputed.append((bgr.astype(np.float32), alpha_3d))

    # 启动 FFmpeg 子进程，通过 stdin 接收无损 rawvideo 管道输入
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{W}x{H}",
        "-r", str(fps),
        "-i", "-",  # 视频流从管道读取
        "-i", INPUT_VIDEO,  # 提取原视频音频
        "-map", "0:v:0",
        "-map", "1:a:0?",
        "-c:v", "libx264",
        "-crf", "16",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        OUTPUT_VIDEO
    ]

    print(f"Starting FFmpeg rendering pipeline to: {OUTPUT_VIDEO}")
    proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    start_time = time.time()
    frame_idx = 0
    current_scene_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # 找到当前帧所属的场景
        while current_scene_idx < len(SCENES) - 1 and frame_idx > SCENES[current_scene_idx][1]:
            current_scene_idx += 1

        ov_bgr, alpha_3d = precomputed[current_scene_idx]

        # 快速向量化 Alpha 混合: out = frame * (1 - alpha) + ov * alpha
        # 仅对有遮罩的区域 (y: 0..150, y: 1330..1800, y: 1840..1920) 进行混合加速
        blended = frame.copy()

        # Top mask y: 0..150
        blended[0:150, :] = (
            frame[0:150, :].astype(np.float32) * (1.0 - alpha_3d[0:150, :])
            + ov_bgr[0:150, :] * alpha_3d[0:150, :]
        ).astype(np.uint8)

        # Lower-third mask y: 1330..1800
        blended[1330:1800, :] = (
            frame[1330:1800, :].astype(np.float32) * (1.0 - alpha_3d[1330:1800, :])
            + ov_bgr[1330:1800, :] * alpha_3d[1330:1800, :]
        ).astype(np.uint8)

        # Bottom mask y: 1840:1920
        blended[1840:1920, :] = (
            frame[1840:1920, :].astype(np.float32) * (1.0 - alpha_3d[1840:1920, :])
            + ov_bgr[1840:1920, :] * alpha_3d[1840:1920, :]
        ).astype(np.uint8)

        # 写入 FFmpeg 管道
        proc.stdin.write(blended.tobytes())

        frame_idx += 1
        if frame_idx % 150 == 0 or frame_idx == total_frames:
            elapsed = time.time() - start_time
            fps_proc = frame_idx / max(elapsed, 0.001)
            percent = (frame_idx / total_frames) * 100
            print(f"Render progress: {frame_idx}/{total_frames} ({percent:.1f}%) | Speed: {fps_proc:.1f} fps")

    cap.release()
    proc.stdin.close()
    stderr_out = proc.stderr.read().decode("utf-8", errors="ignore")
    proc.wait()

    if proc.returncode != 0:
        print(f"FFmpeg Error:\n{stderr_out}")
        sys.exit(1)

    elapsed_total = time.time() - start_time
    file_size_mb = os.path.getsize(OUTPUT_VIDEO) / (1024 * 1024)
    print(f"\n✅ Video successfully rendered in {elapsed_total:.2f}s!")
    print(f"Output: {OUTPUT_VIDEO} ({file_size_mb:.2f} MB)")


if __name__ == "__main__":
    process_video()
