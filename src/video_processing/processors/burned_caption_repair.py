"""竖屏硬字幕的逐帧定位、字形修补与原位排版凭证。

自动处理居中、有转录匹配及可分离白色字形的英文原字幕；其它情况停止，不能退回叠字。
Vision 是本机逐帧识别；修补只改字形掩膜，不能保证恢复被遮挡的真实背景。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-21 | Codex | A 方案接入：逐帧识别与保守修补、完整画面、来源及成片摘要门禁。 |
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import json
import logging
from pathlib import Path
import re
import select
import subprocess
import tempfile

import cv2
import imageio_ffmpeg
import numpy as np

from ..utils.render_source_binding import digest

VERSION = "in-place-captions-v1"
VISION = Path(__file__).parents[1] / "utils/caption_vision.js"
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedCaptions:
    video: Path
    center_y: float | None
    source_hash: str
    plan: Path
    anchors: tuple = ()


def _write(path, value):
    temporary = path.with_suffix(path.suffix + ".pending")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _probe(path):
    from ..utils.video_metadata import _resolve_ffprobe_cmd
    result = subprocess.run([_resolve_ffprobe_cmd(), "-v", "error", "-select_streams", "v:0", "-show_streams",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True, timeout=30)
    stream = json.loads(result.stdout)["streams"][0]
    def rate(value):
        a, b = value.split("/")
        return float(a) / float(b)
    fps = rate(stream["avg_frame_rate"])
    if (fps <= 0 or abs(fps - rate(stream["r_frame_rate"])) > .001
            or abs(float(stream.get("start_time", 0))) > .001
            or any(s.get("rotation", 0) for s in stream.get("side_data_list", []))):
        raise ValueError("原位字幕修补需要零起点、无旋转的恒定帧率源；请先规范化素材")
    return int(stream["width"]), int(stream["height"]), fps, float(stream["duration"])


@contextmanager
def _vision():
    # 错误流落本地临时文件，防止管道写满；所有请求都只有当前帧 PNG。
    with tempfile.TemporaryFile() as errors:
        worker = subprocess.Popen(["/usr/bin/osascript", "-l", "JavaScript", str(VISION)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=errors)
        try:
            yield worker
        finally:
            worker.stdin.close()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=5)
            worker.stdout.close()


def _recognize(worker, frame):
    ok, png = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("原字幕定位帧编码失败")
    worker.stdin.write(base64.b64encode(png) + b"\n")
    worker.stdin.flush()
    if not select.select([worker.stdout], [], [], 60)[0]:
        raise ValueError("原字幕逐帧定位超时，停止出片")
    result = json.loads(worker.stdout.readline())
    if "rows" not in result:
        raise ValueError("本地 Vision 无法定位原字幕，停止出片")
    return result["rows"]


def _words(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def _locate(source, segments, directory, fps, progress):
    capture = cv2.VideoCapture(str(source))
    frames = []
    try:
        with _vision() as worker:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                rows = _recognize(worker, frame)
                # 所有识别结果保留审计；下半画面是此次原位字幕处理范围。
                frames.append(rows)
                if len(frames) % max(1, round(fps * 5)) == 0:
                    LOG.info("[SourceCaptionScan] 已定位 %s 帧", len(frames))
                    if progress:
                        progress("VIDEO_RENDERING")
    finally:
        capture.release()
    if not frames:
        raise ValueError("无法完整解码原片")
    _write(directory / "ocr.json", {"version": VERSION, "frames": frames})
    return _classify(frames, segments, fps)


def _classify(frames, segments, fps):
    # 画面中央的疑似字幕必须有临近转录证据；不能仅凭整段文字没变就当台标放过。
    selected, boxes = [], []
    for index, rows in enumerate(frames):
        now = index / fps
        local_words = set().union(*(_words(s.get("text", "")) for s in segments
            if s["start"] - 5 <= now <= s["end"] + 5))
        local_text = ''.join(re.findall('[a-z]+', ' '.join(s.get('text', '').lower() for s in segments
            if s['start'] - 5 <= now <= s['end'] + 5)))
        chosen = []
        for row in rows:
            text, box = row["text"], row["box"]
            # 只处理画面中央的原字幕，保留边缘台标、姓名条和顶部标题。
            if not (.38 <= box[1] < box[3] <= .94 and .4 <= (box[0]+box[2])/2 <= .6):
                continue
            tokens = _words(text)
            if not any(c.isalnum() for c in text):
                continue
            matches = bool(tokens) and len(tokens & local_words) / len(tokens) >= .5
            compact = ''.join(re.findall('[a-z]+', text.lower()))
            if len(compact) >= 5:
                matches = matches or SequenceMatcher(None, compact, local_text, autojunk=False).find_longest_match().size / len(compact) >= .8
            if row["confidence"] < .75 or not matches:
                raise ValueError(f"原字幕位置或文字不确定，停止出片：{text[:60]}")
            if box[3] - box[1] > .08 or box[2] - box[0] > .94:
                raise ValueError("原字幕字形范围超出可安全修补边界")
            chosen.append(box)
            boxes.append(box)
        if chosen and max(b[3] for b in chosen) - min(b[1] for b in chosen) > .18:
            raise ValueError('同帧存在多处疑似原字幕，需单独审查')
        selected.append(chosen)
    if not boxes:
        return selected, None
    top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
    return selected, (top + bottom) / 2


def _anchors(rows, fps):
    """把相邻字幕位置聚成时间区间；无字帧沿用最近位置，不新增显示区域。"""
    located = [(i/fps, (min(b[1] for b in boxes)+max(b[3] for b in boxes))/2)
               for i, boxes in enumerate(rows) if boxes]
    if not located:
        return ()
    groups = [[located[0]]]
    for point in located[1:]:
        if abs(point[1] - np.median([p[1] for p in groups[-1]])) > .10:
            groups.append([])
        groups[-1].append(point)
    return tuple((0 if i == 0 else group[0][0], float(np.median([p[1] for p in group])))
                 for i, group in enumerate(groups))


def caption_spans(prepared, start, end):
    anchors = prepared.anchors or ((0, prepared.center_y),)
    cuts = [start, *(t for t, _ in anchors if start < t < end), end]
    return [(a, b, next(y for t, y in reversed(anchors) if t <= a)) for a, b in zip(cuts, cuts[1:])]


def _mask(frame, boxes):
    h, w = frame.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    for box in boxes:
        pad = max(3, round(w / 120))
        x0, y0 = max(0, int(box[0]*w)-pad), max(0, int(box[1]*h)-pad)
        x1, y1 = min(w, int(box[2]*w)+pad+1), min(h, int(box[3]*h)+pad+1)
        roi = frame[y0:y1, x0:x1]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        # 局部亮度突起保留细白字，避免把浅色衬衣等平滑背景整体当字擦除。
        contrast = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad*2+1, pad*2+1)))
        glyph = ((gray > 190) & (hsv[:, :, 1] < 80) & (contrast > 25)).astype(np.uint8)*255
        count, labels, stats, _ = cv2.connectedComponentsWithStats(glyph)
        selected = np.zeros_like(glyph)
        for i in range(1, count):
            _, _, cw, ch, area = stats[i]
            if 2 <= ch <= roi.shape[0] and 1 <= cw <= w*.12 and 2 <= area <= w*h*.003:
                selected[labels == i] = 255
        ratio = np.count_nonzero(selected) / selected.size
        if not .015 <= ratio <= .45:
            raise ValueError("原字幕白色字形无法与背景可靠分离，停止出片")
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (pad*2+1, pad*2+1))
        mask[y0:y1, x0:x1] |= cv2.dilate(selected, kernel)
    return mask


def _residual_text(rows, boxes):
    """邻近书封的大识别框边缘轻触字幕框，不算修补区域内的残字。"""
    for row in rows:
        b = row['box']
        area = max(1e-12, (b[2]-b[0]) * (b[3]-b[1]))
        cx, cy = (b[0]+b[2])/2, (b[1]+b[3])/2
        for old in boxes:
            overlap = max(0, min(b[2], old[2])-max(b[0], old[0])) * max(0, min(b[3], old[3])-max(b[1], old[1]))
            if old[0] <= cx <= old[2] and old[1] <= cy <= old[3] or overlap / area >= .25:
                return True
    return False


def prepare_source(source: Path, segments: list[dict], progress=None) -> PreparedCaptions:
    """逐帧扫描全片；中途失败不返回原片，避免调用者静默叠加两套字幕。"""
    source = Path(source)
    w, h, fps, duration = _probe(source)
    source_hash = digest(source)
    identity = {"version": VERSION, "source_sha256": source_hash, "vision_sha256": digest(VISION),
                "implementation_sha256": digest(Path(__file__)),
                "segments_sha256": hashlib.sha256(json.dumps(segments, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    directory = source.parent / ".caption-repair" / hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    directory.mkdir(parents=True, exist_ok=True)
    plan = directory / "plan.json"
    if plan.is_file():
        data = json.loads(plan.read_text())
        cleaned = directory / "clean.mp4" if data["center_y"] is not None else source
        if data["identity"] == identity and digest(cleaned) == data["clean_sha256"]:
            return PreparedCaptions(cleaned, data["center_y"], source_hash, plan, tuple(map(tuple, data.get('anchors', []))))
    # 横屏既有布局不在本次 A 方案范围；不改变英语精读卡片模板。
    if w >= h:
        return PreparedCaptions(source, None, source_hash, plan)
    rows, center = _locate(source, segments, directory, fps, progress)
    if digest(source) != source_hash:
        raise ValueError("扫描期间源片发生变更")
    expected = round(duration * fps)
    if abs(len(rows) - expected) > 1:
        raise ValueError("原字幕扫描未覆盖完整时长")
    cleaned = source
    if center is not None:
        silent, pending = directory / "silent.mp4", directory / "clean.pending.mp4"
        encoder = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
            "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-pix_fmt", "yuv420p", str(silent)], stdin=subprocess.PIPE)
        capture = cv2.VideoCapture(str(source))
        try:
            with _vision() as verifier:
                for index, boxes in enumerate(rows):
                    ok, frame = capture.read()
                    if not ok:
                        raise ValueError("修补时源片提前结束")
                    mask = _mask(frame, boxes)
                    fixed = cv2.inpaint(frame, mask, max(2, round(w/90)), cv2.INPAINT_TELEA) if boxes else frame
                    if boxes:
                        remaining = _recognize(verifier, fixed)
                        if _residual_text(remaining, boxes):
                            raise ValueError(f"第 {index} 帧修补后原字幕位置仍可识别出文字，停止出片")
                    encoder.stdin.write(fixed.tobytes())
                    if (index+1) % max(1, round(fps*5)) == 0:
                        LOG.info('[SourceCaptionRepair] 已修补并复核 %s 帧', index+1)
                        if progress:
                            progress('VIDEO_RENDERING')
            encoder.stdin.close()
            if encoder.wait(timeout=120) != 0:
                raise ValueError("原字幕修补编码失败")
        finally:
            capture.release()
            if not encoder.stdin.closed:
                encoder.stdin.close()
            if encoder.poll() is None:
                encoder.terminate()
                try:
                    encoder.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    encoder.kill()
                    encoder.wait(timeout=5)
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(silent),
            "-i", str(source), "-map", "0:v:0", "-map", "1:a?", "-c", "copy", "-movflags", "+faststart", str(pending)], check=True, timeout=120)
        cleaned = directory / "clean.mp4"
        pending.replace(cleaned)
        silent.unlink()
    if identity['implementation_sha256'] != digest(Path(__file__)) or identity['vision_sha256'] != digest(VISION):
        raise ValueError('处理期间字幕实现发生变化，不能签发处理计划')
    anchors = _anchors(rows, fps)
    _write(plan, {"identity": identity, "center_y": center, "anchors": anchors, "frames": len(rows), "fps": fps,
                  "canvas": [w, h], "crop": False, "extra_subtitle_panel": False, "clean_sha256": digest(cleaned)})
    return PreparedCaptions(cleaned, center, source_hash, plan, anchors)


def seal_render(output: Path, source: Path, ass: Path, prepared: PreparedCaptions):
    if digest(source) != prepared.source_hash:
        raise ValueError("渲染期间源片变更，不能签发原位字幕凭证")
    _write(output.with_suffix(".captions.json"), {"version": VERSION, "source_sha256": digest(source),
        "output_sha256": digest(output), "ass_sha256": digest(ass), "plan": str(prepared.plan.resolve()),
        "plan_sha256": digest(prepared.plan), "implementation_sha256": digest(Path(__file__)),
        "renderer_sha256": digest(Path(__file__).with_name('vertical_processor.py')), "vision_sha256": digest(VISION)})


def render_receipt_matches(output: Path, source: Path) -> bool:
    try:
        w, h, _, _ = _probe(source)
        if w >= h:
            return True
        data = json.loads(output.with_suffix(".captions.json").read_text())
        return (data["version"] == VERSION and data["source_sha256"] == digest(source)
            and data["output_sha256"] == digest(output) and data["ass_sha256"] == digest(source.with_suffix(".ass"))
            and data["plan_sha256"] == digest(Path(data["plan"]))
            and data['renderer_sha256'] == digest(Path(__file__).with_name('vertical_processor.py'))
            and data["implementation_sha256"] == digest(Path(__file__)) and data["vision_sha256"] == digest(VISION))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False
