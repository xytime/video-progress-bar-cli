"""快手创作者中心浏览器上传器。

仅适用于创作者自己的快手账号：首次扫码后的浏览器会话保存在本机状态文件，
不使用快手开放平台 App、OAuth 或任何 API 密钥。上传控件须在真实登录页面
校准后才会启用，防止页面改版时误提交作品。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-07-15 | Codex | 新增快手创作者中心会话登录、状态判定与安全返回码骨架 |
| 1.1.0 | 2026-07-15 | Codex | 基于已登录创作者后台实测，固化唯一视频文件输入控件的选择器与校验 |
| 1.2.0 | 2026-07-15 | Codex | 新增仅上传校准模式，采集上传后表单控件但不填写、不保存草稿、不发布 |
| 1.2.1 | 2026-07-15 | Codex | 登录回跳后等待发表页异步渲染，避免过早误判视频文件输入控件缺失 |
| 1.3.0 | 2026-07-15 | Codex | 校准快照纳入内容编辑器和 ARIA 按钮，并可仅前进一页查看作品信息字段 |
| 1.3.1 | 2026-07-15 | Codex | 识别快手新手引导的 Skip 控件，避免将引导“下一步”误作作品提交步骤 |
| 1.3.2 | 2026-07-15 | Codex | 上传后等待“上传中”与进度百分比消失，超时转不确定而非误报上传完成 |
| 1.3.3 | 2026-07-15 | Codex | 文件选中后先等待页面进入上传态，避免首帧尚未显示进度时过早判定完成 |
| 1.4.0 | 2026-07-15 | Codex | 实测作品描述 contenteditable 控件，支持仅填入文案并停在提交前页面 |
| 1.4.1 | 2026-07-15 | Codex | 填写描述后滚至提交区采集真实按钮，避免将页面上方控件误作最终操作 |
| 1.4.2 | 2026-07-15 | Codex | 适配快手内部滚动容器，定位页面底部的实际提交区而非 window 正文 |
| 1.5.0 | 2026-07-15 | Codex | 实测最终发布按钮，新增提交后成功确认轮询；默认不开启发布动作 |
| 1.6.0 | 2026-07-15 | Codex | 发布后必须在作品管理列表中检出本次文案标识，杜绝仅凭提示或跳转误报已发布 |
| 1.6.1 | 2026-07-15 | Codex | 识别快手明确的内容校验失败提示并返回可重试失败，避免误标为发布结果不确定 |
| 1.7.0 | 2026-07-15 | Codex | 区分作品管理中的“审核中”和“已发布”；审核中只表示提交成功，不能冒充最终发布成功 |
| 1.7.1 | 2026-07-15 | Codex | 快手专属文案适配：最多保留前 4 个话题，避免平台因标签上限拒绝，原始视频号文案不改 |
| 1.8.0 | 2026-07-15 | Codex | 新增仅核对作品管理状态模式，用于定时审核，不触发上传或发布 |
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


logger = logging.getLogger("kuaishou_uploader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

KUAISHOU_PUBLISH_URL = "https://cp.kuaishou.com/article/publish/video"
KUAISHOU_MANAGE_URL = "https://cp.kuaishou.com/article/manage/video"
KUAISHOU_VIDEO_INPUT_SELECTOR = 'input[type="file"][accept*="video"]'
KUAISHOU_DESCRIPTION_SELECTOR = '[contenteditable="true"][placeholder*="作品描述"]'
KUAISHOU_MAX_TOPIC_TAGS = 4
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_LOGIN_REQUIRED = 2
EXIT_UNCONFIRMED = 3
EXIT_NOT_CALIBRATED = 4
EXIT_UPLOADED_FOR_CALIBRATION = 5
EXIT_UNDER_REVIEW = 6
MANAGEMENT_PUBLISHED = "PUBLISHED"
MANAGEMENT_UNDER_REVIEW = "UNDER_REVIEW"
MANAGEMENT_VISIBLE_UNCONFIRMED = "VISIBLE_UNCONFIRMED"


def is_creator_publish_url(url: str) -> bool:
    """只把创作者中心视频发表页视为已登录状态，不能只根据域名判断。"""
    parsed = urlparse(url or "")
    return parsed.netloc == "cp.kuaishou.com" and parsed.path.rstrip("/") == "/article/publish/video"


def is_login_required(url: str, visible_text: str = "", frame_urls: Iterable[str] = ()) -> bool:
    """综合 URL、页面和 iframe 证据判断是否需要扫码登录。"""
    candidates = [url or "", *frame_urls]
    if any("passport.kuaishou.com" in candidate or "/login" in candidate for candidate in candidates):
        return True
    return "立即登录" in (visible_text or "") and "快手创作者服务平台" in (visible_text or "")


def is_confirmed_submission(*, redirected: bool, page_text: str, draft: bool) -> bool:
    """只有跳转作品管理或明确成功提示才认定提交完成。"""
    if redirected:
        return True
    if "不成功" in (page_text or ""):
        return False
    success_text = ("保存草稿成功", "保存成功") if draft else ("发布成功", "发表成功")
    return any(text in (page_text or "") for text in success_text)


def get_publish_failure_reason(page_text: str) -> Optional[str]:
    """提取快手页面已明确给出的发布失败原因；空值表示仍无法判定。"""
    compact = " ".join((page_text or "").split())
    match = re.search(r"(?:内容)?发布失败\s*[:：]\s*([^\n]+)", compact)
    if match:
        return match.group(1).strip()
    if "发布不成功" in compact:
        return "快手页面提示发布不成功"
    return None


def adapt_copy_for_kuaishou(copy_text: str) -> tuple[str, int]:
    """按快手话题上限生成提交副本，原始文案文件保持不变。"""
    matches = list(re.finditer(r"#[^\s#]+", copy_text or ""))
    if len(matches) <= KUAISHOU_MAX_TOPIC_TAGS:
        return copy_text, 0
    chunks: list[str] = []
    cursor = 0
    for match in matches[KUAISHOU_MAX_TOPIC_TAGS:]:
        removal_start = match.start()
        while removal_start > cursor and copy_text[removal_start - 1].isspace():
            removal_start -= 1
        chunks.append(copy_text[cursor:removal_start])
        cursor = match.end()
    chunks.append(copy_text[cursor:])
    return "".join(chunks).strip(), len(matches) - KUAISHOU_MAX_TOPIC_TAGS


def get_video_upload_input(page, *, log_unexpected: bool = True):
    """返回实测的唯一视频文件输入控件；页面变化时拒绝猜测并安全停止。"""
    locator = page.locator(KUAISHOU_VIDEO_INPUT_SELECTOR)
    count = locator.count()
    if count != 1:
        if log_unexpected:
            logger.error("快手视频文件输入控件数量异常，期望 1，实际 %s", count)
        return None
    return locator


def wait_for_video_upload_input(page, timeout_seconds: int = 15):
    """登录回跳后等待 SPA 渲染出唯一视频上传控件。"""
    for _ in range(timeout_seconds):
        upload_input = get_video_upload_input(page, log_unexpected=False)
        if upload_input:
            return upload_input
        page.wait_for_timeout(1_000)
    return get_video_upload_input(page)


def _capture_form_controls(page, artifact_dir: Path, artifact_name: str) -> None:
    """采集可编辑字段与交互按钮的最小契约，供后续选择器校准。"""
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
        logger.warning("保存快手表单截图失败: %s", exc)


def dismiss_onboarding_if_present(page) -> bool:
    """关闭快手新手引导；这只影响本地引导浮层，不修改作品内容。"""
    skip = page.locator('[aria-label="Skip"]')
    if skip.count() == 0:
        return False
    if skip.count() != 1:
        logger.warning("快手新手引导 Skip 控件数量异常，保留浮层")
        return False
    skip.click()
    page.wait_for_timeout(500)
    return True


def is_upload_in_progress(page) -> bool:
    """快手页面仍展示上传中或百分比时，绝不能把文件当作已上传完成。"""
    try:
        visible_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return True
    return "上传中" in visible_text or re.search(r"(?<!\d)(?:100|[1-9]?\d)%", visible_text) is not None


def wait_for_upload_completion(page, timeout_seconds: int = 900) -> bool:
    """等待快手文件传输完成；超时交给调用方标记 UNCERTAIN，禁止自动重传。"""
    for elapsed in range(timeout_seconds):
        if not is_upload_in_progress(page):
            return True
        if elapsed and elapsed % 30 == 0:
            logger.info("快手文件仍在上传，已等待 %s 秒", elapsed)
        page.wait_for_timeout(1_000)
    return False


def get_description_editor(page):
    """返回实测的唯一作品描述编辑器；不可确认时拒绝填入文案。"""
    editor = page.locator(KUAISHOU_DESCRIPTION_SELECTOR)
    count = editor.count()
    if count != 1:
        logger.error("快手作品描述编辑器数量异常，期望 1，实际 %s", count)
        return None
    return editor


def fill_description_for_review(page, copy_text: str, artifact_dir: Path) -> bool:
    """仅填入作品描述并采集提交前页面；绝不点草稿或发布。"""
    editor = get_description_editor(page)
    if not editor:
        return False
    editor.fill(copy_text.strip())
    page.wait_for_timeout(500)
    _capture_form_controls(page, artifact_dir, "kuaishou_ready_to_submit")
    logger.info("已填入快手作品描述，仍未保存草稿或发布")
    return True


def capture_submission_area(page, artifact_dir: Path) -> None:
    """滚动至页面底部并采集最终操作区；只读，不触发草稿或发布。"""
    page.evaluate(
        """() => {
            const candidates = Array.from(document.querySelectorAll('*')).filter((element) => {
                const style = getComputedStyle(element);
                return ['auto', 'scroll'].includes(style.overflowY)
                    && element.scrollHeight > element.clientHeight + 8;
            });
            const target = candidates.sort((left, right) =>
                (right.scrollHeight - right.clientHeight) - (left.scrollHeight - left.clientHeight)
            )[0];
            if (!target) return false;
            target.scrollTop = target.scrollHeight;
            return true;
        }"""
    )
    page.wait_for_timeout(500)
    _capture_form_controls(page, artifact_dir, "kuaishou_submission_area")


def get_publish_button(page):
    """返回页面底部唯一的“发布”按钮，拒绝模糊匹配以防误点其他操作。"""
    button = page.get_by_text("发布", exact=True)
    count = button.count()
    if count != 1:
        logger.error("快手最终发布按钮数量异常，期望 1，实际 %s", count)
        return None
    if not button.is_enabled():
        logger.error("快手最终发布按钮当前不可用")
        return None
    return button


def wait_for_publish_confirmation(page, timeout_seconds: int = 60) -> bool:
    """点击发布后仅凭明确成功文案或跳转作品管理判定成功。"""
    for _ in range(timeout_seconds):
        try:
            page_text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            page_text = ""
        if is_confirmed_submission(
            redirected="/article/manage/video" in page.url,
            page_text=page_text,
            draft=False,
        ):
            return True
        if get_publish_failure_reason(page_text):
            return False
        page.wait_for_timeout(1_000)
    return False


def _normalize_page_text(text: str) -> str:
    """压缩页面空白，避免管理列表的换行导致文案标识匹配失败。"""
    return re.sub(r"\s+", "", text or "")


def is_visible_in_management(page_text: str, copy_text: str) -> bool:
    """管理页须包含本次完整文案（忽略空白）才视为作品确实可见。"""
    marker = _normalize_page_text(copy_text)
    return bool(marker) and marker in _normalize_page_text(page_text)


def get_management_submission_state(page_text: str, copy_text: str) -> Optional[str]:
    """从本次作品所在的管理列表片段读取审核状态，避免被其他作品状态干扰。"""
    normalized_page = _normalize_page_text(page_text)
    marker = _normalize_page_text(copy_text)
    if not marker:
        return None
    marker_index = normalized_page.find(marker)
    if marker_index < 0:
        return None
    status_window = normalized_page[marker_index + len(marker):marker_index + len(marker) + 100]
    review_index = status_window.find("审核中")
    published_index = status_window.find("已发布")
    if review_index >= 0 and (published_index < 0 or review_index < published_index):
        return MANAGEMENT_UNDER_REVIEW
    if published_index >= 0:
        return MANAGEMENT_PUBLISHED
    return MANAGEMENT_VISIBLE_UNCONFIRMED


def wait_for_management_submission_state(page, copy_text: str, timeout_seconds: int = 60) -> Optional[str]:
    """进入作品管理并轮询本次文案及其状态；超时必须返回未确认。"""
    try:
        page.goto(KUAISHOU_MANAGE_URL, wait_until="domcontentloaded")
    except Exception as exc:
        logger.error("无法进入快手作品管理页核验发布结果: %s", exc)
        return False
    for _ in range(timeout_seconds):
        if _page_login_required(page):
            logger.error("进入作品管理页后登录态失效，无法核验发布结果")
            return False
        try:
            page_text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            page_text = ""
        state = get_management_submission_state(page_text, copy_text)
        if state:
            return state
        page.wait_for_timeout(1_000)
    return None


def publish_after_review(page, artifact_dir: Path, copy_text: str) -> Optional[str]:
    """执行最终发布，并返回作品管理中确认到的本次作品状态。"""
    button = get_publish_button(page)
    if not button:
        return None
    button.click()
    confirmed = wait_for_publish_confirmation(page)
    _capture_form_controls(page, artifact_dir, "kuaishou_post_submit")
    if not confirmed:
        return None
    return wait_for_management_submission_state(page, copy_text)


def upload_for_calibration(
    page,
    video_path: str,
    artifact_dir: Path,
    *,
    advance_form_once: bool = False,
    upload_wait_seconds: int = 900,
    description_text: Optional[str] = None,
    publish: bool = False,
) -> bool | str | None:
    """只上传一个已授权视频并保存表单结构；绝不填写、保存草稿或发布。"""
    upload_input = get_video_upload_input(page)
    if not upload_input:
        return False
    upload_input.set_input_files(str(Path(video_path).resolve()))
    page.wait_for_timeout(2_000)
    if not wait_for_upload_completion(page, timeout_seconds=upload_wait_seconds):
        logger.error("快手文件上传在 %s 秒内无法确认完成", upload_wait_seconds)
        return False
    dismiss_onboarding_if_present(page)
    _capture_form_controls(page, artifact_dir, "kuaishou_post_upload")
    if description_text is not None and not fill_description_for_review(page, description_text, artifact_dir):
        return False
    if description_text is not None:
        capture_submission_area(page, artifact_dir)
    if publish:
        return publish_after_review(page, artifact_dir, description_text or "")
    if advance_form_once:
        next_step = page.get_by_text("下一步", exact=True)
        if next_step.count() != 1:
            logger.error("快手作品信息“下一步”控件数量异常，拒绝前进")
            return False
        next_step.click()
        page.wait_for_timeout(1_500)
        _capture_form_controls(page, artifact_dir, "kuaishou_next_step")
    logger.info("已上传文件并保存表单控件；未保存草稿、未发布")
    return True


def _page_login_required(page) -> bool:
    """从当前页面和所有 iframe 采集最小登录证据。"""
    try:
        visible_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        visible_text = ""
    try:
        frame_urls = [frame.url for frame in page.frames]
    except Exception:
        frame_urls = ()
    return is_login_required(page.url, visible_text, frame_urls)


def _wait_for_manual_login(page, timeout_seconds: int) -> bool:
    """等待用户在已显示的浏览器窗口完成扫码，绝不代填登录信息。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _page_login_required(page) and is_creator_publish_url(page.url):
            return True
        page.wait_for_timeout(1_000)
    return False


