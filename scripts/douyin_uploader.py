"""抖音创作者中心浏览器上传器。

当前文件只提供登录态保存、页面校准快照和安全返回码骨架。抖音发布页尚未在
真实账号下完成控件校准前，任何 `--publish` 或 `--verify-only` 都会 fail-closed，
避免页面改版或选择器误判时触发真实发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-23 | Codex | 新增抖音创作者中心登录、校准快照与未校准发布保护骨架 |
| 1.1.0 | 2026-07-23 | Codex | 基于已登录发布页校准唯一视频输入控件，新增仅上传采集表单模式 |
| 1.1.1 | 2026-07-23 | Codex | 上传校准期间页面关闭时返回未确认，避免堆栈冒泡误导调度器 |
| 1.1.2 | 2026-07-23 | Codex | 上传后出现标题/发布设置表单即采集，避免静态进度文案导致空等 |
| 1.2.0 | 2026-07-23 | Codex | 新增标题与描述填充校准，停在提交前页面，最终发布继续保持锁定 |
| 1.3.0 | 2026-07-23 | Codex | 新增显式发布动作，提交后以审核中状态返回，等待作品管理回查校准 |
| 1.3.1 | 2026-07-23 | Codex | 发布后等待作品上传中弹窗结束，并用当前标题/文案标识防止误读旧作品状态 |
| 1.4.0 | 2026-07-25 | Gemini_3.6_Flash_planning | 重构 apply_cover 解耦与文件输入直注，增加通用 DOM 助手 |
| 1.5.0 | 2026-07-26 | Codex | 迁移快手封面经验：生成抖音 9:16 封面副本，封面预览哈希不匹配时阻断发布 |
| 1.5.1 | 2026-07-26 | Codex | 按抖音竖封面 3:4 预览口径生成 1080x1440 安全封面副本 |
| 1.5.2 | 2026-07-26 | Codex | 抖音封面 input 优先选择当前上传区，跳过旧隐藏图片 input |
| 1.5.3 | 2026-07-26 | Codex | 抖音封面副本改为 PNG，规避前端 JPEG 格式校验误拒 |
| 1.5.4 | 2026-07-26 | Codex | 抖音封面优先通过可见上传区 file chooser 选择文件，隐藏 input 仅作兜底 |
| 1.5.5 | 2026-07-26 | Codex | 上传封面后按视觉哈希选择新候选缩略图，再保存封面 |
| 1.5.6 | 2026-07-26 | Codex | 收窄 file chooser 上传区域，避免误点左侧生成参考图上传入口 |
| 1.5.7 | 2026-07-26 | Codex | 使用封面编辑器中心预览截图裁剪做哈希校验，避免 DOM 图片选择器取错图 |
| 1.5.8 | 2026-07-26 | Codex | 通过截图中的青色选中边框定位封面预览区域，提升抖音预览哈希稳定性 |
| 1.5.9 | 2026-07-26 | Codex | 补齐抖音横封面 4:3 上传链路，横竖任一封面不可确认即阻断发布 |
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


logger = logging.getLogger("douyin_uploader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
DOUYIN_VIDEO_INPUT_SELECTOR = 'input[type="file"]'
DOUYIN_TITLE_SELECTOR = 'input[placeholder*="作品标题"]'
DOUYIN_DESCRIPTION_SELECTOR = '[contenteditable="true"]'
DOUYIN_COVER_TARGET_WIDTH = 1080
DOUYIN_COVER_TARGET_HEIGHT = 1440
DOUYIN_HORIZONTAL_COVER_TARGET_WIDTH = 1280
DOUYIN_HORIZONTAL_COVER_TARGET_HEIGHT = 960
DOUYIN_COVER_HASH_SIZE = 16
DOUYIN_COVER_PREVIEW_MAX_HASH_DISTANCE = 40
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOGIN_REQUIRED = 2
EXIT_UNCONFIRMED = 3
EXIT_NOT_CALIBRATED = 4
EXIT_UPLOADED_FOR_CALIBRATION = 5
EXIT_UNDER_REVIEW = 6


def is_creator_center_url(url: str) -> bool:
    """仅把抖音创作者中心域名视为候选登录状态，最终仍要结合页面文本判断。"""
    parsed = urlparse(url or "")
    return parsed.netloc.endswith("creator.douyin.com")


def is_login_required(url: str, visible_text: str = "", frame_urls: Iterable[str] = ()) -> bool:
    """综合 URL、页面和 iframe 证据判断是否需要登录。"""
    candidates = [url or "", *frame_urls]
    if any("passport.douyin.com" in item or "sso.douyin.com" in item or "/login" in item for item in candidates):
        return True
    compact = " ".join((visible_text or "").split())
    return "登录" in compact and ("抖音创作者" in compact or "扫码" in compact or "手机号" in compact)


def get_page_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return ""


def capture_controls(page, artifact_dir: Path, artifact_name: str) -> None:
    """采集页面控件契约，供下一轮根据真实 DOM 补充选择器。"""
    controls = page.locator(
        'input, textarea, button, [contenteditable="true"], [role="button"]'
    ).evaluate_all(
        """elements => elements.map(element => ({
            tag: element.tagName.toLowerCase(),
            id: element.getAttribute('id'),
            type: element.getAttribute('type'),
            accept: element.getAttribute('accept'),
            name: element.getAttribute('name'),
            placeholder: element.getAttribute('placeholder'),
            ariaLabel: element.getAttribute('aria-label'),
            title: element.getAttribute('title'),
            dataE2e: element.getAttribute('data-e2e') || element.getAttribute('data-testid'),
            src: element.getAttribute('src'),
            role: element.getAttribute('role'),
            contentEditable: element.getAttribute('contenteditable'),
            className: String(element.className || '').slice(0, 160),
            text: (element.textContent || '').trim().slice(0, 80),
            parentText: (element.parentElement?.textContent || '').trim().slice(0, 120),
            rect: (() => {
                const rect = element.getBoundingClientRect();
                return {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                };
            })(),
            disabled: Boolean(element.disabled),
        }))"""
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"{artifact_name}_controls.json").write_text(
        json.dumps(controls, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        page.screenshot(path=str(artifact_dir / f"{artifact_name}.png"), full_page=True)
    except Exception as exc:
        logger.warning("保存抖音页面截图失败: %s", exc)


def get_video_upload_input(page, *, log_unexpected: bool = True):
    """返回已校准的唯一视频文件输入控件；页面变化时拒绝猜测。"""
    locator = page.locator(DOUYIN_VIDEO_INPUT_SELECTOR)
    count = locator.count()
    if count != 1:
        if log_unexpected:
            logger.error("抖音视频文件输入控件数量异常，期望 1，实际 %s", count)
        return None
    return locator


def get_title_input(page):
    """返回实测的作品标题输入框；不可唯一确认时拒绝填写。"""
    title_input = page.locator(DOUYIN_TITLE_SELECTOR)
    count = title_input.count()
    if count != 1:
        logger.error("抖音作品标题输入框数量异常，期望 1，实际 %s", count)
        return None
    return title_input


def get_description_editor(page):
    """返回实测的作品描述编辑器；不可唯一确认时拒绝填写。"""
    editor = page.locator(DOUYIN_DESCRIPTION_SELECTOR)
    count = editor.count()
    if count != 1:
        logger.error("抖音作品描述编辑器数量异常，期望 1，实际 %s", count)
        return None
    return editor


def wait_for_video_upload_input(page, timeout_seconds: int = 15):
    """等待抖音 SPA 渲染出唯一视频上传控件。"""
    for _ in range(timeout_seconds):
        upload_input = get_video_upload_input(page, log_unexpected=False)
        if upload_input:
            return upload_input
        page.wait_for_timeout(1_000)
    return get_video_upload_input(page)


def is_upload_in_progress(page) -> bool:
    """页面仍展示上传/处理进度时，绝不能把文件当作已上传完成。"""
    if has_post_upload_form(page):
        return False
    try:
        visible_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return True
    progress_words = ("上传中", "上传进度", "视频处理中", "转码中", "处理中")
    return any(word in visible_text for word in progress_words) or "%" in visible_text


def has_post_upload_form(page) -> bool:
    """上传后表单出现时即可采集控件；不需要继续等待静态上传文案消失。"""
    try:
        controls = page.locator('input, textarea, button, [contenteditable="true"], [role="button"]').evaluate_all(
            """elements => elements.map(element => ({
                tag: element.tagName.toLowerCase(),
                type: element.getAttribute('type') || '',
                placeholder: element.getAttribute('placeholder') || '',
                text: (element.textContent || '').trim(),
                contentEditable: element.getAttribute('contenteditable') || '',
            })).slice(0, 120)"""
        )
    except Exception:
        return False
    for control in controls:
        text = f"{control.get('placeholder', '')} {control.get('text', '')}"
        if any(marker in text for marker in ("标题", "作品描述", "简介", "发布", "定时发布", "发布设置")):
            return True
    return False


def wait_for_upload_completion(page, timeout_seconds: int = 900) -> bool:
    """等待抖音文件传输和初步处理完成；超时交给调用方标记 UNCERTAIN。"""
    try:
        for elapsed in range(timeout_seconds):
            if not is_upload_in_progress(page):
                return True
            if elapsed and elapsed % 30 == 0:
                logger.info("抖音文件仍在上传或处理，已等待 %s 秒", elapsed)
            page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.error("抖音上传校准期间页面已关闭或不可用: %s", exc)
        return False
    return False


def upload_for_calibration(
    page,
    video_path: str,
    artifact_dir: Path,
    *,
    upload_wait_seconds: int = 900,
    title_text: Optional[str] = None,
    description_text: Optional[str] = None,
    cover_path: Optional[str] = None,
) -> bool:
    """只上传一个已授权视频并保存表单结构；不填写、不保存草稿、不发布。"""
    upload_input = get_video_upload_input(page)
    if not upload_input:
        return False
    try:
        upload_input.set_input_files(str(Path(video_path).resolve()))
        page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.error("抖音视频文件绑定失败或页面已关闭: %s", exc)
        return False
    if not wait_for_upload_completion(page, timeout_seconds=upload_wait_seconds):
        logger.error("抖音文件上传在 %s 秒内无法确认完成", upload_wait_seconds)
        return False
    capture_controls(page, artifact_dir, "douyin_post_upload")
    if title_text is not None or description_text is not None or cover_path is not None:
        if not fill_publish_fields(page, title_text or "", description_text or "", artifact_dir, cover_path=cover_path):
            return False
    logger.info("已上传文件并保存抖音上传后表单控件；未保存草稿、未发布")
    return True


def _sha256_file(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_cover_upload_file(
    cover_path: str,
    *,
    target_width: int,
    target_height: int,
    suffix: str,
) -> Optional[str]:
    """按指定宽高生成安全封面副本；原始封面不改动。"""
    source = Path(cover_path)
    if not source.is_file():
        logger.error("抖音封面文件不存在: %s", cover_path)
        return None
    try:
        from PIL import Image, ImageEnhance, ImageFilter

        image = Image.open(source).convert("RGB")
        width, height = image.size
        if width == target_width and height == target_height:
            return str(source.resolve())
        background_scale = max(target_width / width, target_height / height)
        background_size = (round(width * background_scale), round(height * background_scale))
        background = image.resize(background_size, Image.Resampling.LANCZOS)
        left = (background.width - target_width) // 2
        top = (background.height - target_height) // 2
        background = background.crop((left, top, left + target_width, top + target_height))
        background = ImageEnhance.Brightness(background.filter(ImageFilter.GaussianBlur(18))).enhance(0.45)

        foreground_scale = min(target_width / width, target_height / height)
        foreground_size = (round(width * foreground_scale), round(height * foreground_scale))
        foreground = image.resize(foreground_size, Image.Resampling.LANCZOS)
        paste_at = (
            (target_width - foreground.width) // 2,
            (target_height - foreground.height) // 2,
        )
        background.paste(foreground, paste_at)
        target = source.with_name(f"{source.stem}_{suffix}.png")
        background.save(target, format="PNG")
        logger.info(
            "已生成抖音专用封面副本: %s (%sx%s -> %sx%s)",
            target,
            width,
            height,
            target_width,
            target_height,
        )
        return str(target.resolve())
    except Exception as exc:
        logger.error("生成抖音专用封面副本失败: %s", exc)
        return None


def prepare_douyin_cover_upload_file(cover_path: str) -> Optional[str]:
    """生成抖音竖封面 3:4 安全副本；原始封面不改动。"""
    return _prepare_cover_upload_file(
        cover_path,
        target_width=DOUYIN_COVER_TARGET_WIDTH,
        target_height=DOUYIN_COVER_TARGET_HEIGHT,
        suffix="douyin",
    )


def prepare_douyin_horizontal_cover_upload_file(cover_path: str) -> Optional[str]:
    """生成抖音横封面 4:3 安全副本；原始封面不改动。"""
    return _prepare_cover_upload_file(
        cover_path,
        target_width=DOUYIN_HORIZONTAL_COVER_TARGET_WIDTH,
        target_height=DOUYIN_HORIZONTAL_COVER_TARGET_HEIGHT,
        suffix="douyin_horizontal",
    )


def _average_hash_for_image(path: Path, *, size: int = DOUYIN_COVER_HASH_SIZE) -> Optional[str]:
    try:
        from PIL import Image

        image = Image.open(path).convert("L").resize((size, size))
        pixels = list(image.getdata())
    except Exception as exc:
        logger.debug("计算图片视觉哈希失败: %s", exc)
        return None
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _average_hash_for_image_object(image, *, size: int = DOUYIN_COVER_HASH_SIZE) -> str:
    gray = image.convert("L").resize((size, size))
    pixels = list(gray.getdata())
    average = sum(pixels) / len(pixels)
    bits = "".join("1" if pixel >= average else "0" for pixel in pixels)
    return f"{int(bits, 2):016x}"


def _hash_distance(left: Optional[str], right: Optional[str]) -> Optional[int]:
    if not left or not right:
        return None
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return None


def capture_cover_evidence(page, artifact_dir: Path, artifact_name: str, cover_path: Optional[str] = None) -> None:
    """采集抖音封面相关 DOM、图片预览和本地封面指纹。"""
    try:
        evidence = page.evaluate(
            """() => {
                const pick = selector => Array.from(document.querySelectorAll(selector)).slice(0, 120).map(element => {
                    const rect = element.getBoundingClientRect();
                    return {
                        tag: element.tagName.toLowerCase(),
                        type: element.getAttribute('type'),
                        accept: element.getAttribute('accept'),
                        role: element.getAttribute('role'),
                        ariaLabel: element.getAttribute('aria-label'),
                        title: element.getAttribute('title'),
                        dataE2e: element.getAttribute('data-e2e') || element.getAttribute('data-testid'),
                        className: String(element.className || '').slice(0, 180),
                        text: (element.innerText || element.textContent || '').trim().slice(0, 200),
                        parentText: (element.parentElement?.innerText || element.parentElement?.textContent || '').trim().slice(0, 220),
                        src: element.getAttribute('src'),
                        disabled: Boolean(element.disabled),
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                    };
                });
                return {
                    url: location.href,
                    title: document.title,
                    bodyTextPreview: (document.body?.innerText || '').slice(0, 3000),
                    coverTextElements: pick('button, [role="button"], [class*="cover"], [class*="Cover"], [class*="upload"], [class*="Upload"]'),
                    fileInputs: pick('input[type="file"]'),
                    visibleImages: pick('img').filter(item => item.rect.width > 20 && item.rect.height > 20),
                };
            }"""
        )
    except Exception as exc:
        evidence = {"error": str(exc), "url": getattr(page, "url", "")}
    evidence["localCover"] = {
        "path": str(Path(cover_path).resolve()) if cover_path else None,
        "sha256": _sha256_file(cover_path),
        "ahash": _average_hash_for_image(Path(cover_path)) if cover_path else None,
    }
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / f"{artifact_name}.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        page.screenshot(path=str(artifact_dir / f"{artifact_name}.png"), full_page=True)
    except Exception as exc:
        logger.warning("保存抖音封面证据截图失败: %s", exc)

def _find_visible_element(scope, selectors: Iterable[str], timeout_ms: int = 1000):
    """从候选选择器列表中依次定位第一个可切且可见的元素。"""
    for sel in selectors:
        try:
            el = scope.locator(sel).first
            if el.is_visible(timeout=timeout_ms) is True:
                return el
        except Exception:
            continue
    return None


def _find_active_modal(page, selectors: Iterable[str]):
    """查找当前页面上第一个可见的 Modal 遮罩，未找到则回退至主 page。"""
    for sel in selectors:
        try:
            locators = page.locator(sel)
            for i in range(locators.count()):
                cand = locators.nth(i)
                if cand.is_visible() is True:
                    return cand
        except Exception:
            continue
    return page


def _get_file_accept(file_input) -> str:
    try:
        accept = file_input.get_attribute("accept") or ""
    except Exception:
        return ""
    return accept if isinstance(accept, str) else ""


def _get_parent_text(file_input) -> str:
    try:
        parent_text = file_input.evaluate(
            "element => (element.parentElement?.innerText || element.parentElement?.textContent || '').trim()"
        )
    except Exception:
        return ""
    return parent_text if isinstance(parent_text, str) else ""


def _get_class_name(file_input) -> str:
    try:
        class_name = file_input.get_attribute("class") or ""
    except Exception:
        return ""
    return class_name if isinstance(class_name, str) else ""


def _is_cover_file_input_candidate(file_input) -> bool:
    """只允许图片 input，避免把封面塞到视频重传 input。"""
    accept = _get_file_accept(file_input).lower()
    if "video" in accept or "mp4" in accept or "mov" in accept:
        return False
    return any(marker in accept for marker in ("image", "jpg", "jpeg", "png", "webp", "bmp"))


def _cover_file_input_score(file_input) -> int:
    parent_text = _get_parent_text(file_input)
    class_name = _get_class_name(file_input)
    score = 0
    if "点击上传文件" in parent_text or "拖拽文件" in parent_text:
        score += 100
    if "上传封面" in parent_text:
        score += 40
    if "semi-upload-hidden-input" in class_name:
        score += 20
    if "replace" in class_name:
        score += 5
    if "upload-btn-input" in class_name and not parent_text:
        score -= 30
    return score


def _get_douyin_cover_preview_hash(page) -> Optional[str]:
    try:
        from io import BytesIO
        from PIL import Image

        screenshot = page.screenshot(full_page=True)
        image = Image.open(BytesIO(screenshot)).convert("RGB")
        pixels = image.load()
        xs: list[int] = []
        ys: list[int] = []
        for y in range(100, min(image.height, 700)):
            for x in range(250, min(image.width, 980)):
                red, green, blue = pixels[x, y]
                if red < 40 and green > 140 and blue > 150:
                    xs.append(x)
                    ys.append(y)
        if xs and ys:
            left, right = min(xs), max(xs)
            top, bottom = min(ys), max(ys)
            if right - left > 120 and bottom - top > 160:
                crop = image.crop((left + 3, top + 3, right - 3, bottom - 3))
                return _average_hash_for_image_object(crop)

        rect = page.evaluate(
            """() => {
                const candidates = Array.from(document.querySelectorAll('*')).map(element => {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    return {
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                        text: (element.innerText || element.textContent || '').trim().slice(0, 80),
                        className: String(element.className || ''),
                        visible: rect.width > 120 && rect.height > 160
                            && style.visibility !== 'hidden'
                            && style.display !== 'none',
                    };
                }).filter(item => item.visible && item.x > 300 && item.x < 900 && item.y > 120 && item.y < 620);
                candidates.sort((left, right) => (right.width * right.height) - (left.width * left.height));
                const target = candidates.find(item => item.width / item.height > 0.6 && item.width / item.height < 0.9)
                    || candidates[0];
                if (!target) return null;
                return {
                    x: Math.round(target.x),
                    y: Math.round(target.y),
                    width: Math.round(target.width),
                    height: Math.round(target.height),
                };
            }"""
        )
        if rect and rect.get("width", 0) > 0 and rect.get("height", 0) > 0:
            crop = image.crop(
                (
                    rect["x"],
                    rect["y"],
                    rect["x"] + rect["width"],
                    rect["y"] + rect["height"],
                )
            )
            return _average_hash_for_image_object(crop)
    except Exception as exc:
        logger.debug("读取抖音封面预览截图哈希失败: %s", exc)

    try:
        return page.evaluate(
            """() => {
                const images = Array.from(document.querySelectorAll("[class*='cover'] img, [class*='Cover'] img, img[src^='blob:']"));
                const image = images.find(img => {
                    const rect = img.getBoundingClientRect();
                    const style = getComputedStyle(img);
                    return rect.width > 20 && rect.height > 20 && style.visibility !== 'hidden' && style.display !== 'none';
                });
                if (!image || !image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) return null;
                const canvas = document.createElement('canvas');
                canvas.width = 16;
                canvas.height = 16;
                const context = canvas.getContext('2d', { willReadFrequently: true });
                context.drawImage(image, 0, 0, 16, 16);
                const pixels = context.getImageData(0, 0, 16, 16).data;
                let values = [];
                for (let i = 0; i < pixels.length; i += 4) {
                    values.push(Math.round(0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2]));
                }
                const average = values.reduce((sum, value) => sum + value, 0) / values.length;
                let bits = '';
                for (const value of values) bits += value >= average ? '1' : '0';
                return BigInt('0b' + bits).toString(16).padStart(16, '0');
            }"""
        )
    except Exception as exc:
        logger.debug("读取抖音封面预览哈希失败: %s", exc)
        return None


def _is_cover_preview_matched(page, cover_path_abs: str) -> bool:
    local_hash = _average_hash_for_image(Path(cover_path_abs))
    preview_hash = _get_douyin_cover_preview_hash(page)
    distance = _hash_distance(local_hash, preview_hash)
    if distance is None:
        logger.error("抖音封面预览无法计算视觉哈希，不能确认封面真正替换")
        return False
    if distance > DOUYIN_COVER_PREVIEW_MAX_HASH_DISTANCE:
        logger.error("抖音封面预览与上传封面不匹配，视觉哈希距离=%s", distance)
        return False
    logger.info("抖音封面预览与上传封面匹配，视觉哈希距离=%s", distance)
    return True


def _click_matching_cover_thumbnail(page, cover_path_abs: str) -> bool:
    local_hash = _average_hash_for_image(Path(cover_path_abs), size=8)
    if not local_hash:
        return False
    try:
        best = page.evaluate(
            """localHash => {
                const bitCount = value => {
                    let count = 0n;
                    while (value) {
                        count += value & 1n;
                        value >>= 1n;
                    }
                    return Number(count);
                };
                const imageHash = image => {
                    const rect = image.getBoundingClientRect();
                    if (rect.width <= 20 || rect.height <= 20) return null;
                    const style = getComputedStyle(image);
                    if (style.visibility === 'hidden' || style.display === 'none') return null;
                    if (!image.complete || image.naturalWidth <= 0 || image.naturalHeight <= 0) return null;
                    const canvas = document.createElement('canvas');
                    canvas.width = 8;
                    canvas.height = 8;
                    const context = canvas.getContext('2d', { willReadFrequently: true });
                    context.drawImage(image, 0, 0, 8, 8);
                    const pixels = context.getImageData(0, 0, 8, 8).data;
                    let values = [];
                    for (let i = 0; i < pixels.length; i += 4) {
                        values.push(Math.round(0.299 * pixels[i] + 0.587 * pixels[i + 1] + 0.114 * pixels[i + 2]));
                    }
                    const average = values.reduce((sum, value) => sum + value, 0) / values.length;
                    let bits = '';
                    for (const value of values) bits += value >= average ? '1' : '0';
                    return {
                        hash: BigInt('0b' + bits).toString(16).padStart(16, '0'),
                        rect: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                        },
                        src: image.currentSrc || image.src || '',
                    };
                };
                const local = BigInt('0x' + localHash);
                const candidates = [];
                for (const image of Array.from(document.querySelectorAll('img'))) {
                    try {
                        const item = imageHash(image);
                        if (!item) continue;
                        item.distance = bitCount(local ^ BigInt('0x' + item.hash));
                        candidates.push(item);
                    } catch (_) {
                    }
                }
                candidates.sort((left, right) => left.distance - right.distance);
                return candidates[0] || null;
            }""",
            local_hash,
        )
    except Exception as exc:
        logger.debug("查找抖音匹配封面缩略图失败: %s", exc)
        return False
    if not best:
        logger.error("抖音封面候选缩略图中未找到可计算哈希的图片")
        return False
    distance = best.get("distance")
    rect = best.get("rect") or {}
    if distance is None or distance > DOUYIN_COVER_PREVIEW_MAX_HASH_DISTANCE:
        logger.error("抖音封面候选缩略图与上传封面不匹配，最佳视觉哈希距离=%s", distance)
        return False
    page.mouse.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.wait_for_timeout(1_000)
    logger.info("已选择抖音匹配封面候选缩略图，视觉哈希距离=%s", distance)
    return True


def _open_cover_upload_tab(page, modal) -> None:
    tab_el = _find_visible_element(modal, ["text=上传封面", "text=本地上传", "div.text-zsBQsb:has-text('上传封面')"])
    if tab_el:
        try:
            tab_el.click(timeout=1000)
        except Exception as exc:
            logger.debug("普通点击抖音上传封面 Tab 受阻，尝试 force 点击: %s", exc)
            try:
                tab_el.click(timeout=1000, force=True)
            except Exception as force_exc:
                logger.debug("抖音上传封面 Tab force 点击仍失败，继续检测上传区域: %s", force_exc)
        logger.info("已点击'上传封面' Tab")
        page.wait_for_timeout(1000)


def _inject_cover_file_in_modal(page, modal, cover_path_abs: str) -> bool:
    """在当前封面面板注入图片文件；优先走可见 file chooser，隐藏 input 仅兜底。"""
    btn_selectors = [
        ".upload-ZOJTUA",
        ".upload-BvM5FF",
        ".semi-upload-drag-area:has-text('点击上传文件')",
        "div:has-text('点击上传文件')",
        ".upload-tips-KomyJM",
        "text=+ 上传封面",
    ]
    upload_btn = _find_visible_element(modal, btn_selectors)
    if upload_btn:
        try:
            with page.expect_file_chooser(timeout=4000) as fc_info:
                upload_btn.click(timeout=2000, force=True)
            fc_info.value.set_files(cover_path_abs)
            logger.info("已通过抖音可见上传区域 file chooser 注入封面图片！")
            return True
        except Exception as fc_err:
            logger.debug("点击抖音封面上传区触发 file chooser 失败: %s", fc_err)

    try:
        file_inputs = modal.locator("input[type='file']")
        candidates = []
        for i in range(file_inputs.count()):
            candidate = file_inputs.nth(i)
            if not _is_cover_file_input_candidate(candidate):
                logger.warning("跳过疑似抖音视频 input，accept=%s", _get_file_accept(candidate))
                continue
            candidates.append((_cover_file_input_score(candidate), candidate))
        for _, file_input in sorted(candidates, key=lambda item: item[0], reverse=True):
            file_input.set_input_files(cover_path_abs, timeout=3000)
            logger.info("已通过 modal 内图片 input 兜底注入抖音封面图片！")
            return True
    except Exception as exc:
        logger.debug("直接 set_input_files 注入失败: %s", exc)
    return False


def _apply_cover_in_current_panel(
    page,
    modal,
    cover_path_abs: str,
    *,
    artifact_dir: Optional[Path],
    artifact_prefix: str,
) -> bool:
    _open_cover_upload_tab(page, modal)
    if not _inject_cover_file_in_modal(page, modal, cover_path_abs):
        logger.error("抖音封面图片未能注入当前封面面板: %s", cover_path_abs)
        return False
    page.wait_for_timeout(2000)
    if artifact_dir:
        capture_cover_evidence(page, artifact_dir, f"{artifact_prefix}_after_input_injection", cover_path_abs)
    if not _click_matching_cover_thumbnail(page, cover_path_abs):
        return False
    if not _is_cover_preview_matched(page, cover_path_abs):
        return False
    return True


def _click_horizontal_cover_step(page, modal) -> bool:
    horizontal_selectors = [
        "button:has-text('设置横封面')",
        "span:has-text('设置横封面')",
        "text=设置横封面",
        "button:has-text('横封面')",
        "span:has-text('横封面')",
        "text=横封面",
    ]
    horizontal_btn = _find_visible_element(modal, horizontal_selectors)
    if not horizontal_btn:
        logger.error("未找到抖音横封面设置入口，不能确认横竖双封面完整")
        return False
    try:
        horizontal_btn.click(timeout=2000)
    except Exception as exc:
        logger.debug("普通点击抖音横封面入口失败，尝试 force 点击: %s", exc)
        horizontal_btn.click(timeout=2000, force=True)
    page.wait_for_timeout(1500)
    logger.info("已进入抖音横封面设置面板")
    return True


def _click_cover_confirm(page, modal) -> None:
    confirm_selectors = [
        "button:has-text('完成')", "span:has-text('完成')", "button.semi-button-primary",
        "text=完成", "text=确定", "text=确认", "text=裁剪并保存"
    ]
    confirm_btn = _find_visible_element(modal, confirm_selectors)
    if confirm_btn and confirm_btn.is_enabled():
        confirm_btn.click(timeout=2000)
        logger.info("已点击右下角'完成'保存封面！")
        page.wait_for_timeout(2000)


def apply_cover(
    page,
    cover_path: str,
    *,
    artifact_dir: Optional[Path] = None,
    horizontal_cover_path: Optional[str] = None,
) -> bool:
    """应用抖音封面上传；提供横封面时必须同时确认横竖双封面。"""
    if not cover_path or not Path(cover_path).is_file():
        logger.error("抖音竖封面文件不存在: %s", cover_path)
        return False
    if horizontal_cover_path and not Path(horizontal_cover_path).is_file():
        logger.error("抖音横封面文件不存在: %s", horizontal_cover_path)
        return False
    try:
        logger.info("开始应用抖音封面: %s", cover_path)
        cover_path_abs = str(Path(cover_path).resolve())
        horizontal_cover_path_abs = str(Path(horizontal_cover_path).resolve()) if horizontal_cover_path else None

        # 1. 寻找并点击“选择封面” / “设置封面” 入口按钮
        entry_selectors = [
            "text=选择封面", "text=设置封面", "text=编辑封面", "text=更改封面", "text=更换封面",
            "div:has-text('选择封面')", "div:has-text('设置封面')", ".cover-edit-btn", "[class*='cover'] button"
        ]
        cover_entry = _find_visible_element(page, entry_selectors)
        if not cover_entry:
            logger.warning("未找到抖音封面设置入口（选择封面/设置封面）")
            return False

        cover_entry.click(timeout=2000)
        page.wait_for_timeout(2000)
        if artifact_dir:
            capture_cover_evidence(page, artifact_dir, "douyin_cover_entry_opened", cover_path_abs)

        # 2. 定位 Modal 并切换“上传封面” / “本地上传” Tab
        modal = _find_active_modal(page, [".dy-creator-content-modal-wrap", ".semi-modal-wrap", "div[role='dialog']", ".modal-container"])

        if not _apply_cover_in_current_panel(
            page,
            modal,
            cover_path_abs,
            artifact_dir=artifact_dir,
            artifact_prefix="douyin_cover",
        ):
            return False

        if horizontal_cover_path_abs:
            if not _click_horizontal_cover_step(page, modal):
                return False
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_entry_opened", horizontal_cover_path_abs)
            if not _apply_cover_in_current_panel(
                page,
                modal,
                horizontal_cover_path_abs,
                artifact_dir=artifact_dir,
                artifact_prefix="douyin_horizontal_cover",
            ):
                return False

        _click_cover_confirm(page, modal)

        # 若弹窗未自动关闭，尝试 Escape
        try:
            if modal.is_visible(timeout=500):
                page.keyboard.press("Escape")
                page.wait_for_timeout(1000)
        except Exception:
            pass
        if artifact_dir:
            capture_cover_evidence(page, artifact_dir, "douyin_cover_applied", cover_path_abs)
        return True

    except Exception as e:
        logger.warning("抖音封面应用过程发生异常: %s", e)

    return False

def fill_publish_fields(page, title_text: str, description_text: str, artifact_dir: Path, cover_path: Optional[str] = None) -> bool:
    """填入作品标题和描述并应用封面，停在提交前页面；不保存草稿、不发布。"""
    title_input = get_title_input(page)
    editor = get_description_editor(page)
    if not title_input or not editor:
        return False
    title = " ".join((title_text or "").split()).strip()
    description = (description_text or "").strip()
    if title:
        title_input.fill(title[:50])
    if description:
        editor.fill(description)
    page.wait_for_timeout(500)
    
    if cover_path and Path(cover_path).is_file():
        logger.info(f"开始应用抖音封面: {cover_path}")
        cover_upload_path = prepare_douyin_cover_upload_file(cover_path)
        horizontal_cover_upload_path = prepare_douyin_horizontal_cover_upload_file(cover_path)
        if not cover_upload_path or not horizontal_cover_upload_path:
            return False
        if not apply_cover(
            page,
            cover_upload_path,
            artifact_dir=artifact_dir,
            horizontal_cover_path=horizontal_cover_upload_path,
        ):
            logger.error("抖音横竖封面未能完整确认应用，停止后续发布以避免默认封面作品")
            return False

    
    capture_controls(page, artifact_dir, "douyin_ready_to_submit")
    logger.info("已填入抖音作品标题和描述，仍未保存草稿或发布")
    return True


def get_publish_button(page):
    """返回底部唯一的“发布”按钮；避免误点“高清发布”等其它入口。"""
    button = page.get_by_text("发布", exact=True)
    count = button.count()
    if count != 1:
        logger.error("抖音最终发布按钮数量异常，期望 1，实际 %s", count)
        return None
    if not button.is_enabled():
        logger.error("抖音最终发布按钮当前不可用")
        return None
    return button


def _normalize_page_text(text: str) -> str:
    return "".join((text or "").split())


def _current_work_visible(page_text: str, title_text: str, description_text: str) -> bool:
    normalized_page = _normalize_page_text(page_text)
    title_marker = _normalize_page_text(title_text)[:20]
    desc_marker = _normalize_page_text(description_text)[:30]
    return bool(title_marker and title_marker in normalized_page) or bool(desc_marker and desc_marker in normalized_page)


def wait_for_publish_submission(
    page,
    *,
    title_text: str,
    description_text: str,
    timeout_seconds: int = 900,
) -> bool:
    """等待抖音接受提交；最终可见状态仍交给作品管理回查确认。"""
    success_markers = ("发布成功", "提交成功", "作品发布成功", "等待审核", "审核中", "发布完成", "管理作品")
    failure_markers = ("发布失败", "提交失败", "不成功")
    upload_markers = ("作品上传中", "上传完成后将自动发布", "请勿关闭页面")
    for elapsed in range(timeout_seconds):
        if "manage" in page.url:
            logger.info("已成功跳转至抖音作品管理页面: %s", page.url)
            return True
        text = get_page_text(page)
        if any(marker in text for marker in success_markers):
            logger.info("检测到抖音成功发布提示文本")
            return True
        if any(marker in text for marker in upload_markers):
            if elapsed and elapsed % 30 == 0:
                logger.info("抖音发布后仍在上传，已等待 %s 秒", elapsed)
            page.wait_for_timeout(1_000)
            continue
        if _current_work_visible(text, title_text, description_text):
            return True
        if any(marker in text for marker in failure_markers):
            logger.error("抖音页面提示提交失败: %s", " ".join(text.split())[:500])
            return False
        page.wait_for_timeout(1_000)
    return False


def publish_after_review(page, artifact_dir: Path, *, title_text: str, description_text: str) -> bool:
    """点击最终发布并采集提交后页面；只表示提交已被平台接受，不直接记 PUBLISHED。"""
    # 填发表单后若有模态弹窗拦截（如 Douyin / Semi Design 封面弹窗），主动尝试清理
    try:
        modal = page.locator(".dy-creator-content-modal-wrap, .semi-modal-wrap").first
        if modal.count() > 0 and modal.is_visible(timeout=500):
            logger.warning("发现未关闭的弹窗遮罩，发送 Escape 键清理")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass

    button = get_publish_button(page)
    if not button:
        return False
    try:
        button.click(timeout=5000)
    except Exception as exc:
        logger.warning("普通点击发布按钮受阻 (%s)，使用 force=True 强制点击发布", exc)
        button.click(force=True)
    page.wait_for_timeout(1_000)
    capture_controls(page, artifact_dir, "douyin_post_submit")
    if wait_for_publish_submission(page, title_text=title_text, description_text=description_text):
        logger.info("抖音已接受发布提交，等待审核或作品管理回查确认")
        return True
    capture_controls(page, artifact_dir, "douyin_submit_unconfirmed")
    return False


def upload_and_publish(
    page,
    video_path: str,
    artifact_dir: Path,
    *,
    upload_wait_seconds: int,
    title_text: str,
    description_text: str,
    cover_path: Optional[str] = None,
) -> int:
    """上传、填写标题描述并显式发布；返回审核中而非最终已发布。"""
    if not upload_for_calibration(
        page,
        video_path,
        artifact_dir,
        upload_wait_seconds=upload_wait_seconds,
        title_text=title_text,
        description_text=description_text,
        cover_path=cover_path,
    ):
        return EXIT_UNCONFIRMED
    if publish_after_review(page, artifact_dir, title_text=title_text, description_text=description_text):
        return EXIT_UNDER_REVIEW
    return EXIT_UNCONFIRMED


def wait_until_logged_in(page, timeout_seconds: int = 300) -> bool:
    """等待用户在可视浏览器中完成登录。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        visible_text = get_page_text(page)
        frame_urls = [frame.url for frame in page.frames]
        if is_creator_center_url(page.url) and not is_login_required(page.url, visible_text, frame_urls):
            return True
        page.wait_for_timeout(2_000)
    return False


