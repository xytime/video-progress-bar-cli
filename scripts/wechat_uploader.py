"""WeChat Channels Automated Video Uploader

# Modification History
| Version | Date       | Author                              | Description                                              |
|---------|------------|-------------------------------------|----------------------------------------------------------|
| 1.0.0   | 2026-05-21 | Gemini_3.5_Flash_planning           | Initial creation using Playwright                        |
| 1.1.0   | 2026-05-22 | Claude_Sonnet_4.6_Thinking_planning | 处理短标题/封面/分类/原创勾选；修复登录误判 URL优先策略 |
| 1.2.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | P0根因修复: (1)封面确认改为轮询等待disabled→enabled (2)原创声明增加JS兜底 |
| 1.3.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 原创声明 v2.0: 抗 UI 变化三层降级架构 (_click_original_toggle + _handle_original_rights_dialog) |
| 1.4.0   | 2026-05-24 | Claude_Sonnet_4.6_Thinking_planning | 反反爬虫 v1.0: human_mouse+浏览器指纹伪造+关键点击改为人类行为模拟 |
| 1.5.0   | 2026-05-24 | Gemini_3.5_Flash_High_planning      | 修复原创权益弹窗勾选（适配 AntD Checkbox 与 class 类名禁用校验）及分类下拉框 Shadow DOM 穿透 |
| 1.6.0   | 2026-05-27 | Claude_Sonnet_4.6_Thinking_planning | 优雅截断: 引入 graceful_truncate_title，替换硬截断兜底，防止磁盘读入的超长标题被截成半句 |
| 1.7.0   | 2026-05-27 | Gemini_2.0_Flash_fast               | 增加 Web UI 临时二维码自动生成与无头等待扫码支持 |
| 1.8.0   | 2026-05-27 | Antigravity_planning                | 移除彻底失效的分类选择 UI 操作逻辑（微信官方升级已移除），由自然语言 Hashtag 替代 |
| 1.9.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | _select_collection 全面重写：5轮DOM探针实证，正确选择器 .post-album-display-wrap/.option-item/.create a |
| 2.0.0   | 2026-06-02 | Claude_Sonnet_4.6_Thinking_planning | bugfix: Modal检测改用wait_for_selector(state=visible)；所有return False前Escape关闭遮罩；publish前清理残留dialog |
| 2.1.0   | 2026-06-02 | Gemini_3.5_Flash_planning           | 修复合集列表异步加载延迟；优化创建新合集按钮滚动及 JS 点击兜底 |
| 2.2.0   | 2026-06-15 | Claude_Opus_4.8                     | [BUG-2] 发布确认改为 confirmed 布尔：仅 /post/list 跳转或明确成功文案才 return 0，否则 return 3(UNCONFIRMED) 交管线人工核验，杜绝「假成功」 |
| 2.3.0   | 2026-06-27 | Claude_Opus_4.8                     | [无痛重登] --login-only 不再强制 headless=False，改遵循传入 headless：headless 时走「截图 QR→发 Telegram/Web UI」远程扫码（与上传流登录同路径），实现「登录态丢失后经 Telegram 主动取二维码」；本机当面登录用 --no-headless |
| 2.4.0   | 2026-06-27 | Claude_Opus_4.8                     | [无痛重登·强制] 新增 --relogin：忽略现有会话→必到登录页出二维码，支持「临期主动重登刷新 24h」（不只过期后）；安全——旧 state 不删，仅扫码成功才覆盖，未扫则旧会话保持有效、管线不掉线 |
| 2.5.0   | 2026-06-28 | Claude_Opus_4.8                     | [二维码精裁] 登录二维码在内嵌 iframe(/platform/login-for-iframe)的 img.qrcode(208x208)里，顶层 locator 找不到→以前总发整页截图(206KB,难扫)。改遍历所有 frame 精确裁剪→发 13KB 干净二维码 |
| 2.6.0   | 2026-07-05 | Codex                               | 扫码成功保存 Playwright state 后同步写 wechat_login_at.txt，供 Web/TG 状态判断使用，避免旧 state 文件造成“已登录”假阳性 |
| 2.7.0   | 2026-07-05 | Codex                               | 二维码捕获改为先落盘整页兜底图再尝试精裁覆盖，避免 selector 漂移时 Web UI 无二维码可扫 |
| 2.8.0   | 2026-07-10 | Codex                               | 自动发布新增 fail-fast-login 模式：检测到登录页立即返回 LOGIN_REQUIRED，不把管线挂在扫码等待上 |
| 2.9.0   | 2026-07-23 | Codex                               | 适配视频号新版登录页：优先点击 iframe 内微信快捷登录，失败再切换/裁剪可见二维码，保留扫码兜底 |
| 3.0.0   | 2026-07-29 | Codex                               | 快捷登录后自动确认“视频号创作平台申请使用昵称、头像”的允许授权，单手机无需自扫二维码 |
| 3.1.0   | 2026-07-29 | Codex                               | Playwright 页面/浏览器被关闭时返回 UNCONFIRMED(3)，避免后台裸 traceback 与误判发布成功 |
| 3.2.0   | 2026-07-29 | Codex                               | 自定义封面改为发布硬门禁：仅操作封面预览专属弹层，确认后必须验证持久化证据 |
| 3.3.0   | 2026-07-30 | Codex                               | 封面门禁要求预览实际变化且平台确认成功，拒绝仅凭 toast 放行 |
| 3.4.0   | 2026-07-30 | Codex                               | 封面预览验证比较卡片内全部图片来源，避免首张视频预览遮蔽真实封面变化 |
| 3.5.0   | 2026-07-30 | Codex                               | 图片来源未变时比较封面卡片视觉指纹，兼容平台以同一图片地址刷新封面 |
| 3.6.0   | 2026-07-30 | Codex                               | 封面来源同时读取 img 与 CSS 背景图，适配视频号预览的背景图渲染 |
| 3.7.0   | 2026-07-30 | Codex                               | 增加仅命令行启用的人工视觉核验覆写，保留截图且不放宽自动发布门禁 |
| 3.7.1   | 2026-07-30 | Codex                               | 人工覆写复用封面截图时刻的成功提示，避免 toast 消退后误拒绝已核验操作 |
| 3.7.2   | 2026-07-30 | Codex                               | 覆写以确认点击、弹层关闭和留存截图为依据，适配视觉层 toast 不可读场景 |
| 3.7.3   | 2026-07-30 | Codex                               | 发表跳转后等待作品列表加载再截图，避免空白加载页被误作发布后证据 |
| 3.7.4   | 2026-07-30 | Codex                               | 封面预览生成中等待可见编辑入口，避免隐藏提示被误当作编辑按钮 |
| 3.7.5   | 2026-07-30 | Codex                               | 编辑弹层未立即出现时等待预览图生成完成并重试同一可见入口 |
| 3.7.6   | 2026-07-31 | Codex                               | 复用确认后即时捕获的封面成功提示，避免 toast 消退导致预览已更新却误拦截 |
| 3.7.7   | 2026-07-31 | Codex                               | 确认封面后等待保存中的弹层关闭，避免 2 秒固定等待过早判定失败 |
| 3.7.8   | 2026-07-31 | Codex                               | 直接读取可见封面成功 toast，避免正文同步滞后造成假失败 |
| 3.7.9   | 2026-07-31 | Codex                               | 视频上传超时即中止并保留证据，禁止未完成上传继续进入发表流程 |
| 3.8.0   | 2026-08-04 | Codex                               | 支持明确跳过原创声明，避免转载或获授权素材被自动错误标为原创。 |
| 3.8.0   | 2026-07-31 | Codex                               | 上传前强制校验专门生成封面来源清单，历史视频帧截图不得投递 |
| 3.8.1   | 2026-07-31 | Codex                               | 自动投递必须提供合规封面，禁止平台回退默认视频帧 |
| 3.9.0   | 2026-08-03 | Codex                               | 上传前追加无大面积遮罩版式来源清单校验，旧遮罩封面不得投递 |
| 4.0.0   | 2026-08-11 | Codex                               | 跳转作品列表仅视为平台已受理，返回审核中而非发布成功；最终公开状态交由作品管理回查确认 |
| 4.2.0   | 2026-08-20 | Codex                               | 发布前后比较同会话作品列表原生 ID；唯一新增 ID 且完整标题一致才落绑定回执，标题回查停用 |
| 4.1.0   | 2026-08-20 | Codex                               | 新增作品管理页只读回查：以标题定位后台作品并输出已发布、审核中、驳回、未找到或不可判定结果 |
| 4.3.0   | 2026-08-25 | Codex                               | 修复合集列表选择器；新建后重新回选并校验 active，未确认绑定则阻断发表 |
| 4.4.0   | 2026-08-25 | Codex                               | 合集绑定失败改为发表硬门禁；新增受限 macOS WeChat 桌面快捷授权与无点击预检入口 |
| 4.5.0   | 2026-08-25 | Codex                               | 桌面授权监听改在网页快捷登录点击后启动，避免授权弹窗出现前耗尽观察窗口。 |
"""

import os
import sys
import argparse
import hashlib
import json
import logging
import re
from pathlib import Path
from playwright.sync_api import sync_playwright
try:
    from playwright._impl._errors import TargetClosedError
except Exception:  # pragma: no cover - Playwright 内部类跨版本兜底
    TargetClosedError = ()
import random
import time

# [Claude_Sonnet_4.6_Thinking_planning] 反反爬虫: 人类行为模拟
import sys as _sys
_scripts_dir = str(Path(__file__).parent)
if _scripts_dir not in _sys.path:
    _sys.path.insert(0, _scripts_dir)
_src_dir = str(Path(__file__).parent.parent / "src")
if _src_dir not in _sys.path:
    _sys.path.insert(0, _src_dir)
from human_mouse import (
    human_click, human_check, find_and_human_click_text,
    find_checkbox_near_text, dispatch_human_click_events,
    _human_delay
)
from config.settings import settings
from wechat_desktop_auth import WeChatDesktopAuthWatcher, desktop_auth_preflight
from copywriter import graceful_truncate_title  # [Claude_Sonnet_4.6_Thinking_planning] v1.6.0
from video_processing.core.cover_policy import validate_dedicated_cover_file

try:
    import requests as _requests
except ImportError:
    _requests = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("wechat_uploader")

# 微信视频号发表地址
WECHAT_CREATE_URL = "https://channels.weixin.qq.com/platform/post/create"
WECHAT_POST_LIST_URL = "https://channels.weixin.qq.com/platform/post/list"

# 提交后跳转作品列表只说明视频号已接收，不代表转码/审核完成或对外可见。
# 管线收到此退出码后必须保留证据、进入审核中，并禁止自动重传。
EXIT_SUBMITTED_FOR_REVIEW = 6
EXIT_MANAGEMENT_UNCERTAIN = 7
EXIT_MANAGEMENT_REJECTED = 8
EXIT_MANAGEMENT_NOT_FOUND = 9

MANAGEMENT_PUBLISHED = "PUBLISHED"
MANAGEMENT_UNDER_REVIEW = "UNDER_REVIEW"
MANAGEMENT_REJECTED = "REJECTED"
MANAGEMENT_NOT_FOUND = "NOT_FOUND"
MANAGEMENT_UNCERTAIN = "UNCERTAIN"


def _default_cover_provenance_path(cover_file: Path) -> Path:
    """返回与封面同名绑定的来源清单路径。"""
    return cover_file.with_name(f"{cover_file.stem}_provenance.json")


def _is_dedicated_cover(cover_file: Path, provenance_file: Path) -> bool:
    """仅接受哈希绑定、非视频帧且无大面积遮罩版式证明的专门生成封面。"""
    return validate_dedicated_cover_file(cover_file, provenance_file)


def _is_playwright_target_closed(exc: BaseException) -> bool:
    """识别 Playwright 页面/上下文/浏览器被外部关闭的发布未确认场景。"""
    if TargetClosedError and isinstance(exc, TargetClosedError):
        return True
    message = str(exc)
    return (
        "Target page, context or browser has been closed" in message
        or "Target closed" in message
    )