def verify_submission_in_management(page, copy_text: str) -> int:
    """只读核对当前文案在作品管理中的最终状态，绝不上传或提交。"""
    submission_state = wait_for_management_submission_state(page, copy_text)
    if submission_state == MANAGEMENT_PUBLISHED:
        logger.info("快手作品管理已确认本次作品为已发布")
        return EXIT_OK
    if submission_state == MANAGEMENT_UNDER_REVIEW:
        logger.info("快手作品管理显示本次作品仍在审核中")
        return EXIT_UNDER_REVIEW
    logger.warning("快手作品管理未能确认本次作品状态")
    return EXIT_UNCONFIRMED


def run_uploader(
    video_path: Optional[str] = None,
    copy_path: Optional[str] = None,
    *,
    state_path: str = "output/kuaishou_state.json",
    login_only: bool = False,
    headless: bool = True,
    relogin: bool = False,
    fail_fast_login: bool = False,
    login_wait_seconds: int = 180,
    draft: bool = False,
    calibrate_after_upload: bool = False,
    advance_form_once: bool = False,
    upload_wait_seconds: int = 900,
    prepare_description: bool = False,
    publish: bool = False,
    verify_only: bool = False,
) -> int:
    """登录并进入快手发表页；上传动作在真实 DOM 校准前被显式阻止。"""
    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    if not login_only:
        if not copy_path or not Path(copy_path).is_file():
            logger.error("发布文案文件不存在: %s", copy_path)
            return EXIT_FAILED
        if not verify_only and (not video_path or not Path(video_path).is_file()):
            logger.error("视频文件不存在: %s", video_path)
            return EXIT_FAILED

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--no-proxy-server", "--window-size=1280,800"],
        )
        context_options = {"viewport": {"width": 1280, "height": 800}}
        if state_file.exists() and not relogin:
            context_options["storage_state"] = str(state_file)
        context = browser.new_context(**context_options)
        page = context.new_page()
        try:
            page.goto(KUAISHOU_PUBLISH_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            if _page_login_required(page):
                if fail_fast_login:
                    logger.warning("快手登录态失效，自动任务不等待扫码")
                    return EXIT_LOGIN_REQUIRED
                logger.info("请在浏览器窗口扫码登录快手创作者中心")
                if not _wait_for_manual_login(page, login_wait_seconds):
                    logger.warning("未在规定时间内完成快手扫码登录")
                    return EXIT_LOGIN_REQUIRED

            if not is_creator_publish_url(page.url):
                logger.error("登录后未进入快手视频发表页: %s", page.url)
                return EXIT_LOGIN_REQUIRED

            context.storage_state(path=str(state_file))
            logger.info("快手创作者中心登录态已保存: %s", state_file)
            if login_only:
                return EXIT_OK
            if verify_only:
                copy_text = Path(copy_path).read_text(encoding="utf-8")
                copy_text, removed_tags = adapt_copy_for_kuaishou(copy_text)
                if removed_tags:
                    logger.info("快手审核核对使用已适配的 %s 标签文案", KUAISHOU_MAX_TOPIC_TAGS)
                return verify_submission_in_management(page, copy_text)

            # 已实测为唯一 input[type=file][accept*=video]；真正传输前仍须由上层
            # 获得明确授权，并在上传后的表单上继续校准标题、简介及草稿/发布按钮。
            if not wait_for_video_upload_input(page):
                return EXIT_UNCONFIRMED
            if calibrate_after_upload:
                if publish and not prepare_description:
                    logger.error("发布前必须先通过 --prepare-description 填写作品描述")
                    return EXIT_FAILED
                copy_text = Path(copy_path).read_text(encoding="utf-8") if prepare_description else None
                if copy_text is not None:
                    copy_text, removed_tags = adapt_copy_for_kuaishou(copy_text)
                    if removed_tags:
                        logger.info("快手文案按平台上限移除 %s 个尾部话题，原始文案文件未改动", removed_tags)
                publish_result = upload_for_calibration(
                    page,
                    video_path,
                    state_file.parent,
                    advance_form_once=advance_form_once,
                    upload_wait_seconds=upload_wait_seconds,
                    description_text=copy_text,
                    publish=publish,
                )
                if publish:
                    if publish_result == MANAGEMENT_PUBLISHED:
                        return EXIT_OK
                    if publish_result == MANAGEMENT_UNDER_REVIEW:
                        logger.info("快手作品已进入审核中，尚未最终发布")
                        return EXIT_UNDER_REVIEW
                elif publish_result:
                    return EXIT_UPLOADED_FOR_CALIBRATION
                if publish:
                    try:
                        failure_reason = get_publish_failure_reason(
                            page.locator("body").inner_text(timeout=3_000)
                        )
                    except Exception:
                        failure_reason = None
                    if failure_reason:
                        logger.error("快手发布被页面明确拒绝: %s", failure_reason)
                        return EXIT_FAILED
                return EXIT_UNCONFIRMED
            logger.error("快手上传后的表单控件尚未完成真实页面校准，已安全停止。draft=%s", draft)
            return EXIT_NOT_CALIBRATED
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="快手创作者中心浏览器上传器")
    parser.add_argument("--video", help="待上传视频路径")
    parser.add_argument("--copy", help="发布文案文本路径")
    parser.add_argument("--state", default="output/kuaishou_state.json", help="本机 Playwright 会话文件")
    parser.add_argument("--login-only", action="store_true", help="仅扫码登录并保存本机会话")
    parser.add_argument("--relogin", action="store_true", help="忽略旧会话，强制扫码刷新")
    parser.add_argument("--fail-fast-login", action="store_true", help="登录失效时立即返回 2，不等待扫码")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口，供本机扫码")
    parser.add_argument("--login-wait-seconds", type=int, default=180, help="等待扫码的秒数")
    parser.add_argument("--draft", action="store_true", help="预留：后续校准后保存草稿而非发布")
    parser.add_argument("--calibrate-after-upload", action="store_true", help="仅上传并采集表单控件，绝不填写或发布")
    parser.add_argument("--advance-form-once", action="store_true", help="校准时仅点击一次“下一步”，查看作品信息字段")
    parser.add_argument("--upload-wait-seconds", type=int, default=900, help="等待快手文件上传完成的最长秒数")
    parser.add_argument("--prepare-description", action="store_true", help="仅将 --copy 填入作品描述，停在提交前页面")
    parser.add_argument("--publish", action="store_true", help="提交前置校验完成的作品；默认关闭")
    parser.add_argument("--verify-only", action="store_true", help="仅在作品管理核对当前文案状态，绝不上传或发布")
    args = parser.parse_args()
    return run_uploader(
        video_path=args.video,
        copy_path=args.copy,
        state_path=args.state,
        login_only=args.login_only,
        headless=not args.no_headless,
        relogin=args.relogin,
        fail_fast_login=args.fail_fast_login,
        login_wait_seconds=args.login_wait_seconds,
        draft=args.draft,
        calibrate_after_upload=args.calibrate_after_upload,
        advance_form_once=args.advance_form_once,
        upload_wait_seconds=args.upload_wait_seconds,
        prepare_description=args.prepare_description,
        publish=args.publish,
        verify_only=args.verify_only,
    )


if __name__ == "__main__":
    raise SystemExit(main())