def save_storage_state(context, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(state_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Douyin creator-center uploader")
    parser.add_argument("--video", type=Path, help="竖屏成片路径")
    parser.add_argument("--cover", type=Path, help="封面图片路径")
    parser.add_argument("--copy", type=Path, help="发布文案路径")
    parser.add_argument("--title-file", type=Path, help="发布标题路径")
    parser.add_argument("--state", type=Path, default=Path("output/douyin_state.json"), help="Playwright 登录态文件")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--fail-fast-login", action="store_true", help="登录失效时立即退出，不等待扫码")
    parser.add_argument("--login-only", action="store_true", help="仅打开创作者中心并保存登录态")
    parser.add_argument("--calibrate", action="store_true", help="采集当前发布页控件快照，不上传、不发布")
    parser.add_argument("--calibrate-after-upload", action="store_true", help="仅上传并采集表单控件，绝不填写或发布")
    parser.add_argument("--upload-wait-seconds", type=int, default=900, help="等待抖音文件上传完成的最长秒数")
    parser.add_argument("--prepare-description", action="store_true", help="仅填入标题和作品描述，停在提交前页面")
    parser.add_argument("--publish", action="store_true", help="发布视频；校准完成前会安全拒绝")
    parser.add_argument("--verify-only", action="store_true", help="仅核对作品状态；校准完成前会安全拒绝")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.publish and (not args.video or not args.copy):
        logger.error("--publish requires --video and --copy")
        return EXIT_FAILED
    if args.calibrate_after_upload and not args.video:
        logger.error("--calibrate-after-upload requires --video")
        return EXIT_FAILED
    if args.video and not args.video.is_file():
        logger.error("视频文件不存在: %s", args.video)
        return EXIT_FAILED
    if args.copy and not args.copy.is_file():
        logger.error("文案文件不存在: %s", args.copy)
        return EXIT_FAILED
    if args.title_file and not args.title_file.is_file():
        logger.error("标题文件不存在: %s", args.title_file)
        return EXIT_FAILED

    artifact_dir = args.state.parent / "douyin_calibration"
    try:
        playwright_context = sync_playwright()
        playwright = playwright_context.__enter__()
    except KeyboardInterrupt:
        return EXIT_UNCONFIRMED
    try:
        browser = playwright.chromium.launch(headless=not args.no_headless)
        context_kwargs = {}
        if args.state.is_file():
            context_kwargs["storage_state"] = str(args.state)
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(DOUYIN_UPLOAD_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2_000)

        visible_text = get_page_text(page)
        frame_urls = [frame.url for frame in page.frames]
        login_required = is_login_required(page.url, visible_text, frame_urls)
        if login_required:
            if args.fail_fast_login:
                logger.error("抖音登录态失效或尚未登录")
                browser.close()
                return EXIT_LOGIN_REQUIRED
            logger.info("请在打开的浏览器中完成抖音创作者中心登录")
            if not wait_until_logged_in(page):
                browser.close()
                return EXIT_LOGIN_REQUIRED

        save_storage_state(context, args.state)
        if args.login_only:
            capture_controls(page, artifact_dir, "douyin_login_ready")
            browser.close()
            return EXIT_OK

        if args.calibrate:
            capture_controls(page, artifact_dir, "douyin_publish_page")
            logger.info("已采集抖音发布页控件快照；尚未启用上传或发布选择器")
            browser.close()
            return EXIT_OK

        if args.calibrate_after_upload:
            if not wait_for_video_upload_input(page):
                browser.close()
                return EXIT_UNCONFIRMED
            title_text = args.title_file.read_text(encoding="utf-8") if args.prepare_description and args.title_file else ""
            description_text = args.copy.read_text(encoding="utf-8") if args.prepare_description and args.copy else ""
            uploaded = upload_for_calibration(
                page,
                str(args.video),
                artifact_dir,
                upload_wait_seconds=args.upload_wait_seconds,
                title_text=title_text if args.prepare_description else None,
                description_text=description_text if args.prepare_description else None,
                cover_path=str(args.cover) if args.prepare_description and args.cover else None,
            )
            browser.close()
            return EXIT_UPLOADED_FOR_CALIBRATION if uploaded else EXIT_UNCONFIRMED

        if args.verify_only:
            logger.error("抖音作品管理回查尚未完成页面校准；本次不读取状态、不触发上传")
            browser.close()
            return EXIT_NOT_CALIBRATED

        if args.publish:
            if not wait_for_video_upload_input(page):
                browser.close()
                return EXIT_UNCONFIRMED
            title_text = args.title_file.read_text(encoding="utf-8") if args.title_file else ""
            description_text = args.copy.read_text(encoding="utf-8") if args.copy else ""
            result = upload_and_publish(
                page,
                str(args.video),
                artifact_dir,
                upload_wait_seconds=args.upload_wait_seconds,
                title_text=title_text,
                description_text=description_text,
                cover_path=str(args.cover) if args.cover else None,
            )
            browser.close()
            return result

        capture_controls(page, artifact_dir, "douyin_publish_page")
        browser.close()
        return EXIT_OK
    except KeyboardInterrupt:
        logger.warning("抖音上传器被中断，本次状态未确认")
        return EXIT_UNCONFIRMED
    finally:
        try:
            playwright_context.__exit__(None, None, None)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