def _capture_wechat_evidence(page, evidence_dir: Path, name: str) -> None:
    """保留封面和提交页证据；采集失败不改变已验证的页面状态。"""
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(evidence_dir / f"{name}.png"), full_page=True)
    except Exception as exc:
        logger.warning("Failed to capture WeChat evidence %s: %s", name, exc)


def _collect_management_cards(page) -> dict[str, dict[str, str]]:
    """读取作品管理页已暴露的原生记录标识；不以标题搜索或推断记录。"""
    try:
        records = page.locator("[data-post-id], [data-id], a[href]").evaluate_all(
            '''nodes => {
                const found = new Map();
                const idFromHref = href => {
                    try {
                        const url = new URL(href, window.location.href);
                        for (const key of ['post_id', 'postId', 'video_id', 'videoId', 'object_id', 'objectId']) {
                            const value = url.searchParams.get(key);
                            if (value) return value;
                        }
                        const match = url.pathname.match(/\\/(?:post|video|content)\\/(?:detail\\/)?([A-Za-z0-9_-]{6,})/);
                        return match ? match[1] : '';
                    } catch (_) { return ''; }
                };
                for (const node of nodes) {
                    const link = node.tagName === 'A' ? node : node.querySelector('a[href]');
                    const id = node.getAttribute('data-post-id') || node.getAttribute('data-id') ||
                        node.dataset?.postId || node.dataset?.id || (link ? idFromHref(link.href) : '');
                    if (!id) continue;
                    const card = node.closest('[data-post-id], [data-id], [class*=card], li, tr') || node.parentElement;
                    const text = (card?.innerText || node.innerText || '').trim();
                    if (!text) continue;
                    found.set(String(id), {post_id: String(id), url: link?.href || '', text});
                }
                return Array.from(found.values());
            }'''
        )
    except Exception as exc:
        logger.warning("Unable to read platform record identifiers from management page: %s", exc)
        return {}
    return {
        str(record["post_id"]): {
            "platform_post_id": str(record["post_id"]),
            "platform_url": str(record.get("url") or ""),
            "card_text": str(record.get("text") or ""),
        }
        for record in records
        if record.get("post_id")
    }


def resolve_submission_platform_identity(
    before: dict[str, dict[str, str]], after: dict[str, dict[str, str]], expected_title: str,
) -> dict[str, str] | None:
    """仅当同次提交产生唯一新增平台 ID 且完整标题一致时返回精确绑定结果。"""
    if not expected_title:
        return None
    introduced_ids = set(after) - set(before)
    if len(introduced_ids) != 1:
        return None
    record = after[next(iter(introduced_ids))]
    normalized_title = re.sub(r"\s+", "", expected_title)
    card_title_lines = {
        re.sub(r"\s+", "", line)
        for line in str(record.get("card_text") or "").splitlines()
        if line.strip()
    }
    if normalized_title not in card_title_lines:
        return None
    return {
        "platform_post_id": record["platform_post_id"],
        "platform_url": record.get("platform_url", ""),
        "matched_by": "same_session_before_after_platform_id_delta_and_exact_title",
    }


def _write_submission_receipt(evidence_dir: Path, receipt: dict[str, str]) -> None:
    """原子写入提交绑定回执，供管线只按平台原生 ID 维护账本。"""
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = evidence_dir / "submission_receipt.json"
        temporary_path = receipt_path.with_suffix(".json.tmp")
        temporary_path.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary_path.replace(receipt_path)
    except Exception as exc:
        logger.warning("Failed to persist WeChat submission identity receipt: %s", exc)


def _load_management_cards(page) -> tuple[dict[str, dict[str, str]], bool]:
    """打开作品管理页并读取已加载卡片；失败返回 false，调用方必须拒绝绑定。"""
    try:
        page.goto(WECHAT_POST_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15_000)
        page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.warning("Unable to load management page for exact submission binding: %s", exc)
        return {}, False
    if "/post/list" not in page.url:
        return {}, False
    return _collect_management_cards(page), True


def classify_management_publication(card_text: str) -> str:
    """将作品管理页卡片文字归一到可终结的平台状态。"""
    text = re.sub(r"\s+", "", card_text or "")
    if any(marker in text for marker in ("审核未通过", "审核不通过", "未通过", "已驳回", "违规", "已删除", "不可见")):
        return MANAGEMENT_REJECTED
    if any(marker in text for marker in ("已发表", "发表成功", "已发布", "公开可见")):
        return MANAGEMENT_PUBLISHED
    if any(marker in text for marker in ("审核中", "审核通过", "处理中", "待审核", "转码中")):
        return MANAGEMENT_UNDER_REVIEW
    return MANAGEMENT_UNCERTAIN


def _search_management_title(page, expected_title: str) -> bool:
    """优先使用作品管理页搜索框；找不到搜索控件时不报告“未找到”。"""
    for selector in (
        "input[placeholder*='标题']",
        "input[placeholder*='搜索']",
        "input[placeholder*='作品']",
        "input[type='search']",
    ):
        try:
            locator = page.locator(selector)
            if locator.count() and locator.first.is_visible():
                locator.first.fill(expected_title)
                locator.first.press("Enter")
                page.wait_for_timeout(1800)
                return True
        except Exception:
            continue
    return False


def _management_card_for_title(page, expected_title: str) -> tuple[str, str, str]:
    """从命中标题的卡片中提取状态文本及平台记录标识，避免用整页状态误判。"""
    title_locator = page.get_by_text(expected_title, exact=True)
    if title_locator.count() == 0:
        title_locator = page.get_by_text(expected_title, exact=False)
    for index in range(min(title_locator.count(), 3)):
        try:
            record = title_locator.nth(index).evaluate(
                """node => {
                    let current = node;
                    for (let depth = 0; current && depth < 7; depth += 1, current = current.parentElement) {
                        const text = (current.innerText || '').trim();
                        if (text.length >= 8 && text.length <= 3000) {
                            const link = current.querySelector('a[href]');
                            const postId = current.getAttribute('data-id') ||
                                current.getAttribute('data-post-id') || current.dataset?.id || current.dataset?.postId || '';
                            return { text, postId, url: link ? link.href : '' };
                        }
                    }
                    return { text: '', postId: '', url: '' };
                }"""
            )
            if record and expected_title in (record.get("text") or ""):
                return record.get("text") or "", record.get("postId") or "", record.get("url") or ""
        except Exception:
            continue
    return "", "", ""


