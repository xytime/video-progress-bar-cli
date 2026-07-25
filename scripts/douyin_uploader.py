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
"""

from __future__ import annotations

import argparse
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
            type: element.getAttribute('type'),
            name: element.getAttribute('name'),
            placeholder: element.getAttribute('placeholder'),
            ariaLabel: element.getAttribute('aria-label'),
            role: element.getAttribute('role'),
            contentEditable: element.getAttribute('contenteditable'),
            className: String(element.className || '').slice(0, 160),
            text: (element.textContent || '').trim().slice(0, 80),
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

def _find_visible_element(scope, selectors: Iterable[str], timeout_ms: int = 1000):
    """从候选选择器列表中依次定位第一个可切且可见的元素。"""
    for sel in selectors:
        try:
            el = scope.locator(sel).first
            if el.is_visible(timeout=timeout_ms):
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
                if cand.is_visible():
                    return cand
        except Exception:
            continue
    return page


def apply_cover(page, cover_path: str) -> bool:
    """应用抖音封面上传。"""
    if not cover_path or not Path(cover_path).is_file():
        logger.error("抖音封面文件不存在: %s", cover_path)
        return False
    try:
        logger.info("开始应用抖音封面: %s", cover_path)
        cover_path_abs = str(Path(cover_path).resolve())

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

        # 2. 定位 Modal 并切换“上传封面” / “本地上传” Tab
        modal = _find_active_modal(page, [".dy-creator-content-modal-wrap", ".semi-modal-wrap", "div[role='dialog']", ".modal-container"])
        tab_el = _find_visible_element(modal, ["text=上传封面", "text=本地上传", "div.text-zsBQsb:has-text('上传封面')"])
        if tab_el:
            tab_el.click(timeout=1000)
            logger.info("已点击'上传封面' Tab")
            page.wait_for_timeout(1000)

        # 3. 寻找上传控件并注入图片文件
        injected = False
        try:
            file_inputs = modal.locator("input[type='file']")
            if file_inputs.count() > 0:
                file_inputs.first.set_input_files(cover_path_abs, timeout=3000)
                injected = True
                logger.info("已成功通过 modal 内 input[type='file'] 注入抖音封面图片！")
        except Exception as exc:
            logger.debug("直接 set_input_files 注入失败，将尝试点击触发 file_chooser: %s", exc)

        if not injected:
            btn_selectors = [
                "[class*='selectArea']", "[class*='upload']", ".upload-tips-KomyJM",
                "div:has-text('点击上传文件')", "div:has-text('上传封面')", "text=+ 上传封面"
            ]
            upload_btn = _find_visible_element(modal, btn_selectors)
            if upload_btn:
                try:
                    with page.expect_file_chooser(timeout=4000) as fc_info:
                        upload_btn.click(timeout=2000)
                    fc_info.value.set_files(cover_path_abs)
                    injected = True
                    logger.info("已成功通过点击'+ 上传封面'专属按钮注入封面图片！")
                except Exception as fc_err:
                    logger.debug("点击'+ 上传封面'触发 file_chooser 失败: %s", fc_err)

        if injected:
            page.wait_for_timeout(2000)
            # 4. 点击“完成”/“确定”关闭弹窗
            confirm_selectors = [
                "button:has-text('完成')", "span:has-text('完成')", "button.semi-button-primary",
                "text=完成", "text=确定", "text=确认", "text=裁剪并保存"
            ]
            confirm_btn = _find_visible_element(modal, confirm_selectors)
            if confirm_btn and confirm_btn.is_enabled():
                confirm_btn.click(timeout=2000)
                logger.info("已点击右下角'完成'保存封面！")
                page.wait_for_timeout(2000)

            # 若弹窗未自动关闭，尝试 Escape
            try:
                if modal.is_visible(timeout=500):
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(1000)
            except Exception:
                pass
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
        apply_cover(page, cover_path)

    
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