def verify_management_publication(page, evidence_root: Path, expected_title: str) -> tuple[str, str, str]:
    """只读核对作品管理页，返回状态、平台记录 ID 与可追溯 URL。"""
    page.goto(WECHAT_POST_LIST_URL, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    if "/post/list" not in page.url:
        _capture_wechat_evidence(page, evidence_root, "management_uncertain")
        return MANAGEMENT_UNCERTAIN, "", ""

    searched = _search_management_title(page, expected_title)
    card_text, post_id, post_url = _management_card_for_title(page, expected_title)
    if card_text:
        state = classify_management_publication(card_text)
        _capture_wechat_evidence(page, evidence_root, f"management_{state.lower()}")
        return state, post_id, post_url

    try:
        body_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        body_text = ""
    if searched and any(marker in body_text for marker in ("暂无数据", "暂无内容", "暂无作品", "未找到", "没有找到")):
        _capture_wechat_evidence(page, evidence_root, "management_not_found")
        return MANAGEMENT_NOT_FOUND, "", ""

    _capture_wechat_evidence(page, evidence_root, "management_uncertain")
    return MANAGEMENT_UNCERTAIN, "", ""


def verify_management_publication_by_id(page, evidence_root: Path, platform_post_id: str) -> tuple[str, str]:
    """只按已绑定的原生记录 ID 回查平台状态；找不到时保持不可判定，不补发。"""
    cards, loaded = _load_management_cards(page)
    record = cards.get((platform_post_id or "").strip()) if loaded else None
    if not record:
        _capture_wechat_evidence(page, evidence_root, "management_uncertain")
        return MANAGEMENT_UNCERTAIN, ""
    state = classify_management_publication(record.get("card_text", ""))
    _capture_wechat_evidence(page, evidence_root, f"management_{state.lower()}")
    return state, record.get("platform_url", "")


def _find_wechat_cover_dialog(page):
    """只接受明确属于封面编辑的可见范围，拒绝向发布页全局 input 注入文件。"""
    selectors = [
        ".edit-cover-dialog-container",
        "[role='dialog']:has-text('上传封面')",
        ".weui-desktop-dialog:has-text('上传封面')",
        ".weui-desktop-dialog:has-text('封面')",
    ]
    for selector in selectors:
        try:
            dialogs = page.locator(selector)
            for index in range(dialogs.count()):
                dialog = dialogs.nth(index)
                if dialog.is_visible():
                    return dialog
        except Exception as exc:
            logger.debug("Cover dialog selector %s unavailable: %s", selector, exc)
    return None


def _wait_for_wechat_cover_dialog_to_close(page, attempts: int = 20) -> bool:
    """等待平台保存封面并关闭编辑弹层，避免固定短等待误判。"""
    for _ in range(attempts):
        if not _find_wechat_cover_dialog(page):
            return True
        page.wait_for_timeout(1_000)
    return not _find_wechat_cover_dialog(page)


def _wechat_cover_preview_signatures(container) -> frozenset[str]:
    """读取封面卡片内图片与背景图地址，覆盖视频号的两种预览渲染。"""
    signatures: set[str] = set()
    try:
        media_sources = container.locator("*").evaluate_all(
            """elements => elements.flatMap(element => {
                const sources = [];
                if (element instanceof HTMLImageElement && element.currentSrc) {
                    sources.push(`img:${element.currentSrc}`);
                }
                const background = getComputedStyle(element).backgroundImage;
                if (background && background !== 'none') {
                    sources.push(`background:${background}`);
                }
                return sources;
            })"""
        )
        signatures.update(source for source in media_sources if source)
    except Exception as exc:
        logger.debug("Unable to read WeChat cover preview signature: %s", exc)
    return frozenset(signatures)


def _wechat_cover_preview_visual_signature(container) -> str | None:
    """对可见封面卡片取视觉指纹，作为同 URL 刷新场景的受限兜底。"""
    try:
        return hashlib.sha256(container.screenshot()).hexdigest()
    except Exception as exc:
        logger.debug("Unable to capture WeChat cover preview visual signature: %s", exc)
        return None


def _is_wechat_cover_applied(
    page,
    cover_card,
    before_signatures: frozenset[str],
    before_visual_signature: str | None,
    success_marker_observed: bool = False,
) -> bool:
    """确认封面弹层关闭、预览实际变化且本轮操作出现平台确认。"""
    if _find_wechat_cover_dialog(page):
        logger.error("Cover editor remains visible after confirmation.")
        return False
    after_signatures = _wechat_cover_preview_signatures(cover_card)
    after_visual_signature = _wechat_cover_preview_visual_signature(cover_card)
    source_changed = bool(after_signatures - before_signatures)
    visual_changed = bool(
        before_visual_signature
        and after_visual_signature
        and before_visual_signature != after_visual_signature
    )
    preview_changed = source_changed or visual_changed
    try:
        page_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        page_text = ""
    success_marker = success_marker_observed or any(
        marker in page_text
        for marker in ("封面已更新", "封面修改成功", "封面上传成功")
    )
    if not preview_changed:
        logger.error(
            "WeChat cover preview did not change after confirmation (before=%d, after=%d, visual_changed=%s).",
            len(before_signatures),
            len(after_signatures),
            visual_changed,
        )
        return False
    if not success_marker:
        logger.error("WeChat did not show a cover-update success marker after confirmation.")
        return False
    logger.info(
        "WeChat cover application verified (success_marker=%s, source_changed=%s, visual_changed=%s).",
        success_marker,
        source_changed,
        visual_changed,
    )
    return True


def _has_wechat_cover_success_marker(page) -> bool:
    """读取平台明确的封面更新提示，供人工视觉核验覆写复用。"""
    markers = ("封面已更新", "封面修改成功", "封面上传成功")
    # 微信的短暂 toast 有时已绘制到页面，但尚未进入 body.inner_text()。
    # 先直接查询可见文本，随后再保留正文兜底，避免把真实保存误判为失败。
    for marker in markers:
        try:
            toast = page.locator(f"text={marker}")
            if toast.count() > 0 and toast.last.is_visible():
                return True
        except Exception:
            continue
    try:
        page_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return False
    return any(marker in page_text for marker in markers)


def _stamp_login_success(state_file: Path) -> None:
    """真实跳回发布页并保存 state 后，记录本轮登录成功时间。"""
    try:
        marker = state_file.parent / "wechat_login_at.txt"
        marker.write_text(str(int(time.time())), encoding="utf-8")
        # 自动预热重登成功后允许下一登录周期再次触发。
        auto_flag = state_file.parent / "wechat_auto_relogin_started.flag"
        try:
            auto_flag.unlink()
        except FileNotFoundError:
            pass
        logger.info(f"Login success marker updated: {marker}")
    except Exception as e:
        logger.warning(f"Failed to update login success marker: {e}")


def _select_collection(page, collection_name: str) -> bool:
    """在微信视频号助手页面选择视频合集，若不存在则自动新建。

    # [Claude_Sonnet_4.6_Thinking_planning] v1.9.0 - 5轮DOM探针实证重写
    # 真实 DOM 结构（微信视频号助手发布页）：
    #
    #  div.post-album-display-wrap      ← 点击展开触发器
    #  div.filter-wrap                  ← 展开后面板
    #    div.common-option-list-wrap
    #      div.option-item [.active]    ← 每个合集项（.active=已选中）
    #        div.item
    #          div.name   "合集名"
    #          div.desc   "共N个内容"
    #    div.create
    #      <a>创建新合集</a>             ← 新建按钮
    #
    # 新建后弹出 .weui-desktop-dialog 对话框（与旧代码一致）
    """
    if not collection_name:
        return True

    logger.info(f"Setting collection: {collection_name!r}")

    # ── Step 1: 找触发器并展开 ─────────────────────────────────────────────
    trigger = page.locator(".post-album-display-wrap").first
    if trigger.count() == 0:
        # 兜底：通过「添加到合集」标签找到相邻的显示区
        trigger = page.locator("text=添加到合集").locator(
            "xpath=following-sibling::div//*[contains(@class,'post-album-display')]"
        ).first
    if trigger.count() == 0:
        logger.warning("Could not find collection trigger (.post-album-display-wrap).")
        return False

    try:
        trigger.click(timeout=2000)
    except Exception as e:
        logger.error(f"Failed to click collection trigger: {e}")
        return False

    # ── Step 2: 等待面板展开（以「创建新合集」出现为信号）──────────────────
    try:
        page.wait_for_selector("text=创建新合集", timeout=5000)
        logger.info("Collection dropdown opened.")
    except Exception:
        logger.warning("Collection dropdown did not open within 5s.")
        return False
    page.wait_for_timeout(300)  # 等动画稳定

    # ── Step 3: 在 .option-item 中查找目标合集 ─────────────────────────────
    # [BugFix] 列表实际位于 .filter-wrap；旧的 .post-album-wrap 已不在当前 DOM。
    # 使用严格文本匹配，避免 "AI" 误命中 "AI如何重塑电网" 等前缀合集。
    def _find_item(name: str):
        return page.locator(
            ".filter-wrap .option-item",
            has=page.get_by_text(name, exact=True),
        ).first

    # [Gemini_3.5_Flash_planning] 循环等待最多 3 秒，防止因为微信异步拉取列表导致误判“合集不存在”
    target_item = None
    for attempt in range(10):
        temp_item = _find_item(collection_name)
        if temp_item.count() > 0:
            target_item = temp_item
            break

        page.wait_for_timeout(300)

    # ── Step 4a: 已存在 → 选中（含去重检测）──────────────────────────────
    if target_item and target_item.count() > 0:
        item_class = target_item.get_attribute("class") or ""
        if "active" in item_class:
            # 已经选中，去重直接返回
            logger.info(f"Collection {collection_name!r} already active (dedup). Closing.")
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            return True

        logger.info(f"Collection {collection_name!r} found. Selecting...")
        try:
            target_item.click(timeout=2000)
        except Exception as e:
            logger.warning(f"Click on collection item failed: {e}, trying JS fallback...")
            try:
                target_item.evaluate("node => node.click()")
            except Exception as e2:
                logger.error(f"JS click also failed: {e2}")
                return False

        # 只有 active 状态被页面确认，才允许后续发表。
        for _ in range(10):
            page.wait_for_timeout(200)
            item_class_after = target_item.get_attribute("class") or ""
            if "active" in item_class_after:
                logger.info(f"Successfully selected collection {collection_name!r}.")
                return True
        logger.error(f"Collection {collection_name!r} click was not reflected as active.")
        page.keyboard.press("Escape")
        return False

    # ── Step 4b: 不存在 → 创建新合集 ─────────────────────────────────────
    logger.info(f"Collection {collection_name!r} not in list. Creating new...")

    # 实证 HTML: <div class="create"><a data-v-021f92ab="">创建新合集 </a></div>
    create_btn = page.locator(".filter-wrap .create a").first
    if create_btn.count() == 0:
        create_btn = page.get_by_text("创建新合集").first
    if create_btn.count() == 0:
        logger.warning("Could not find '创建新合集' button.")
        page.keyboard.press("Escape")
        return False

    # [Gemini_3.5_Flash_planning] 优化创建按钮的滚动与 JS 点击兜底
    try:
        create_btn.scroll_into_view_if_needed(timeout=2000)
        create_btn.click(timeout=2000)
    except Exception as e:
        logger.warning(f"Failed to click '创建新合集' via standard click: {e}, trying JS fallback...")
        try:
            create_btn.evaluate("node => node.click()")
        except Exception as e2:
            logger.error(f"JS click on '创建新合集' also failed: {e2}")
            page.keyboard.press("Escape")
            return False

    page.wait_for_timeout(500)

    # ── Step 5: 填写新建 Modal ─────────────────────────────────────────────
    # [Claude_Sonnet_4.6_Thinking_planning] v2.0.0 bugfix:
    # is_visible() 在 CSS transition 期间可能误报 False，改用 wait_for_selector
    try:
        page.wait_for_selector(".weui-desktop-dialog", state="visible", timeout=5000)
    except Exception:
        logger.warning("Collection creation dialog did not appear within 5s.")
        # 可能有残留遮罩，按 Escape 清理
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False
    modal = page.locator(".weui-desktop-dialog").first

    logger.info("New collection creation dialog detected.")
    page.screenshot(path="output/debug_collection_dialog.png")

    input_box = modal.locator(
        "input[type='text'], input[placeholder*='合集名称'], input[placeholder*='标题'], input"
    ).first
    if input_box.count() == 0:
        logger.warning("No input box in creation dialog.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False

    import re as _re
    cleaned_name = _re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]', '', collection_name).strip()[:15]
    logger.info(f"Filling dialog with cleaned name: {cleaned_name!r}")

    input_box.fill(cleaned_name)
    page.wait_for_timeout(500)

    confirm_btn = None
    for bt in ["确定", "保存", "创建", "确认"]:
        btn = modal.locator(f"button:has-text('{bt}')").first
        if btn.count() > 0 and btn.is_visible():
            confirm_btn = btn
            break

    if not confirm_btn:
        logger.warning("No confirm button found in creation dialog.")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        return False

    ok = human_click(page, confirm_btn)
    if not ok:
        confirm_btn.evaluate("node => node.click()")
    logger.info("Clicked confirm button in new collection dialog.")
    page.wait_for_timeout(1500)
    page.screenshot(path="output/debug_collection_after_create.png")

    # ── Step 6: 新建后重新展开并回选，确认合集确实绑定到当前作品 ──────────────
    # 创建成功并不等于当前发布表单已绑定；先关闭残留面板，再按正常路径重新打开。
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    try:
        trigger.click(timeout=2000)
        page.wait_for_selector("text=创建新合集", timeout=5000)
    except Exception as e:
        logger.error(f"Created collection but could not reopen collection list: {e}")
        return False

    new_item = None
    for _ in range(10):
        new_item = _find_item(cleaned_name)
        if new_item.count() > 0:
            break
        page.wait_for_timeout(300)
    if not new_item or new_item.count() == 0:
        logger.error(f"Created collection {cleaned_name!r} was not found in refreshed list.")
        page.keyboard.press("Escape")
        return False

    if "active" not in (new_item.get_attribute("class") or ""):
        try:
            new_item.click(timeout=2000)
        except Exception:
            try:
                new_item.evaluate("node => node.click()")
            except Exception as e:
                logger.error(f"Could not select created collection {cleaned_name!r}: {e}")
                page.keyboard.press("Escape")
                return False

    for _ in range(10):
        page.wait_for_timeout(200)
        if "active" in (new_item.get_attribute("class") or ""):
            logger.info(f"Successfully bound newly created collection {cleaned_name!r}.")
            return True
    logger.error(f"Created collection {cleaned_name!r} was not reflected as active.")
    page.keyboard.press("Escape")
    return False


def _collection_binding_confirmed(page, collection_name: str | None) -> bool:
    """合集为可选字段；一旦要求绑定，必须由选择器给出确认结果。"""
    return not collection_name or _select_collection(page, collection_name)

# 发布表单的成功提示或跳转列表，只能证明提交已受理；平台仍可能显示“处理中”。
# 因此此函数仅用于区分提交结果是否得到平台响应，不能作为公开发布的最终证明。
def classify_publish_result(redirected: bool, page_content: str, draft: bool = False) -> bool:
    """判定发表/存草稿是否已获得提交响应。

    Args:
        redirected: 发表后是否跳转到 /post/list（仅代表已提交）。
        page_content: 未跳转时的页面文本（降级判据）。
        draft: 是否为存草稿模式（成功文案不同）。

    Returns:
        True 仅当平台给出提交响应；公开视频仍须作品管理页最终确认。
    """
    content = page_content or ""
    if "不成功" in content:  # 明确的失败文案，直接否决
        return False
    positives = ("保存草稿成功", "保存成功") if draft else ("发表成功", "发布成功")
    return any(k in content for k in positives)


def _wait_and_save_login(page, context, state_file: Path, qr_path: Path | None = None) -> None:
    """等待登录回到发布页，保存 Playwright state 和登录成功时间戳。"""
    page.wait_for_url("**/post/create", timeout=600000)
    logger.info("Login detected. Saving session...")
    context.storage_state(path=str(state_file))
    _stamp_login_success(state_file)
    logger.info(f"Session saved to: {state_file}")
    if qr_path and qr_path.exists():
        try:
            qr_path.unlink()
        except Exception:
            pass


def _click_visible_frame_button(page, text: str, timeout: int = 3000) -> bool:
    """在主页面与跨域登录 iframe 中点击指定可见按钮。"""
    for fr in page.frames:
        try:
            loc = fr.locator("button:visible").filter(has_text=text).first
            if loc.count() > 0:
                loc.click(timeout=timeout)
                logger.info(f"Clicked visible login button {text!r} in frame={fr.url[:80]!r}")
                return True
        except Exception as e:
            logger.debug(f"Login button {text!r} not usable in frame={fr.url[:80]!r}: {e}")
    return False


def _try_wechat_quick_login(page, desktop_auth: WeChatDesktopAuthWatcher | None = None,
                            timeout_ms: int = 30_000) -> bool:
    """新版 open.weixin.qq.com 登录 iframe：完成快捷登录及资料授权。"""
    try:
        if not _click_visible_frame_button(page, "微信快捷登录"):
            return False
        # 原生 WeChat 授权弹窗由上述网页点击触发；必须随后才启动监听，避免
        # 把有限超时耗在 iframe 尚未创建授权请求的阶段。
        if desktop_auth:
            desktop_auth.start()

        # 点击“微信快捷登录”后，微信会在同一网页 iframe 显示「视频号创作平台
        # 申请使用你的昵称、头像」的二次确认。它不是手机扫码/手机确认；若不点
        # 「允许」，旧逻辑会等到超时后错误降级到二维码，导致单手机远程值守卡住。
        # 限定先确认授权文案存在，再点完全匹配的「允许」，避免误点发布页上无关按钮。
        for _ in range(20):
            for fr in page.frames:
                try:
                    request_text = fr.get_by_text("视频号创作平台申请使用", exact=False)
                    if request_text.count() == 0 or not request_text.first.is_visible():
                        continue
                    allow = fr.get_by_role("button", name="允许", exact=True)
                    if allow.count() > 0 and allow.first.is_visible():
                        allow.first.click(timeout=3000)
                        logger.info("Approved WeChat Channels nickname/avatar authorization.")
                        break
                except Exception as e:
                    logger.debug(f"WeChat profile authorization not ready in frame={fr.url[:80]!r}: {e}")
            else:
                page.wait_for_timeout(500)
                continue
            break

        try:
            page.wait_for_url("**/post/create", timeout=timeout_ms)
            logger.info("WeChat quick authorization login succeeded.")
            return True
        except Exception as e:
            logger.warning(f"WeChat quick authorization did not finish within {timeout_ms / 1000:.0f}s: {e}")
            return False
    finally:
        if desktop_auth:
            desktop_auth.stop()


def _capture_wechat_login_qr(page, qr_path: Path) -> bool:
    """捕获可扫二维码；若新版快捷登录页挡住二维码，则先切到普通二维码模式。"""
    qr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(qr_path))
        logger.info("Login fallback full-page screenshot saved before QR crop attempt.")
    except Exception as e_full:
        logger.warning(f"Failed to save login fallback full-page screenshot: {e_full}")

    # 新版 open.weixin.qq.com iframe 默认展示快捷登录；点“使用其他头像...”后二维码才可见。
    if _click_visible_frame_button(page, "使用其他头像、昵称或账号", timeout=3000):
        page.wait_for_timeout(1000)

    qr_selectors = ["img.qrcode", ".login-qr img", ".qr-code img", "img[src*='qr']", ".qrcode"]
    for fr in page.frames:
        for qr_sel in qr_selectors:
            try:
                qr_el = fr.locator(qr_sel)
                for idx in range(qr_el.count()):
                    candidate = qr_el.nth(idx)
                    if not candidate.is_visible(timeout=500):
                        continue
                    candidate.screenshot(path=str(qr_path))
                    logger.info(f"QR captured (visible cropped) via frame={fr.url[:40]!r} sel={qr_sel!r} idx={idx}")
                    return True
            except Exception:
                continue

    try:
        page.screenshot(path=str(qr_path))
        logger.info("QR full-page screenshot (fallback, Always-save).")
    except Exception as e_full:
        logger.warning(f"Failed to save final QR fallback screenshot: {e_full}")
    return False


def run_uploader(
    video_path: str = None,
    copy_path: str = None,
    state_path: str = "output/wechat_state.json",
    login_only: bool = False,
    headless: bool = True,
    draft: bool = False,
    title_path: str = None,      # 短标题文件（6-16 字，匹配微信平台真实限制）
    cover_path: str = None,      # 封面图文件 (JPEG)
    cover_provenance_path: str = None,  # 专门生成封面来源清单（哈希绑定）
    category_path: str = None,   # 分类文件
    collection: str = None,      # 新增：微信合集名称
    relogin: bool = False,       # [Claude_Opus_4.8] 强制重登：忽略现有会话→走登录页出二维码（成功才覆盖 state）
    fail_fast_login: bool = False,  # 自动管线使用：登录失效立即返回，不等待二维码
    evidence_dir: str = None,
    cover_manually_verified: bool = False,
    declare_original: bool = True,
    verify_only: bool = False,
    platform_post_id: str = None,
) -> int:
    """运行 Playwright 微信上传自动化"""

    state_file = Path(state_path)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_root = Path(evidence_dir) if evidence_dir else Path("output") / "wechat_evidence"

    if verify_only:
        if not (platform_post_id or "").strip():
            logger.error("作品管理页回查必须提供已绑定的平台原生 post_id；标题匹配已永久停用。")
            return 1
        video_abs = copy_text = cover_abs = category = collection = None
    elif not login_only:
        if not video_path or not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return 1
        if not copy_path or not Path(copy_path).exists():
            logger.error(f"Copy text file not found: {copy_path}")
            return 1
        if not cover_path:
            logger.error("A dedicated non-frame cover is required; refusing platform default video frame.")
            return 1
        cover_file = Path(cover_path)
        if not cover_file.is_file():
            logger.error(f"Requested cover file not found: {cover_path}")
            return 1
        provenance_file = (
            Path(cover_provenance_path)
            if cover_provenance_path else _default_cover_provenance_path(cover_file)
        )
        if not _is_dedicated_cover(cover_file, provenance_file):
            logger.error(
                "Requested cover is missing valid dedicated non-frame provenance: cover=%s provenance=%s",
                cover_file,
                provenance_file,
            )
            return 1
        video_abs  = str(Path(video_path).resolve())
        copy_text  = Path(copy_path).read_text(encoding="utf-8")
        short_title = (
            Path(title_path).read_text(encoding="utf-8").strip()
            if title_path and Path(title_path).exists() else None
        )
        cover_abs  = (
            str(Path(cover_path).resolve())
            if cover_path and Path(cover_path).exists() else None
        )
        category   = (
            Path(category_path).read_text(encoding="utf-8").strip()
            if category_path and Path(category_path).exists() else None
        )
        logger.info(f"short_title={short_title!r}  category={category!r}  collection={collection!r}  cover={'yes' if cover_abs else 'no'}")
    else:
        video_abs = copy_text = short_title = cover_abs = category = collection = None
        # [Claude_Opus_4.8] 不再强制 headless=False。--login-only 现遵循传入的 headless：
        # headless 时走下方「截图 QR → 发 Telegram / Web UI 浮层」远程扫码分支（与上传流登录同路径，
        # 已验证可达），实现「登录态丢失后经 Telegram 主动获取二维码」；本机当面登录用 --no-headless 显式弹窗。

    with sync_playwright() as p:
        logger.info("Launching browser...")
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-web-security",
                "--no-sandbox",
                # 反检测：隐藏 Headless 特征
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
                # [BugFix] 禁用代理，防止 Playwright 走海外节点导致微信异地登录强制掉线
                "--no-proxy-server",
            ]
        )

        # 加载 Cookie 状态
        context_opts = {
            "viewport": {"width": 1280, "height": 800},
            # 使用真实 Chrome UA（与保存 Session 时一致）
            "user_agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        }
        if relogin:
            # [Claude_Opus_4.8] 强制重登：不加载旧会话→必到登录页出二维码。旧 state 文件**不删**，
            # 仅在扫码成功后由 context.storage_state() 覆盖；未扫码则旧会话保持有效（管线不掉线）。
            logger.info("Force-relogin: ignoring existing session, will show fresh QR.")
        elif state_file.exists():
            logger.info(f"Loading session state from: {state_file}")
            context_opts["storage_state"] = str(state_file)

        context = browser.new_context(**context_opts)

        # [Claude_Sonnet_4.6_Thinking_planning] 反检测 v2.0: 完整浏览器指纹伪造
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => false });
            window.chrome = {
                runtime: {},
                loadTimes: function(){},
                csi: function(){},
                app: {}
            };
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN','zh','en'] });
            const _oq = window.navigator.permissions.query;
            window.navigator.permissions.query = (p) =>
                p.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : _oq(p);
            delete window.__playwright;
            delete window.__pw_manual;
            delete window._phantom;
        """)

        page = context.new_page()

        target_url = WECHAT_POST_LIST_URL if verify_only else WECHAT_CREATE_URL
        expected_route = "/post/list" if verify_only else "/post/create"
        logger.info("Navigating to WeChat Channels page: %s", target_url)
        page.goto(target_url, wait_until="domcontentloaded")
        # 等待页面完全渲染（Vue SPA 需额外时间）
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(5000)

        # 调试截图：永远保存，方便排查 headless 登录状态
        dbg_pre = state_file.parent / "debug_pre_login_check.png"
        try:
            page.screenshot(path=str(dbg_pre))
            logger.info(f"Pre-login-check screenshot: {dbg_pre}")
        except Exception:
            pass

        # ── 登录状态检测（URL 优先，防止 Vue SPA 未渲染完触发误判）────────────
        current_url = page.url
        logger.info(f"Current URL after load: {current_url}")

        # 1st: 目标业务页已打开 → 明确已登录，跳过所有 DOM 检测
        if expected_route in current_url:
            is_login_page = False
            logger.info("Successfully authenticated via saved session (URL confirmed).")
        # 2nd: URL 明确含 login → 未登录
        elif "login" in current_url:
            is_login_page = True
            logger.warning(f"Redirected to login page: {current_url}")
        # 3rd: URL 模糊（如首页 /）→ 再等 3s 后检查 DOM
        else:
            page.wait_for_timeout(3000)
            current_url = page.url
            if expected_route in current_url:
                is_login_page = False
                logger.info("Successfully authenticated (URL confirmed after extra wait).")
            elif "login" in current_url:
                is_login_page = True
            else:
                # DOM 检测作为最后手段
                try:
                    dom_login = (
                        page.locator("text=使用微信扫码登录").is_visible(timeout=2000) or
                        page.locator(".login-box").is_visible(timeout=2000) or
                        page.locator(".login-qr").is_visible(timeout=2000)
                    )
                except Exception:
                    dom_login = False
                is_login_page = dom_login
                if is_login_page:
                    # 截图留证，方便排查是否是误判
                    dbg = state_file.parent / "debug_login_detect.png"
                    try:
                        page.screenshot(path=str(dbg))
                        logger.warning(f"Login page detected via DOM. Debug screenshot: {dbg}")
                    except Exception:
                        pass
                else:
                    logger.info("Successfully authenticated (DOM check passed).")

        if is_login_page:
            qr_path = state_file.parent / "login_qr.png"
            page.wait_for_timeout(2000)  # 等登录 iframe 渲染

            # 2026-07 新版：open.weixin.qq.com iframe 默认先显示“微信快捷登录”授权按钮。
            # 成功时无需二维码；失败时继续保留传统扫码兜底。
            login_completed = False
            desktop_quick_attempted = False
            if settings.enable_wechat_desktop_quick_login:
                desktop_quick_attempted = True
                desktop_auth = WeChatDesktopAuthWatcher(
                    settings.wechat_desktop_quick_login_timeout_seconds,
                    enable_visual_fallback=settings.enable_wechat_desktop_visual_auth_fallback,
                )
                if _try_wechat_quick_login(
                    page,
                    desktop_auth=desktop_auth,
                    timeout_ms=settings.wechat_desktop_quick_login_timeout_seconds * 1000,
                ):
                    _wait_and_save_login(page, context, state_file, qr_path)
                    login_completed = True

            if not login_completed and fail_fast_login and not login_only:
                logger.error("Login required; bounded desktop quick-login failed and fail-fast mode refuses QR wait.")
                browser.close()
                return 2  # LOGIN_REQUIRED，交由管线回写状态并告警

            if not login_completed and not desktop_quick_attempted and _try_wechat_quick_login(page):
                _wait_and_save_login(page, context, state_file, qr_path)
                login_completed = True
            elif not login_completed:
                _capture_wechat_login_qr(page, qr_path)

            if not login_completed and headless:
                # [Claude_Sonnet_4.6_Thinking_fast] P1: Telegram QR 推送登录
                # headless 无弹窗，但可截图 QR 发 Telegram，等扫码后继续上传
                tg_token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
                tg_chat_id = (
                    os.environ.get("TELEGRAM_CHAT_ID", "").strip() or
                    os.environ.get("TELEGRAM_ADMIN_IDS", "").split(",")[0].strip()
                )

                if tg_token and tg_chat_id and _requests:
                    if qr_path.exists():
                        logger.info("Headless login required. Sending QR code to Telegram...")
                        try:
                            caption = (
                                "微信视频号登录\n"
                                "请用微信扫码授权；若已通过快捷登录授权，脚本会自动继续。\n"
                                "登录成功后会保存会话并继续任务。"
                            )
                            with open(qr_path, "rb") as f:
                                resp = _requests.post(
                                    f"https://api.telegram.org/bot{tg_token}/sendPhoto",
                                    data={"chat_id": tg_chat_id, "caption": caption},
                                    files={"photo": ("qr.png", f, "image/png")},
                                    timeout=15,
                                )
                            if resp.ok:
                                logger.info("QR code sent to Telegram. Waiting for scan/authorization...")
                            else:
                                logger.warning("Telegram sendPhoto failed: HTTP %s", resp.status_code)
                        except Exception as exc:
                            # requests 异常可能包含带 Token 的 URL，日志中只保留错误类别。
                            logger.error("Failed to send QR to Telegram: %s", type(exc).__name__)

                # [Gemini_2.0_Flash_fast] 无论是否配置 TG，在 headless 模式下均挂起等待扫码（120秒内由 Web UI 扫码完成登录）
                logger.info("Waiting for WeChat login authorization (Web UI / Telegram / App)...")
                try:
                    _wait_and_save_login(page, context, state_file, qr_path)
                        
                    if tg_token and tg_chat_id and _requests:
                        try:
                            _requests.post(
                                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                                json={"chat_id": tg_chat_id, "text": "✅ 微信视频号登录成功，继续上传任务..."},
                                timeout=10,
                            )
                        except Exception:
                            pass
                except Exception as e:
                    logger.error(f"Headless WeChat login wait timed out or failed: {e}")
                    if qr_path.exists():
                        try:
                            qr_path.unlink()
                        except Exception:
                            pass
                    browser.close()
                    return 2  # 返回 LOGIN_REQUIRED
            elif not login_completed:
                logger.info("=" * 50)
                logger.info("请在弹出的浏览器窗口中完成微信快捷授权或扫码登录。")
                logger.info("=" * 50)
                try:
                    _wait_and_save_login(page, context, state_file, qr_path)
                except Exception as e:
                    logger.error(f"Login wait timed out or failed: {e}")
                    if qr_path.exists():
                        try:
                            qr_path.unlink()
                        except Exception:
                            pass
                    browser.close()
                    return 1

        if login_only:
            logger.info("Login-only mode completed successfully.")
            browser.close()
            return 0

        if verify_only:
            state, platform_url = verify_management_publication_by_id(
                page, evidence_root, platform_post_id,
            )
            try:
                context.storage_state(path=str(state_file))
                _stamp_login_success(state_file)
            except Exception as exc:
                logger.warning("精确平台 ID 回查后保存会话失败: %s", exc)
            browser.close()
            if state == MANAGEMENT_PUBLISHED:
                return 0
            if state == MANAGEMENT_UNDER_REVIEW:
                return EXIT_SUBMITTED_FOR_REVIEW
            if state == MANAGEMENT_REJECTED:
                return EXIT_MANAGEMENT_REJECTED
            logger.warning("作品管理页未找到已绑定 ID 或未能判定状态: post_id=%s", platform_post_id)
            return EXIT_MANAGEMENT_UNCERTAIN

        identity_baseline: dict[str, dict[str, str]] = {}
        identity_baseline_ready = False
        identity_page = None
        try:
            identity_page = context.new_page()
            identity_baseline, identity_baseline_ready = _load_management_cards(identity_page)
        finally:
            if identity_page:
                identity_page.close()
        if not identity_baseline_ready:
            logger.warning("Pre-submit platform-ID baseline unavailable; submission may proceed but will remain unbound.")

        # 2. 上传视频文件 ─ 三段式容错策略
        logger.info(f"Uploading video: {video_abs}")
        upload_ok = False

        # ── 策略 A：直接定位 input[type='file']（包括隐藏元素，Playwright 可设置） ──
        try:
            # 通过 JS 确认 input 数量（穿透 display:none）
            n_inputs = page.evaluate("() => document.querySelectorAll('input[type=\"file\"]').length")
            logger.info(f"Strategy A: JS found {n_inputs} file input(s)")
            if n_inputs > 0:
                file_input = page.locator("input[type='file']").first
                file_input.set_input_files(video_abs)
                logger.info("Strategy A succeeded: file set on hidden input.")
                upload_ok = True
        except Exception as e_a:
            logger.warning(f"Strategy A failed: {e_a}")

        # ── 策略 B：等待上传区域出现后再用 filechooser 事件 ──
        if not upload_ok:
            try:
                logger.info("Strategy B: waiting for upload area then using expect_file_chooser...")
                upload_selectors = [
                    "[class*='upload']:not(div>div)",
                    "button:has-text('上传视频')",
                    "button:has-text('上传')",
                    ".upload-btn", ".upload-area", ".upload-wrapper",
                    "label[for]", "[class*='Upload']",
                ]
                clicked = False
                with page.expect_file_chooser(timeout=10000) as fc_info:
                    for sel in upload_selectors:
                        try:
                            loc = page.locator(sel)
                            if loc.count() > 0 and loc.first.is_visible():
                                loc.first.click()
                                clicked = True
                                logger.info(f"Strategy B: clicked '{sel}'")
                                break
                        except Exception:
                            continue
                if clicked:
                    fc = fc_info.value
                    fc.set_files(video_abs)
                    logger.info("Strategy B succeeded: file set via file chooser.")
                    upload_ok = True
            except Exception as e_b:
                logger.warning(f"Strategy B failed: {e_b}")

        # ── 策略 C：多 selector 暴力枚举 ──
        if not upload_ok:
            try:
                logger.info("Strategy C: trying extended selector list...")
                for sel in ["input[type='file']", "input[accept*='video']",
                            "input[accept*='mp4']", "input[name*='file']"]:
                    loc = page.locator(sel)
                    if loc.count() > 0:
                        loc.first.set_input_files(video_abs)
                        logger.info(f"Strategy C succeeded with selector: {sel}")
                        upload_ok = True
                        break
            except Exception as e_c:
                logger.warning(f"Strategy C failed: {e_c}")

        if not upload_ok:
            # 截图留存，方便人工分析页面结构
            dbg_path = Path(video_abs).parent / f"debug_upload_{Path(video_abs).stem}.png"
            try:
                page.screenshot(path=str(dbg_path), full_page=True)
                logger.error(f"All upload strategies failed. Debug screenshot: {dbg_path}")
            except Exception:
                logger.error("All upload strategies failed and screenshot also failed.")
            browser.close()
            return 1
            
        # ── 3. 等待视频上传完成 ────────────
        logger.info("Waiting for video upload to complete...")
        upload_finished = False
        for i in range(60):  # 60 × 5s = 300s max
            page.wait_for_timeout(5000)
            content = page.content()
            if "上传成功" in content or "已上传100%" in content or "上传完成" in content:
                logger.info("Upload complete (text detected).")
                upload_finished = True
                break
            publish_btn = page.locator("button:has-text('发表')").first
            if publish_btn.count() > 0:
                is_disabled = (
                    publish_btn.get_attribute("disabled") is not None or
                    "disabled" in (publish_btn.get_attribute("class") or "").lower()
                )
                if not is_disabled:
                    logger.info("Upload complete (Publish button enabled).")
                    upload_finished = True
                    break
            logger.info(f"Still uploading... ({i+1}/60)")
        if not upload_finished:
            logger.error("Upload verification timed out (5 min). Stopping before copy, cover, and publish.")
            _capture_wechat_evidence(page, evidence_root, "upload_timeout")
            browser.close()
            return 1

        # ── 4. 填写视频文案/描述 (等上传完成页面稳定后再填) ────────────
        logger.info("Writing copy to description field...")
        desc_input = None
        for selector in [".input-editor", "div[contenteditable='true']", "textarea", ".editor", ".description-textarea"]:
            try:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    desc_input = loc.first
                    break
            except Exception:
                continue
                
        if desc_input:
            try:
                desc_input.focus()
                page.keyboard.press("Meta+A")
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
                page.keyboard.insert_text(copy_text)
                logger.info("Successfully pasted copy description.")
            except Exception as e:
                logger.error(f"Failed to write description: {e}")
        else:
            logger.warning("Could not find description input selector, trying fallback click on text...")
            try:
                page.locator("text=添加描述").click()
                page.keyboard.insert_text(copy_text)
            except Exception as e2:
                logger.error(f"Fallback description fill failed: {e2}")

        # 上传后截图，确认页面状态
        dbg_post = state_file.parent / "debug_post_upload.png"
        try:
            page.screenshot(path=str(dbg_post))
            logger.info(f"Post-upload screenshot: {dbg_post}")
        except Exception:
            pass

        # [BugFix] 每次上传成功后及时保存最新的 storage_state，保存刷新的 Cookie / Token
        try:
            context.storage_state(path=str(state_file))
            _stamp_login_success(state_file)
            logger.info(f"Session state updated and saved to: {state_file}")
        except Exception as e:
            logger.warning(f"Failed to update session state after upload: {e}")

        # ── 4. 短标题（视频上传后字段才出现）────────────────────────────────
        # 规则来源：WeChat JS 源码 345.509f6449.js → parseShortTitle() + handleBlur()
        # 允许字符正则：/^[\u2103\u4E00-\u9FA5A-Za-z0-9《》""":：+?？%\s]+$/
        #   ℃ 中文 英文 数字 《》 全角引号 全角冒号 : + ? ？ % 空格
        # 字数：min=6  max=16（.length，即 JS 的字符串长度）
        # 禁止：逗号 , 句号 . 感叹号 ! 其他半角标点（逗号可用空格代替）
        # 输入清洗：去除零宽字符 \u200B

        if short_title:
            import re as _re
            # [Claude_Sonnet_4.6_Thinking_fast] 规则来自 WeChat JS 源码 345.509f6449.js
            # parseShortTitle: /^[\u2103\u4E00-\u9FA5A-Za-z0-9\u300A\u300B\u201C\u201D:+?%\s]+$/
            # handleBlur: length < 6 → "标题至少6个字"; length > 16 → 超过限制
            # handleInput: .replace(/\u200B/g, "")

            # Step 1: 清洗零宽字符
            short_title_clean = short_title.replace('\u200B', '').replace('\uFEFF', '').strip()

            # Step 2: 字数验证
            TITLE_MIN, TITLE_MAX = 6, 16
            if len(short_title_clean) < TITLE_MIN:
                logger.warning(
                    f"Short title too short ({len(short_title_clean)} chars, min={TITLE_MIN}): "
                    f"{short_title_clean!r} — skipping."
                )
                short_title_clean = None
            elif len(short_title_clean) > TITLE_MAX:
                # [Claude_Sonnet_4.6_Thinking_planning] v1.6.0: 优雅截断替换硬截断兜底
                short_title_clean = graceful_truncate_title(short_title_clean, max_len=TITLE_MAX)
                logger.warning(f"Short title gracefully truncated to {len(short_title_clean)} chars: {short_title_clean!r}")

            # Step 3: 字符白名单验证（与 WeChat parseShortTitle 一致）
            TITLE_PAT = _re.compile(
                r'^[\u2103\u4E00-\u9FA5A-Za-z0-9'
                r'\u300A\u300B'           # 《》
                r'\u201C\u201D\u2018\u2019'  # ""''
                r'\uFF02\uFF1A\uFF1F'     # ＂：？
                r':+?%\s]+$'
            )
            if short_title_clean and not TITLE_PAT.match(short_title_clean):
                bad = [c for c in short_title_clean if not TITLE_PAT.match(c)]
                logger.warning(
                    f"Short title has forbidden chars {bad!r}: {short_title_clean!r}. "
                    "Allowed: 中文/英数/《》/全角引号/：/+/？/%/空格. 逗号→空格."
                )
                # 自动修复：逗号→空格，其余非法字符删除
                cleaned = _re.sub(r'[,，。！!；;]', ' ', short_title_clean)
                cleaned = _re.sub(
                    r'[^\u2103\u4E00-\u9FA5A-Za-z0-9'
                    r'\u300A\u300B\u201C\u201D\u2018\u2019'
                    r'\uFF02\uFF1A\uFF1F:+?%\s]',
                    '', cleaned
                ).strip()
                if TITLE_MIN <= len(cleaned) <= TITLE_MAX:
                    logger.info(f"Auto-cleaned short title: {cleaned!r}")
                    short_title_clean = cleaned
                else:
                    logger.warning(f"Cleaned title invalid (len={len(cleaned)}), skipping.")
                    short_title_clean = None

            if short_title_clean:
                logger.info(f"Setting short title: {short_title_clean!r} (len={len(short_title_clean)})")
                page.wait_for_timeout(2000)

                # DOM selector 来自真实 WeChat HTML: placeholder="概括视频主要内容，字数建议6-16个字符"
                # 组件 class: .post-short-title-wrap > mp-input > input
                filled = False
                for loc in [
                    page.locator("input[placeholder*='概括视频主要内容']"),
                    page.locator("input[placeholder*='6-16']"),
                    page.locator("input[placeholder*='短标题']"),
                    page.locator(".post-short-title-wrap input"),
                    page.locator("text=短标题").locator("xpath=..").locator("input, textarea"),
                ]:
                    try:
                        if loc.count() > 0 and loc.first.is_visible():
                            loc.first.fill(short_title_clean)
                            loc.first.blur()  # 触发 handleBlur → 字数验证
                            page.wait_for_timeout(500)
                            logger.info("Short title set via placeholder locator.")
                            filled = True
                            break
                    except Exception:
                        continue

                if not filled:
                    logger.warning("Trying JS injection for short title...")
                    result = page.evaluate(
                        """(v) => {
                            const el = document.querySelector(
                                'input[placeholder*="概括视频主要内容"],'
                                'input[placeholder*="6-16"],'
                                'input[placeholder*="短标题"]'
                            );
                            if (!el) return null;
                            const setter = Object.getOwnPropertyDescriptor(
                                HTMLInputElement.prototype, 'value'
                            )?.set;
                            setter?.call(el, v);
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.blur();
                            return el.value;
                        }""",
                        short_title_clean
                    )
                    if result:
                        logger.info(f"Short title set via JS injection: {result!r}")
                    else:
                        logger.warning("All short title strategies failed — skipping.")

        # ── 5. 封面上传 ───────────────────────────────────────────────────────
        # [Claude_Sonnet_4.6_Thinking_fast] 修复 Bug1/Bug2/Bug3：
        # 真实 UI 流程：Hover 缩略图 → 浮现"编辑"按钮 → 点击"编辑" → Modal 内点"上传封面"
        # → set_input_files 注入文件 → 等待上传完成 → 点"确定"确认应用封面
        if cover_abs:
            logger.info(f"Uploading cover: {cover_abs}")
            cover_set = False
            cover_success_marker = False
            cover_confirmed = False

            # ── Strategy A: 直接 Hover 封面缩略图，等"编辑"按钮浮现后点击（正确流程）──
            try:
                cover_card_sels = ["text=封面预览"]
                for card_sel in cover_card_sels:
                    try:
                        card_container = page.locator(card_sel).locator("xpath=..")
                        if card_container.count() == 0:
                            continue
                        cover_card = card_container.first
                        before_signatures = _wechat_cover_preview_signatures(cover_card)
                        before_visual_signature = _wechat_cover_preview_visual_signature(cover_card)
                        cover_card.hover()
                        page.wait_for_timeout(1000)

                        edit_btn = None
                        for wait_attempt in range(30):
                            for edit_root in (cover_card, cover_card.locator("xpath=..")):
                                candidates = edit_root.locator("text=编辑")
                                for index in range(candidates.count()):
                                    candidate = candidates.nth(index)
                                    if candidate.is_visible():
                                        edit_btn = candidate
                                        break
                                if edit_btn:
                                    break
                            if edit_btn:
                                break
                            logger.info("Cover preview is not editable yet (wait %ss/30s).", wait_attempt + 1)
                            page.wait_for_timeout(1000)
                        if not edit_btn:
                            logger.warning("Cover preview did not become editable within 30s.")
                            continue

                        logger.info(f"Found visible 编辑 button under: {card_sel}. Clicking...")
                        edit_btn.click(force=True)
                        page.wait_for_timeout(2000)

                        cover_dialog = _find_wechat_cover_dialog(page)
                        if not cover_dialog:
                            logger.info("Cover editor did not open yet; waiting for preview generation before retrying.")
                            for retry_attempt in range(30):
                                page.wait_for_timeout(1000)
                                try:
                                    body_text = page.locator("body").inner_text(timeout=1_000)
                                except Exception:
                                    body_text = ""
                                if "预览图生成中" in body_text:
                                    continue
                                cover_card.hover()
                                retry_buttons = cover_card.locator("text=编辑")
                                retry_button = None
                                for index in range(retry_buttons.count()):
                                    candidate = retry_buttons.nth(index)
                                    if candidate.is_visible():
                                        retry_button = candidate
                                        break
                                if not retry_button:
                                    continue
                                retry_button.click(force=True)
                                page.wait_for_timeout(1000)
                                cover_dialog = _find_wechat_cover_dialog(page)
                                if cover_dialog:
                                    logger.info("Cover editor opened after preview generation wait (%ss).", retry_attempt + 1)
                                    break
                            if not cover_dialog:
                                logger.warning("Cover editor did not open from the cover preview entry.")
                                continue

                        # Step 1: 点击"上传封面"，触发 WeChat 创建隐藏 input
                        upload_btn = None
                        for inner_sel in ["text=上传封面", "text=本地上传", ".upload-btn", ".cover-upload"]:
                            try:
                                inner_loc = cover_dialog.locator(inner_sel).last
                                if inner_loc.count() > 0 and inner_loc.is_visible():
                                    upload_btn = inner_loc
                                    logger.info(f"Found upload trigger: {inner_sel}")
                                    break
                            except Exception:
                                continue

                        if upload_btn:
                            upload_btn.click(force=True)
                            page.wait_for_timeout(1500)

                        # Step 2: 注入文件到 hidden input[type=file]
                        file_injected = False
                        for input_sel in [
                            "input[type=\'file\'][accept*=\'image\']",
                            "input[type=\'file\']",
                        ]:
                            try:
                                file_input = cover_dialog.locator(input_sel).last
                                if file_input.count() > 0:
                                    accept = (file_input.get_attribute("accept") or "").lower()
                                    if input_sel.endswith("input[type='file']") and ("video" in accept or "mp4" in accept):
                                        logger.warning("Skipping non-image file input in cover dialog: %s", accept)
                                        continue
                                    file_input.set_input_files(cover_abs)
                                    logger.info(f"Cover file injected via hidden input: {input_sel}")
                                    file_injected = True
                                    break
                            except Exception:
                                continue

                        if not file_injected:
                            logger.warning("No image file input found inside the cover editor.")
                            continue

                        # Step 3: 等待上传完成
                        page.wait_for_timeout(5000)
                        _capture_wechat_evidence(page, evidence_root, "cover_before_confirm")

                        # Step 4: 轮询等待"确认"按钮变为可点击状态，然后点击
                        # [Claude_Sonnet_4.6_Thinking_planning] P0 根因修复:
                        # 封面图上传后，微信需要几秒钟处理图片，期间"确认"按钮处于disabled状态
                        # 必须循环等待按钮从disabled变为enabled，而不是静态等待5秒就直接找
                        confirmed = False
                        logger.info("Polling for enabled confirm button in cover dialog (max 20s)...")

                        for poll_attempt in range(20):  # 最多等20秒
                            page.wait_for_timeout(1000)
                            for btn_name in ["确认", "确定", "完成"]:
                                btns = cover_dialog.locator(f"button:has-text('{btn_name}')")
                                count = btns.count()
                                for i in range(count):
                                    try:
                                        btn = btns.nth(i)
                                        if not btn.is_visible():
                                            continue
                                        # 检查是否 disabled: 属性存在且不为 None 则跳过
                                        disabled_attr = btn.get_attribute("disabled")
                                        if disabled_attr is not None:
                                            logger.info(f"  [poll {poll_attempt}] button '{btn_name}' still disabled, waiting...")
                                            continue
                                        # 额外检查: aria-disabled
                                        if btn.get_attribute("aria-disabled") == "true":
                                            continue
                                        # 确认按钮可用，人类化点击（避免 isTrusted=false 检测）
                                        ok = human_click(page, btn)
                                        if not ok:
                                            ok = dispatch_human_click_events(page, btn)
                                        if not ok:
                                            try:
                                                btn.evaluate("node => node.click()")
                                                ok = True
                                            except Exception:
                                                pass
                                        if ok:
                                            logger.info(f"[Strategy A] Cover confirmed via human_click '{btn_name}' poll={poll_attempt}")
                                            confirmed = True
                                            break
                                    except Exception as click_err:
                                        logger.warning(f"  click error: {click_err}")
                                if confirmed:
                                    break
                            if confirmed:
                                break

                        if not confirmed:
                            logger.warning("Cover confirm button not found after 20s polling — cover may not be applied!")
                            _capture_wechat_evidence(page, evidence_root, "cover_failed_confirm")
                        else:
                            if not _wait_for_wechat_cover_dialog_to_close(page):
                                logger.warning("Cover editor remained visible after save wait.")
                            _capture_wechat_evidence(page, evidence_root, "cover_after_confirm")
                            cover_confirmed = confirmed
                            cover_success_marker = _has_wechat_cover_success_marker(page)
                            cover_set = _is_wechat_cover_applied(
                                page,
                                cover_card,
                                before_signatures,
                                before_visual_signature,
                                success_marker_observed=cover_success_marker,
                            )
                        break  # 成功处理一张卡片即退出循环
                    except Exception as e_card:
                        logger.warning(f"Cover strategy A failed for card \'{card_sel}\': {e_card}")
                        continue
            except Exception as e_a:
                logger.warning(f"Cover Strategy A (hover+edit) failed: {e_a}")

            if not cover_set:
                if cover_manually_verified and cover_confirmed and not _find_wechat_cover_dialog(page):
                    logger.warning(
                        "Using operator-verified WeChat cover override after confirmed close; evidence has been retained."
                    )
                    cover_set = True
                else:
                    _capture_wechat_evidence(page, evidence_root, "cover_not_applied")
                    logger.error("Custom cover was not verified. Stopping before publish to avoid a default-cover post.")
                    browser.close()
                    return 1

        # ── 6. 原创声明 ───────────────────────────────────────────────────────
        logger.info("Checking original declaration checkbox...")
        # ═══════════════════════════════════════════════════════════════════════════
        # [Claude_Sonnet_4.6_Thinking_planning] v2.0 抗 UI 变化架构
        # 核心原则:
        #   1. 文字定位优先 (text walker) — CSS class 会变，文字内容相对稳定
        #   2. 逐层降级 (Tier 1→2→3) — 每一层都独立完整，不依赖上一层
        #   3. 轮询等待 — 永远不假设 UI 状态，等待后再检查
        #   4. 截图 + 日志 — 任何失败都留下证据
        #
        # 流程:
        #   Step A: 找到并点击"声明原创"toggle/switch/行
        #   Step B: 检测"原创权益"确认弹窗 (可能弹出)
        #   Step C: 弹窗内 (1)勾选"我已阅读" checkbox → (2)等"声明原创"按钮变蓝 → (3)点击
        # ═══════════════════════════════════════════════════════════════════════════

        def _click_original_toggle(page) -> bool:
            """Step A: 点击主界面上的原创声明 toggle。返回是否成功。"""
            # 策略 1: CSS 选择器（最快，但可能因 UI 变化失效）
            css_selectors = [
                "label:has-text('原创') input[type='checkbox']",
                "label:has-text('声明原创') input[type='checkbox']",
                "input[type='checkbox'][class*='original']",
                ".original-declaration input",
                "input[type='checkbox']:near(:text('原创'))",
                "input[type='checkbox']:near(:text('声明原创'))",
                ".weui-desktop-switch:near(:text('原创'))",
                ".weui-desktop-switch:near(:text('声明原创'))",
            ]
            for sel in css_selectors:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if 'checkbox' in sel:
                            if not loc.first.is_checked():
                                human_click(page, loc.first)
                        else:
                            human_click(page, loc.first)
                        logger.info(f"[Original-ToggleA] human_click via: {sel}")
                        return True
                except Exception:
                    pass

            # 策略 2: JS 文字遍历 (抗 CSS 变化)
            result = page.evaluate("""() => {
                const targets = ['声明原创', '原创声明', '原创'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const txt = node.textContent.trim();
                    if (!targets.includes(txt)) continue;
                    let el = node.parentElement;
                    for (let i = 0; i < 8 && el; i++) {
                        // 找 input[type=checkbox]
                        const cb = el.querySelector('input[type="checkbox"]');
                        if (cb && !cb.checked) { cb.click(); return {ok:true, method:'cb', cls:cb.className}; }
                        // 找 role=switch
                        const sw = el.querySelector('[role="switch"]');
                        if (sw) { sw.click(); return {ok:true, method:'role-switch', cls:sw.className}; }
                        // 找 class 含 switch/toggle 的元素
                        const toggleEl = el.querySelector('[class*="switch"],[class*="toggle"],[class*="Switch"],[class*="Toggle"]');
                        if (toggleEl) { toggleEl.click(); return {ok:true, method:'cls-toggle', cls:toggleEl.className}; }
                        // 最后兜底: 整行可点击
                        if (el.tagName === 'LABEL' || el.getAttribute('role') === 'button') {
                            el.click(); return {ok:true, method:'row-click', cls:el.className};
                        }
                        el = el.parentElement;
                    }
                }
                return {ok:false};
            }""")
            if result and result.get('ok'):
                logger.info(f"[Original-ToggleA] JS text-walker click: {result}")
                return True

            logger.warning("[Original-ToggleA] All strategies failed — toggle not found")
            return False

        def _handle_original_rights_dialog(page) -> bool:
            """Step B+C: 处理"原创权益"二次确认弹窗。
            流程: 检测弹窗 -> 勾选 checkbox -> 等待"声明原创"按钮变蓝 -> 点击。

            # [Claude_Sonnet_4.6_Thinking_planning] v4.0 策略库架构:
            # 设计原则: 永不丢弃历史策略，只做累积。微信可能在不同版本/设备上
            # 切换 UI 方案，历史策略随时可能重新适用。
            # CHECKBOX_STRATEGIES = 所有已知方案的有序列表，逐一尝试，
            # 以"声明原创"按钮变 enabled 作为 checkbox 已勾选的唯一客观验证。
            """
            # ── 检测弹窗 (最多等4秒) ────────────────────────────────────────────
            dialog_detected = False
            for _ in range(8):
                page.wait_for_timeout(500)
                # [Gemini_3.5_Flash_High_planning] 优先使用 Playwright 自动穿透 Shadow DOM 的定位机制进行检测
                try:
                    # 查找可见的且包含“原创权益”的文本节点或元素
                    loc = page.locator("text=原创权益").first
                    if loc.count() > 0 and loc.is_visible(timeout=100):
                        dialog_detected = True
                        logger.info("[Original-Dialog] '原创权益' dialog detected via Playwright locator")
                        page.screenshot(path="output/debug_dialog_detected.png")
                        break
                except Exception:
                    pass

                # [Gemini_3.5_Flash_High_planning] 备选：递归穿透所有 Shadow DOM 进行深度遍历检测
                found_js = page.evaluate("""() => {
                    function findTextDeep(root) {
                        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                        let node;
                        while (node = walker.nextNode()) {
                            const t = node.textContent.trim();
                            if (t === '原创权益' || t.includes('原创权益')) {
                                const el = node.parentElement;
                                if (el && el.offsetParent !== null) return true;
                            }
                        }
                        const all = root.querySelectorAll('*');
                        for (const el of all) {
                            if (el.shadowRoot) {
                                if (findTextDeep(el.shadowRoot)) return true;
                            }
                        }
                        return false;
                    }
                    return findTextDeep(document.body);
                }""")
                if found_js:
                    dialog_detected = True
                    logger.info("[Original-Dialog] '原创权益' dialog detected via Deep JS search")
                    page.screenshot(path="output/debug_dialog_detected.png")
                    break

            if not dialog_detected:
                logger.info("[Original-Dialog] No dialog -- toggle direct, no confirmation needed")
                return True

            page.wait_for_timeout(1000)  # 等动画结束

            # ── 客观验证: 声明原创按钮是否 enabled ────────────────────────────
            def _is_declare_btn_enabled():
                """以"声明原创"按钮从 disabled->enabled 作为 checkbox 已勾选的验证
                # [Gemini_3.5_Flash_High_planning] 挂载 weui-desktop-btn_disabled 类名判定微前端场景下的禁用状态"""
                for btn_text in ["\u58f0\u660e\u539f\u521b", "\u786e\u5b9a"]:
                    try:
                        btns = page.locator(f"button:has-text('{btn_text}')")
                        for i in range(btns.count()):
                            btn = btns.nth(i)
                            if not btn.is_visible():
                                continue
                            cls = btn.get_attribute("class") or ""
                            # [Gemini_3.5_Flash_High_planning] 校验 disabled 属性、aria-disabled 以及 class 中的禁用类
                            if (btn.get_attribute("disabled") is None and
                                    btn.get_attribute("aria-disabled") != "true" and
                                    "disabled" not in cls.lower() and
                                    "weui-desktop-btn_disabled" not in cls):
                                return True, btn
                    except Exception:
                        pass
                return False, None

            # ── CHECKBOX_STRATEGIES: 所有已知 UI 方案的策略库 ─────────────────
            # 规则: 永不删除，只追加。每个策略返回 True/False 表示是否成功触发点击。
            # 验证由外层统一做 (_is_declare_btn_enabled)，与策略解耦。

            def _s1_native_input_css(page):
                """S1 (v2.0遗留): 标准 input[type=checkbox] CSS 选择器
                适用: 微信使用原生 HTML checkbox 的版本"""
                for sel in [
                    ".weui-desktop-dialog input[type='checkbox']",
                    ".weui-desktop-dialog__bd input[type='checkbox']",
                    "div[role='dialog'] input[type='checkbox']",
                    "input[type='checkbox']:near(:text('\u9605\u8bfb'))",
                    "input[type='checkbox']:near(:text('\u540c\u610f'))",
                    "input[type='checkbox']",  # 页内唯一 checkbox 兜底
                ]:
                    try:
                        cb = page.locator(sel)
                        if cb.count() > 0 and cb.first.is_visible(timeout=300):
                            if cb.first.is_checked():
                                logger.info(f"[S1] Already checked via {sel}")
                                return True
                            ok = human_check(page, cb.first)
                            if ok:
                                logger.info(f"[S1] native input checked via: {sel}")
                                return True
                    except Exception:
                        pass
                return False

            def _s2_label_has_text(page):
                """S2 (v3.0): 点击包含'阅读'文字的 label 标签
                适用: 微信将 checkbox+文字 包在 label 内的版本"""
                for text_kw in ["\u6211\u5df2\u9605\u8bfb\u5e76\u540c\u610f",
                                "\u6211\u5df2\u9605\u8bfb", "\u9605\u8bfb\u5e76\u540c\u610f",
                                "\u9605\u8bfb", "\u540c\u610f"]:
                    for sel in [
                        f"label:has-text('{text_kw}')",
                        f".weui-desktop-dialog label:has-text('{text_kw}')",
                        f"[role='dialog'] label:has-text('{text_kw}')",
                        ".weui-desktop-dialog label",
                        "div[role='dialog'] label",
                    ]:
                        try:
                            loc = page.locator(sel).first
                            if loc.count() > 0 and loc.is_visible(timeout=300):
                                ok = human_click(page, loc)
                                if ok:
                                    logger.info(f"[S2] label clicked: {sel}")
                                    return True
                        except Exception:
                            pass
                return False

            def _s3_js_coord_click(page):
                """S3 (v3.0): JS 找'阅读'文字节点 -> BoundingRect -> 鼠标坐标点击
                适用: 自定义组件无法被 Playwright 选择器找到，但坐标可用"""
                rect = page.evaluate("""() => {
                    const keys = ['\u6211\u5df2\u9605\u8bfb\u5e76\u540c\u610f',
                                  '\u6211\u5df2\u9605\u8bfb', '\u9605\u8bfb\u5e76\u540c\u610f',
                                  '\u9605\u8bfb'];
                    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                    let node;
                    while (node = walker.nextNode()) {
                        const t = node.textContent.trim();
                        if (keys.some(k => t.includes(k))) {
                            let el = node.parentElement;
                            for (let i = 0; i < 6 && el; i++) {
                                if (el.offsetParent !== null) {
                                    const r = el.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) {
                                        return {x: r.left + 8, y: r.top + r.height / 2,
                                                text: t.slice(0, 30)};
                                    }
                                }
                                el = el.parentElement;
                            }
                        }
                    }
                    return null;
                }""")
                if rect:
                    import random as _rand
                    cx = rect["x"] + _rand.uniform(1, 6)
                    cy = rect["y"] + _rand.uniform(-2, 2)
                    page.mouse.move(cx, cy)
                    page.wait_for_timeout(120)
                    page.mouse.click(cx, cy)
                    logger.info(f"[S3] coord click ({cx:.0f},{cy:.0f}) '{rect.get('text','')}'")
                    return True
                return False

            def _s4_class_enum_in_container(page):
                """S4 (v3.0): 在弹窗容器内枚举所有 checkbox 类元素并点击
                适用: class 名含'checkbox'的自定义组件版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    const candidates = container.querySelectorAll(
                        'input[type="checkbox"],[class*="checkbox"],[class*="check-box"],' +
                        '[class*="Checkbox"],[role="checkbox"]'
                    );
                    for (const el of candidates) {
                        if (el.offsetParent === null) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        el.click();
                        return {ok:true, tag:el.tagName, cls:el.className.slice(0,50)};
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    logger.info(f"[S4] class enum click: {result}")
                    return True
                return False

            def _s5_label_in_container(page):
                """S5 (v3.0): 弹窗容器内找含'阅读'文字的 label 并点击
                适用: label 不被 :has-text 找到但在容器内可枚举的版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    const labels = container.querySelectorAll('label');
                    for (const lb of labels) {
                        if (lb.offsetParent !== null &&
                            (lb.innerText.includes('\u9605\u8bfb') || lb.innerText.includes('\u540c\u610f'))) {
                            lb.click();
                            return {ok:true, text:lb.innerText.slice(0,40)};
                        }
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    logger.info(f"[S5] label in container: {result}")
                    return True
                return False

            def _s6_dispatch_events_on_small_element(page):
                """S6 (新增): 对弹窗内第一个小型可见元素派发完整鼠标事件序列
                适用: 自定义组件对 click() 不响应，但响应 mousedown/mouseup 的版本"""
                result = page.evaluate("""() => {
                    const kw = '\u539f\u521b\u6743\u76ca';
                    const dialogs = [...document.querySelectorAll(
                        '[class*="dialog"],[class*="Dialog"],[class*="modal"],[role="dialog"]'
                    )].filter(el => el.offsetParent !== null && el.innerText.includes(kw));
                    const container = dialogs[0] || document.body;
                    // 找宽高 < 30px 的小元素 (通常是 checkbox 图标)
                    const all = container.querySelectorAll('*');
                    for (const el of all) {
                        if (el.offsetParent === null) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width > 5 && r.width <= 28 && r.height > 5 && r.height <= 28) {
                            return {ok:true, x: r.left + r.width/2, y: r.top + r.height/2,
                                    tag: el.tagName, cls: el.className.slice(0,40)};
                        }
                    }
                    return {ok:false};
                }""")
                if result and result.get("ok"):
                    import random as _rand
                    cx = result["x"] + _rand.uniform(-2, 2)
                    cy = result["y"] + _rand.uniform(-1, 1)
                    # 派发完整事件序列
                    page.mouse.move(cx, cy)
                    page.wait_for_timeout(80)
                    page.mouse.down()
                    page.wait_for_timeout(60)
                    page.mouse.up()
                    logger.info(f"[S6] dispatch events on small el ({cx:.0f},{cy:.0f}) {result.get('tag')} '{result.get('cls','')[:30]}'")
                    return True
                return False

            def _s7_tab_space_keyboard(page):
                """S7 (新增): 键盘 Tab + Space 触发 checkbox
                适用: 弹窗内 checkbox 获得焦点后 Space 可切换的版本"""
                try:
                    # Tab 到弹窗内元素
                    page.keyboard.press("Tab")
                    page.wait_for_timeout(100)
                    page.keyboard.press("Space")
                    logger.info("[S7] keyboard Tab+Space fired")
                    return True
                except Exception:
                    return False

            def _s8_antd_checkbox_wrapper(page):
                """S8 (新增): 点击 .ant-checkbox-wrapper 或 .ant-checkbox-inner
                适用: 微信在微前端中使用 Ant Design Checkbox 的版本
                # [Gemini_3.5_Flash_High_planning] 能够被 Playwright pierced-shadow 机制自动识别"""
                for sel in [
                    ".ant-checkbox-wrapper",
                    ".ant-checkbox-inner",
                    "label.ant-checkbox-wrapper",
                    "span.ant-checkbox-inner",
                    ".declare-body-wrapper label",
                ]:
                    try:
                        cb = page.locator(sel).first
                        if cb.count() > 0 and cb.is_visible(timeout=300):
                            ok = human_click(page, cb)
                            if ok:
                                logger.info(f"[S8] AntD checkbox clicked via: {sel}")
                                return True
                    except Exception:
                        pass
                return False

            def _s9_antd_checkbox_force_input(page):
                """S9 (新增): 强制点击隐藏的 .ant-checkbox-input
                # [Gemini_3.5_Flash_High_planning] 强制点击隐藏 input 是 Playwright 中处理不可见原生控件的推荐方式"""
                try:
                    cb = page.locator(".ant-checkbox-input").first
                    if cb.count() > 0:
                        cb.click(force=True, timeout=500)
                        logger.info("[S9] AntD hidden input force clicked")
                        return True
                except Exception:
                    pass
                return False

            def _s10_absolute_coordinate_click(page):
                """S10 (新增): 物理坐标定位点击 (基于用户建议)
                # [Gemini_3.5_Flash_High_planning] 获取元素 bounding box 后以真实鼠标坐标点击其中心点"""
                for sel in [
                    ".ant-checkbox-wrapper",
                    ".ant-checkbox-inner",
                    "span.ant-checkbox-inner"
                ]:
                    try:
                        cb = page.locator(sel).first
                        if cb.count() > 0 and cb.is_visible(timeout=300):
                            box = cb.bounding_box()
                            if box:
                                cx = box["x"] + box["width"] / 2
                                cy = box["y"] + box["height"] / 2
                                page.mouse.move(cx, cy)
                                page.wait_for_timeout(100)
                                page.mouse.click(cx, cy)
                                logger.info(f"[S10] absolute coordinate click at ({cx:.0f},{cy:.0f}) via: {sel}")
                                return True
                    except Exception as e:
                        pass
                return False

            # 策略库（按历史可靠性和通用性排序，不删除旧策略）
            CHECKBOX_STRATEGIES = [
                ("S1_native_input_css",          _s1_native_input_css),
                ("S2_label_has_text",            _s2_label_has_text),
                ("S3_js_coord_click",            _s3_js_coord_click),
                ("S4_class_enum_in_container",   _s4_class_enum_in_container),
                ("S5_label_in_container",        _s5_label_in_container),
                ("S6_dispatch_on_small_el",      _s6_dispatch_events_on_small_element),
                ("S7_tab_space_keyboard",        _s7_tab_space_keyboard),
                ("S8_antd_checkbox_wrapper",     _s8_antd_checkbox_wrapper),
                ("S9_antd_checkbox_force_input",  _s9_antd_checkbox_force_input),
                ("S10_absolute_coordinate_click", _s10_absolute_coordinate_click),
            ]

            # ── 逐策略尝试，以按钮 enabled 为验证 ───────────────────────────
            for strategy_name, strategy_fn in CHECKBOX_STRATEGIES:
                logger.info(f"[Original-Dialog] Trying {strategy_name}...")
                try:
                    triggered = strategy_fn(page)
                except Exception as e:
                    logger.warning(f"[Original-Dialog] {strategy_name} raised: {e}")
                    triggered = False

                if not triggered:
                    logger.info(f"[Original-Dialog] {strategy_name}: no element found, skipping")
                    continue

                # 等微信响应
                page.wait_for_timeout(800)
                enabled, declare_btn = _is_declare_btn_enabled()

                if enabled:
                    logger.info(f"[Original-Dialog] \u2705 {strategy_name} succeeded! '\u58f0\u660e\u539f\u521b' now enabled")
                    # 点击"声明原创"按钮
                    ok = human_click(page, declare_btn)
                    if not ok:
                        ok = dispatch_human_click_events(page, declare_btn)
                    if not ok:
                        try:
                            declare_btn.evaluate("node => node.click()")
                            ok = True
                        except Exception:
                            pass
                    if ok:
                        logger.info("[Original-Dialog] \u2705 '\u58f0\u660e\u539f\u521b' button clicked!")
                        page.wait_for_timeout(1000)
                        return True
                    else:
                        logger.warning(f"[Original-Dialog] {strategy_name}: button enabled but click failed, continuing...")
                else:
                    logger.warning(f"[Original-Dialog] {strategy_name}: triggered but button still disabled — UI variant mismatch")
                    page.screenshot(path=f"output/debug_dialog_{strategy_name}_fail.png")

            logger.warning("[Original-Dialog] All 7 strategies exhausted — checkbox could not be activated")
            page.screenshot(path="output/debug_original_dialog_fail.png")
            return False

        # ── 执行原创声明流程 ───────────────────────────────────────────────────
        page.screenshot(path="output/debug_original_before.png")

        if declare_original:
            toggle_ok = _click_original_toggle(page)
            if toggle_ok:
                dialog_ok = _handle_original_rights_dialog(page)
                if dialog_ok:
                    logger.info("✅ Original declaration completed successfully")
                else:
                    logger.warning("⚠️ Original declaration dialog handling failed — proceeding anyway")
            else:
                logger.warning("⚠️ Original declaration toggle not found — proceeding anyway")
        else:
            logger.info("Skipping original declaration by explicit operator choice.")

        page.screenshot(path="output/debug_original_after.png")

        # ── 7. 分类选择 (已弃用) ──────────────────────────────────────────────────────
        if category:
            logger.info(f"Category logic skipped. WeChat Web UI no longer supports category selectors. Relying on hashtags for {category!r}.")
            
        # ── 8. 合集选择与新建 ───────────────────────────────────────────────────
        if not _collection_binding_confirmed(page, collection):
            logger.error("Collection binding was not confirmed; refusing to publish this video.")
            browser.close()
            return 1

        # ── 9. 发表前清理残留遮罩 ────────────────────────────────────────────────
        # [Claude_Sonnet_4.6_Thinking_planning] v2.0.0 bugfix:
        # 合集创建流程可能留下未关闭的 .weui-desktop-dialog__wrp，会拦截「发表」按钮点击
        try:
            overlay = page.locator(".weui-desktop-dialog__wrp").first
            if overlay.count() > 0 and overlay.is_visible():
                logger.warning("Detected open dialog overlay before publish — pressing Escape to dismiss.")
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
        except Exception:
            pass
            
        # 5. 执行提交或存草稿
        if draft:
            logger.info("Saving as draft...")
            draft_btn = page.locator("button:has-text('保存草稿')").first
            if draft_btn.count() == 0:
                draft_btn = page.locator("button:has-text('存草稿')").first
                
            if draft_btn.count() > 0:
                draft_btn.click()
                logger.info("Clicked Save Draft button.")
            else:
                logger.warning("Save Draft button not found. Falling back to Publish.")
                page.locator("button:has-text('发表')").first.click()
        else:
            logger.info("Publishing post...")
            publish_btn = page.locator("button:has-text('发表')").first
            if publish_btn.count() > 0:
                publish_btn.click()
                logger.info("Clicked Publish button.")
            else:
                logger.error("Publish button not found!")
                browser.close()
                return 1
                
        # 6. 确认提交/保存结果
        # 跳转作品列表仅代表平台接收；严禁在这里声称公开视频已发布。
        page.wait_for_timeout(5000)
        redirected, page_content = False, ""
        try:
            # 成功发布后视频号网页通常跳转到 /post/list（最可靠信号）
              page.wait_for_url("**/post/list**", timeout=15000)
              redirected = True
              logger.info("Submission accepted: navigated to post list; awaiting platform processing/review.")
              page.wait_for_timeout(5000)
              _capture_wechat_evidence(page, evidence_root, "post_list_after_submission")
              if identity_baseline_ready:
                  after_cards = _collect_management_cards(page)
                  receipt = resolve_submission_platform_identity(identity_baseline, after_cards, short_title)
                  if receipt:
                      _write_submission_receipt(evidence_root, receipt)
                      logger.info(
                          "Captured exact WeChat platform post identity for this submission: %s",
                          receipt["platform_post_id"],
                      )
                  else:
                      _write_submission_receipt(
                          evidence_root,
                          {
                              "matched_by": "unbound",
                              "reason": "No unique before/after platform-ID delta with exact title",
                          },
                      )
        except Exception:
            page_content = page.content()  # 未跳转 → 取页面文本走降级判据

        accepted = redirected or classify_publish_result(False, page_content, draft=draft)
        browser.close()
        if accepted and not draft:
            logger.info("Submission accepted but not platform-published; returning review state.")
            return EXIT_SUBMITTED_FOR_REVIEW
        if accepted:
            return 0
        logger.warning("Publish could NOT be confirmed — returning UNCONFIRMED(3) so pipeline will NOT mark PUBLISHED/GC.")
        return 3

def main():
    parser = argparse.ArgumentParser(description="Upload and publish videos to WeChat Channels.")
    parser.add_argument("--video",         help="Path to vertical MP4 video file")
    parser.add_argument("--copy",          help="Path to WeChat copy description text file")
    parser.add_argument("--title-file",    help="Path to short title text file (6-16 chars, WeChat platform limit)")
    parser.add_argument("--cover",         help="Path to cover image JPEG file")
    parser.add_argument("--cover-provenance", help="Path to dedicated non-frame cover provenance JSON")
    parser.add_argument("--evidence-dir",  help="Directory for cover and post-list evidence")
    parser.add_argument("--cover-manually-verified", action="store_true",
                        help="Allow one operator-verified cover submission after retaining evidence")
    parser.add_argument("--category-file", help="Path to category text file")
    parser.add_argument("--collection",    help="Custom collection/playlist name to associate with this video")
    parser.add_argument("--state",  default="output/wechat_state.json",
                        help="Path to save/load Playwright session state")
    parser.add_argument("--login-only",  action="store_true")
    parser.add_argument("--relogin",     action="store_true",
                        help="强制重登：忽略现有会话，必出二维码（成功扫码才覆盖 state；未扫旧会话保持有效）")
    parser.add_argument("--fail-fast-login", action="store_true",
                        help="自动发布模式：检测到登录失效立即退出，不等待二维码扫码")
    parser.add_argument("--desktop-auth-preflight", action="store_true",
                        help="只读检查 macOS WeChat 辅助功能权限；不登录、不上传、不发表")
    parser.add_argument("--verify-only", action="store_true",
                        help="仅按已绑定的视频号原生 post_id 回查状态，绝不上传或发布")
    parser.add_argument("--platform-post-id", help="视频号后台的已绑定原生作品 ID；回查时必填")
    parser.add_argument("--no-headless", dest="headless", action="store_false")
    parser.add_argument("--draft",       action="store_true")
    parser.add_argument(
        "--no-original-declaration", dest="declare_original", action="store_false",
        help="明确不声明原创；适用于转载或获授权素材",
    )
    parser.set_defaults(headless=True)
    args = parser.parse_args()

    if args.desktop_auth_preflight:
        result = desktop_auth_preflight()
        logger.info("Desktop WeChat authorization preflight: %s", result.code)
        sys.exit(0 if result.ready else 2)

    try:
        code = run_uploader(
            video_path    = args.video,
            copy_path     = args.copy,
            title_path    = args.title_file,
            cover_path    = args.cover,
            cover_provenance_path = args.cover_provenance,
            category_path = args.category_file,
            state_path    = args.state,
            login_only    = args.login_only,
            headless      = args.headless,
            draft         = args.draft,
            collection    = args.collection,
            relogin       = args.relogin,
            fail_fast_login = args.fail_fast_login,
            evidence_dir = args.evidence_dir,
            cover_manually_verified = args.cover_manually_verified,
            declare_original = args.declare_original,
            verify_only = args.verify_only,
            platform_post_id = args.platform_post_id,
        )
    except Exception as exc:
        if not _is_playwright_target_closed(exc):
            raise
        logger.error(
            "Playwright target closed before publish confirmation; "
            "returning UNCONFIRMED(3) so pipeline will keep artifacts for manual verification: %s",
            exc,
        )
        code = 3
    sys.exit(code)


if __name__ == "__main__":
    main()
