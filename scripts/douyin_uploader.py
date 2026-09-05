"""抖音创作者中心浏览器上传器。

上传与发布继续采用页面校准和 fail-closed 门禁；`--verify-only` 则只读访问作品管理页，
必须在同一作品卡片中精确匹配本地标题或文案指纹及“已发布”或“审核中”状态，绝不凭
本地账本或页面其他作品的状态确认结果。

本脚本是低层浏览器原语，但对会上传、预检、发布或访问作品管理页的动作，会在启动浏览器
前复核持久 UI 熔断账本。自动调度和常规业务入口仍必须先由上层共享熔断守卫放行；这里是
跨进程的最后一道防线。熔断期间只允许带阶段、理由和独立证据目录的非最终人工恢复校准，
`--publish` 永远不能用恢复参数绕过熔断，也不得把本地退出码伪装为平台公开发布。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.7.0 | 2026-09-05 | Codex | 双封面保存后等待检测刷新；旧缺失提示仅触发一次重新检测，超时仍阻断。 |
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
| 1.5.10 | 2026-07-29 | Codex | 上传完成判断优先检测右侧进度文本，避免表单已出现但文件仍上传时误点发布 |
| 1.5.11 | 2026-07-29 | Codex | 发布前强制选择抖音“自主声明”为“内容为个人观点或见解”，无法确认则停止发布 |
| 1.5.12 | 2026-07-29 | Codex | 区分固定上传提示与真实进度，并接受作品管理页发布成功吐司为提交成功证据 |
| 1.5.13 | 2026-07-29 | Codex | 不再把“预览转码中/转码过程也可以发布作品”误判为上传未完成，避免卡在最终提交前 |
| 1.5.14 | 2026-07-29 | Codex | 发布前强制回读标题与文案，并在封面弹窗关闭后复核可见预览；任一元信息未确认即拒绝提交 |
| 1.5.15 | 2026-07-29 | Codex | 回读时忽略抖音编辑器自动插入的零宽格式字符，保持正文内容逐字校验 |
| 1.5.16 | 2026-07-29 | Codex | 封面保存沿用横竖编辑面板内哈希证据，等待平台封面检测结束；避免误将作品页缩略图当原图校验 |
| 1.5.17 | 2026-07-29 | Codex | 自主声明选择失败时输出下拉展开后的可见候选项，依据平台实际文案校准且不猜点 |
| 1.5.18 | 2026-07-29 | Codex | 自主声明改为点击已观测的“请选择自主声明”同一行控件，再读取展开列表，避免误点父容器 |
| 1.5.19 | 2026-07-29 | Codex | 自主声明控件先滚入浏览器视口中央，再按重算坐标点击，修复长发布页离屏点击无效 |
| 1.5.20 | 2026-07-29 | Codex | 优先使用 Playwright 唯一可见文本点击“请选择自主声明”，由浏览器负责滚动与命中测试 |
| 1.5.21 | 2026-07-29 | Codex | 区分“提交后未确认”与提交前各闸门未确认退出码，防止账本误标已提交 |
| 1.5.22 | 2026-07-29 | Codex | 适配自主声明弹窗：选中唯一单选项后必须点击弹窗“确定”，再回读发布页已选值 |
| 1.5.23 | 2026-07-29 | Codex | 横封面步骤优先点击弹窗底部“设置横封面”CTA，避免误点顶部横封面标签后停在双封面缺失 |
| 1.5.24 | 2026-07-29 | Codex | 上传封面后先校验大预览，已匹配时不再点击候选缩略图，避免相似候选覆盖正确封面 |
| 1.5.25 | 2026-07-29 | Codex | 封面候选缩略图已匹配但大预览 crop 误判时，交由保存后卡槽与平台封面检测继续兜底 |
| 1.5.26 | 2026-08-08 | Codex | 实现作品管理页只读回查：本地文案指纹与同卡片状态精确匹配后才确认已发布 |
| 1.5.27 | 2026-08-08 | Codex | 回查等待作品列表脱离加载态，避免把刚打开的空壳页面误判为未确认 |
| 1.5.28 | 2026-08-24 | Codex | 封面“完成”不可用或编辑器未关闭时拒绝进入自主声明，避免仅见卡槽标签便误判横竖封面已保存 |
| 1.5.29 | 2026-08-24 | Codex | 对齐创作者中心实际封面弹窗 body 选择器，避免未定位弹窗时把整页可见误判为编辑器未关闭 |
| 1.5.30 | 2026-08-30 | Codex | 作品管理回查等待列表真实加载并优先精确匹配标题；发布受理只认跳转或明确回执，最终按钮异常不再强制重点击 |
| 1.5.32 | 2026-08-30 | Codex | 填写含话题文案后先关闭标签建议浮层，并收窄封面入口避免宽容器点击被遮挡。 |
| 1.5.31 | 2026-08-30 | Codex | 支持为单次隔离投稿指定独立证据目录，避免校准与投稿证据互相覆盖。 |
| 1.5.33 | 2026-08-31 | Codex | 支持独立横封面，按竖后横顺序分别保存；抖音专用中间封面使用 RGB JPEG 以适配实际上传控件，并在最终提交前拦截快速检测的红黄风险提示。 |
| 1.5.34 | 2026-08-31 | Codex | 适配竖封面后的“设置横封面获更多流量”前置确认：先确认弹窗并进入横封面面板，再注入横图；禁止把横图写入被遮住的竖封面面板。 |
| 1.5.35 | 2026-08-31 | Codex | 封面上传改为仅向当前面板图片 input 直接写入绝对路径；无可用 input 即停止，避免点击上传区打开 Finder 干扰自动化。 |
| 1.5.36 | 2026-08-31 | Codex | 新增仅预检模式：完成上传、文案、双封面、自主声明与快速检测后停止，供最终发布前单独取得确认。 |
| 1.5.37 | 2026-08-31 | Codex | 快速检测新增“检测中”状态门禁：机器检测未完成、120 秒超时或不可读时均不得视为可发布。 |
| 1.5.38 | 2026-08-31 | Codex | 封面确认仅接受具名完成/保存/确认控件，移除无文本通用主按钮兜底以防误点。 |
| 1.5.39 | 2026-08-31 | Codex | 对平台检测服务拥堵的完整固定报错设立窄例外；任何并存的封面或其他风险仍拒绝提交。 |
| 1.5.40 | 2026-09-02 | Codex | 明确低层上传器仅作获授权的人工校准原语；自动路径必须先通过共享 UI 熔断守卫。 |
| 1.5.41 | 2026-09-02 | Codex | 上传器在启动浏览器前复核持久熔断；恢复仅允许受审计的非最终校准，禁止 `--publish` 绕过。 |
| 1.5.42 | 2026-09-02 | Codex | 管理页熔断活动时，低层最终提交也要求明确 `source_kind=NEW`，避免 HISTORY 在跨进程窗口穿透。 |
| 1.5.43 | 2026-09-02 | Codex | 投稿页动作改为消费数据库签发的一次性启动凭据，绑定完整投稿包并在浏览器前原子消费。 |
| 1.5.44 | 2026-09-02 | Codex | 所有投稿页访问均纳入熔断；无凭据旧进程安全停止，管理页熔断保留无上传的登录恢复。 |
| 1.5.46 | 2026-09-04 | Codex | 发布前元信息或检测闸门失败返回未提交，只有已通过闸门后的点击/回读未确认才记提交不确定。 |
| 1.5.47 | 2026-09-04 | Codex | 管理页回读先按精确标题检索可见输入，避免新作品被首屏列表截断而长期保留未确认。 |
| 1.5.48 | 2026-09-04 | Codex | 不再点选平台话题候选，避免候选扩写原文；提交前仍逐字回读原始文案。 |
| 1.5.49 | 2026-09-04 | Codex | 仅接受平台对末尾同源话题的中文限定词扩写；标题和正文其余字符仍必须逐字一致。 |
| 1.5.50 | 2026-09-04 | Codex | 横竖封面改为各自保存并闭窗后再切换，平台双封面缺失在封面阶段即阻断。 |
| 1.5.51 | 2026-09-04 | Codex | 每次封面保存后须等待对应卡槽缩略图地址实际变化，禁止用弹窗关闭代替平台落库证据。 |
| 1.5.52 | 2026-09-04 | Codex | 上传后优先选中当前封面弹窗中新生成的候选缩略图，适配大预览匹配但未落选的新版页面。 |
| 1.5.53 | 2026-09-04 | Codex | 横封面编辑器关闭后主页面不再被误当弹窗；从 4:3 卡槽重开并在双封面保存后统一验收。 |
| 1.5.56 | 2026-09-04 | Codex | 横封面保存后平台要求设置竖封面时，在同一编辑器中重填竖图，避免“暂不设置”导致单侧缺失。 |
| 1.5.54 | 2026-09-04 | Codex | 横封面保存后的“设置竖封面”确认层仅点击“暂不设置”收口，随后仍以双卡槽变更为准。 |
| 1.5.55 | 2026-09-04 | Codex | 快速检测明确报告单侧横/竖封面缺失时同样阻断，不能因卡槽缩略图存在而误放行。 |
| 1.5.45 | 2026-09-02 | Codex | 无论熔断是否活动，最终投稿均强制要求完整一次性启动凭据，禁止低层 CLI 匿名提交。 |
| 1.5.57 | 2026-09-04 | Codex | 上传完成仅接受真实视频预览与重新上传控件并存，避免空上传页的静态表单被误判为上传完成。 |
| 1.5.58 | 2026-09-04 | Codex | 封面卡槽点击超时后先回读已打开的编辑器，避免平台已受理点击却被当作失败。 |
| 1.5.59 | 2026-09-04 | Codex | 竖封面保存后的横封面推荐层在同一编辑器内即时确认，避免误等编辑器关闭。 |
| 1.5.60 | 2026-09-04 | Codex | 上传完成后的视频预览说明不再被“已上传”关键词误判为动态进度。 |
| 1.5.61 | 2026-09-04 | Codex | 封面成功态优先于异步遗留的双封面缺失文案，避免已通过检测被旧提示阻断。 |
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


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from config.settings import settings  # noqa: E402
from video_processing.core.douyin_ui_guard_policy import (  # noqa: E402
    DOUYIN_UI_STAGE_MANAGEMENT_VERIFY,
    DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT,
    active_douyin_ui_failure_stages,
    douyin_management_verify_is_blocked,
    douyin_publish_is_blocked,
)
from video_processing.core.douyin_launch_context import (  # noqa: E402
    canonical_local_path,
    douyin_submission_payload_sha256,
    sha256_file as launch_sha256_file,
)
from video_processing.db.database import PipelineDB  # noqa: E402


logger = logging.getLogger("douyin_uploader")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

DOUYIN_UPLOAD_URL = "https://creator.douyin.com/creator-micro/content/upload"
DOUYIN_MANAGEMENT_URL = "https://creator.douyin.com/creator-micro/content/manage"
DOUYIN_VIDEO_INPUT_SELECTOR = 'input[type="file"]'
DOUYIN_TITLE_SELECTOR = 'input[placeholder*="作品标题"]'
DOUYIN_DESCRIPTION_SELECTOR = '[contenteditable="true"]'
DOUYIN_SELF_DECLARATION_LABEL_TEXT = "自主声明"
DOUYIN_SELF_DECLARATION_OPTION_TEXT = "内容为个人观点或见解"
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
EXIT_SUBMISSION_UNCONFIRMED = 7
MANAGEMENT_PUBLISHED = "PUBLISHED"
MANAGEMENT_UNDER_REVIEW = "UNDER_REVIEW"
DOUYIN_BLOCKING_QUICK_CHECK_MARKERS = (
    "作品检测失败",
    "当前检测人数过多",
    "检测失败",
    "横/竖双封面缺失",
    "横竖双封面缺失",
    "建议同时设置横版和竖版的封面",
    "封面检测未通过",
    "封面不合格",
    "封面违规",
    "封面异常",
)
DOUYIN_CAPACITY_CONGESTION_REQUIRED_TEXT = (
    "作品检测失败",
    "当前检测人数过多",
    "请稍后再试",
)
DOUYIN_CAPACITY_CONGESTION_COMPATIBLE_MARKERS = (
    "作品检测失败",
    "当前检测人数过多",
    "检测失败",
)
DOUYIN_PENDING_QUICK_CHECK_MARKERS = (
    "检测中",
    "正在检测",
    "检查中",
    "正在检查",
)
DOUYIN_QUICK_CHECK_TIMEOUT_SECONDS = 120
DOUYIN_CALIBRATION_ROOT = PROJECT_ROOT / "output" / "douyin_calibration"
_UI_GUARD_ACTION_PUBLISH = "publish"
_UI_GUARD_ACTION_MANAGEMENT_VERIFY = "management_verify"
_UI_GUARD_ACTION_AUTH = "auth"


def _guarded_ui_action(args: argparse.Namespace) -> Optional[str]:
    """返回本次会打开的受保护页面；默认快照和登录页也必须过熔断。"""
    if getattr(args, "verify_only", False):
        return _UI_GUARD_ACTION_MANAGEMENT_VERIFY
    if getattr(args, "login_only", False):
        return _UI_GUARD_ACTION_AUTH
    # 除 ``--verify-only`` 外，main() 都会导航到投稿页；因此不能把登录、快照
    # 校准或默认动作当作“不打开浏览器”的旁路。
    return _UI_GUARD_ACTION_PUBLISH


def _read_active_persistent_douyin_ui_failure_stages(
    *,
    db: Optional[PipelineDB] = None,
) -> Optional[set[str]]:
    """读取跨进程熔断账本；不可判定时返回 None，调用者必须 fail-closed。"""
    try:
        ledger = db if db is not None else PipelineDB(str(PROJECT_ROOT / "output" / "pipeline.db"))
        streaks = ledger.get_platform_ui_failure_streaks("douyin")
    except Exception:  # noqa: BLE001 - 账本不可读时不得启动浏览器
        logger.exception("无法读取抖音 UI 熔断账本，拒绝启动浏览器")
        return None
    if not isinstance(streaks, list):
        logger.error("抖音 UI 熔断账本格式异常（期待 list），拒绝启动浏览器")
        return None
    try:
        return active_douyin_ui_failure_stages(
            streaks,
            recording_threshold=settings.douyin_ui_failure_recording_threshold,
        )
    except Exception:  # noqa: BLE001 - 策略无法判定时宁可停止
        logger.exception("抖音 UI 熔断账本无法判定，拒绝启动浏览器")
        return None


def _validate_operator_recovery_request(
    args: argparse.Namespace,
    *,
    calibration_root: Path,
) -> Optional[int]:
    """恢复授权只可用于非最终校准，且证据必须落到既有清熔断可信目录。"""
    stage = getattr(args, "operator_recovery_stage", None)
    reason = (getattr(args, "operator_recovery_reason", None) or "").strip()
    if bool(stage) != bool(reason):
        logger.error("操作员恢复校准必须同时提供 --operator-recovery-stage 与非空 --operator-recovery-reason")
        return EXIT_FAILED
    if not stage:
        return None
    if args.publish:
        logger.error("--operator-recovery-* 仅用于校准证据，不能与 --publish 合用")
        return EXIT_FAILED
    if not (
        getattr(args, "verify_only", False)
        or getattr(args, "preflight_only", False)
        or getattr(args, "calibrate_after_upload", False)
        or getattr(args, "calibrate", False)
    ):
        logger.error("操作员恢复校准仅允许 --verify-only、--calibrate、--preflight-only 或 --calibrate-after-upload")
        return EXIT_FAILED
    expected_stage = (
        DOUYIN_UI_STAGE_MANAGEMENT_VERIFY
        if args.verify_only
        else DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT
    )
    if stage != expected_stage:
        logger.error("恢复阶段 %s 与当前非最终校准动作不匹配，期望 %s", stage, expected_stage)
        return EXIT_FAILED
    if not args.evidence_dir:
        logger.error("操作员恢复校准必须提供 --evidence-dir 以保存独立审计证据")
        return EXIT_FAILED
    try:
        Path(args.evidence_dir).resolve().relative_to(calibration_root.resolve())
    except ValueError:
        logger.error("操作员恢复校准证据必须位于 %s", calibration_root)
        return EXIT_FAILED
    return None


def _operator_recovery_matches_active_stages(
    args: argparse.Namespace,
    action: str,
    active_stages: set[str],
) -> bool:
    """未知阶段不得被恢复旗标放行；已知阶段只允许采集其自身的校准证据。"""
    stage = getattr(args, "operator_recovery_stage", None)
    known_stages = {
        DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT,
        DOUYIN_UI_STAGE_MANAGEMENT_VERIFY,
    }
    if not active_stages or not active_stages.issubset(known_stages):
        return False
    if action == _UI_GUARD_ACTION_MANAGEMENT_VERIFY:
        return (
            stage == DOUYIN_UI_STAGE_MANAGEMENT_VERIFY
            and active_stages == {DOUYIN_UI_STAGE_MANAGEMENT_VERIFY}
        )
    return (
        stage == DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT
        and DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT in active_stages
    )


def _write_operator_recovery_audit(
    args: argparse.Namespace,
    *,
    action: str,
    active_stages: set[str],
) -> bool:
    """在浏览器启动前留下受控恢复请求；失败则不允许打开页面。"""
    evidence_dir = Path(args.evidence_dir)
    payload = {
        "event": "operator_recovery_calibration",
        "recorded_at_epoch": time.time(),
        "stage": args.operator_recovery_stage,
        "reason": args.operator_recovery_reason.strip(),
        "guarded_action": action,
        "active_stages": sorted(active_stages),
        "final_publish": False,
    }
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "operator_recovery_calibration.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error("无法写入操作员恢复校准审计证据：%s", exc)
        return False
    return True


def _submission_launch_payload(args: argparse.Namespace) -> Optional[tuple[str, str, str]]:
    """从真实本地投稿包重算启动绑定；任一文件不完整均不能打开浏览器。"""
    video = getattr(args, "video", None)
    payload_sha256 = douyin_submission_payload_sha256(
        video_path=video,
        copy_path=getattr(args, "copy", None),
        title_path=getattr(args, "title_file", None),
        cover_path=getattr(args, "cover", None),
        horizontal_cover_path=getattr(args, "horizontal_cover", None),
    )
    video_sha256 = launch_sha256_file(video)
    if not video or not payload_sha256 or not video_sha256:
        return None
    return canonical_local_path(video), video_sha256, payload_sha256


def _ticket_fields(args: argparse.Namespace) -> tuple[str, str]:
    """兼容直接单元调用的 Namespace；空/半填均由守卫 fail-closed。"""
    return (
        str(getattr(args, "douyin_launch_ticket_id", "") or "").strip(),
        str(getattr(args, "douyin_launch_token", "") or "").strip(),
    )


def _guard_before_browser(
    args: argparse.Namespace,
    *,
    db: Optional[PipelineDB] = None,
    calibration_root: Optional[Path] = None,
) -> Optional[int]:
    """在 Playwright 启动前执行最后一道跨进程 UI 熔断守卫。"""
    recovery_validation = _validate_operator_recovery_request(
        args,
        calibration_root=calibration_root or DOUYIN_CALIBRATION_ROOT,
    )
    if recovery_validation is not None:
        return recovery_validation
    action = _guarded_ui_action(args)
    if action is None:
        return None
    ticket_id, launch_token = _ticket_fields(args)
    if bool(ticket_id) != bool(launch_token):
        logger.error("抖音浏览器启动凭据必须同时提供 ticket 与 token")
        return EXIT_NOT_CALIBRATED
    if bool(getattr(args, "publish", False)) and not ticket_id:
        logger.error("抖音最终投稿必须持有已领取账本签发的一次性启动凭据")
        return EXIT_NOT_CALIBRATED
    if ticket_id and not args.publish:
        logger.error("一次性抖音启动凭据仅绑定 --publish，不能拿去执行管理页或预检动作")
        return EXIT_NOT_CALIBRATED
    active_stages = _read_active_persistent_douyin_ui_failure_stages(db=db)
    if active_stages is None:
        return EXIT_NOT_CALIBRATED
    blocked = (
        douyin_management_verify_is_blocked(active_stages)
        if action == _UI_GUARD_ACTION_MANAGEMENT_VERIFY
        else douyin_publish_is_blocked(active_stages)
    )
    if blocked and _operator_recovery_matches_active_stages(args, action, active_stages):
        if _write_operator_recovery_audit(args, action=action, active_stages=active_stages):
            logger.warning(
                "抖音 UI 熔断阶段 %s 活动；仅放行受审计的非最终 %s 校准，"
                "完成证据化清熔断前绝不允许发布。",
                ", ".join(sorted(active_stages)),
                action,
            )
            return None
        return EXIT_NOT_CALIBRATED
    if blocked:
        logger.error(
            "抖音 UI 熔断阶段 %s 活动，拒绝在启动浏览器前执行 %s。",
            ", ".join(sorted(active_stages)),
            action,
        )
        return EXIT_NOT_CALIBRATED
    if action == _UI_GUARD_ACTION_PUBLISH and ticket_id:
        payload = _submission_launch_payload(args)
        if not payload:
            logger.error("抖音启动凭据无法绑定完整本地投稿包，拒绝启动浏览器")
            return EXIT_NOT_CALIBRATED
        video_path, asset_sha256, payload_sha256 = payload
        try:
            ledger = db if db is not None else PipelineDB(str(PROJECT_ROOT / "output" / "pipeline.db"))
            allowed = ledger.begin_douyin_browser_launch(
                ticket_id,
                launch_token,
                video_path=video_path,
                asset_sha256=asset_sha256,
                payload_sha256=payload_sha256,
                require_new_source=bool(active_stages),
            )
        except Exception:  # noqa: BLE001 - ticket 不可判定时不允许开浏览器
            logger.exception("无法消费抖音一次性浏览器启动凭据，拒绝启动浏览器")
            return EXIT_NOT_CALIBRATED
        if not allowed:
            logger.error("抖音启动凭据、投稿包或领取状态不匹配，拒绝启动浏览器")
            return EXIT_NOT_CALIBRATED
        return None
    if action == _UI_GUARD_ACTION_PUBLISH and active_stages:
        # 旧父进程没有不可伪造的完整投稿包绑定。即使留下 NEW+UPLOADING 账本，也
        # 不能据此推断其后续命令可安全发布；预检、登录和默认快照同样不能绕过
        # 管理页熔断。必须让旧进程安全停止，再由新领取签发 ticket。
        logger.error("抖音 UI 熔断活动时，投稿页动作必须由受审计恢复校准或已绑定启动凭据授权")
        return EXIT_NOT_CALIBRATED
    return None


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


def _normalize_page_text(text: str) -> str:
    """压缩页面空白及零宽格式字符，便于稳定匹配作品管理卡片正文。"""
    return "".join((text or "").replace("\u200b", "").split())


def get_management_copy_markers(copy_text: str) -> list[str]:
    """生成管理页可见的正文指纹；短片段只作兜底，避免跨作品误匹配。"""
    normalized = _normalize_page_text(copy_text)
    markers: list[str] = []
    for size in (96, 64, 40, 24):
        if len(normalized) < size:
            continue
        marker = normalized[:size]
        if marker not in markers:
            markers.append(marker)
    return markers


def get_management_publication_state(
    page_text: str,
    copy_text: str,
    title_text: str = "",
) -> Optional[str]:
    """只在精确身份锚点后的同一作品卡片片段内读取可见发布状态。"""
    normalized_page = _normalize_page_text(page_text)
    normalized_title = _normalize_page_text(title_text)
    markers = [normalized_title] if len(normalized_title) >= 6 else []
    markers.extend(marker for marker in get_management_copy_markers(copy_text) if marker not in markers)
    matched_states: set[str] = set()
    for marker in markers:
        start = 0
        while True:
            marker_index = normalized_page.find(marker, start)
            if marker_index < 0:
                break
            # 当前作品管理列表只展示标题、日期和状态；收窄窗口，避免读到下一张作品卡片。
            status_window = normalized_page[marker_index + len(marker):marker_index + len(marker) + 320]
            review_index = status_window.find("审核中")
            published_index = status_window.find("已发布")
            if review_index >= 0 and (published_index < 0 or review_index < published_index):
                matched_states.add(MANAGEMENT_UNDER_REVIEW)
            elif published_index >= 0:
                matched_states.add(MANAGEMENT_PUBLISHED)
            start = marker_index + len(marker)
    if len(matched_states) == 1:
        return next(iter(matched_states))
    return None


def wait_for_management_content(
    page,
    timeout_ms: int = 15_000,
    *,
    expected_markers: Iterable[str] = (),
) -> str:
    """等作品列表骨架或目标身份出现；超时仍保持未确认。"""
    deadline = time.monotonic() + timeout_ms / 1000
    markers = tuple(marker for marker in expected_markers if marker)
    page_text = ""
    while time.monotonic() < deadline:
        page_text = get_page_text(page)
        normalized = _normalize_page_text(page_text)
        target_visible = any(marker in normalized for marker in markers)
        list_ready = (
            "搜索作品" in page_text
            and "已发布" in page_text
            and ("审核中" in page_text or "不通过" in page_text)
        )
        if "加载中" not in page_text and (target_visible or list_ready):
            return page_text
        page.wait_for_timeout(500)
    return page_text


def _search_management_title(page, title_text: str) -> bool:
    """用内容管理页的精确标题搜索缩小只读回查范围；找不到控件则保留全表回读。"""
    title = " ".join((title_text or "").split()).strip()
    if len(title) < 6:
        return False
    try:
        fields = page.locator('input[placeholder="搜索作品"]')
        for index in range(fields.count()):
            search = fields.nth(index)
            if search.is_visible(timeout=1_000) is not True:
                continue
            search.fill(title, timeout=3_000)
            search.press("Enter", timeout=3_000)
            page.wait_for_timeout(1_000)
            logger.info("已按精确标题检索抖音内容管理页：%s", title)
            return True
        return False
    except Exception as exc:
        logger.debug("抖音内容管理页标题检索不可用，继续只读全表回查：%s", exc)
        return False


def verify_management_publication(
    page,
    artifact_dir: Path,
    copy_text: str,
    title_text: str = "",
) -> Optional[str]:
    """只读进入作品管理页，记录当前页面证据并返回本次作品的明确可见状态。"""
    try:
        page.goto(DOUYIN_MANAGEMENT_URL, wait_until="domcontentloaded", timeout=60_000)
    except Exception as exc:
        logger.error("进入抖音作品管理页失败: %s", exc)
        return None
    normalized_title = _normalize_page_text(title_text)
    expected_markers = [normalized_title] if len(normalized_title) >= 6 else []
    expected_markers.extend(get_management_copy_markers(copy_text))
    _search_management_title(page, title_text)
    page_text = wait_for_management_content(page, expected_markers=expected_markers)
    if is_login_required(page.url, page_text, [frame.url for frame in page.frames]):
        logger.error("抖音作品管理页登录态失效")
        return None
    capture_controls(page, artifact_dir, "douyin_management_evidence")
    return get_management_publication_state(page_text, copy_text, title_text)


def capture_controls(page, artifact_dir: Path, artifact_name: str) -> None:
    """采集页面控件契约，供下一轮根据真实 DOM 补充选择器。"""
    try:
        page_context = page.evaluate(
            """() => ({
                url: location.href,
                title: document.title,
                bodyTextPreview: (document.body?.innerText || '').slice(0, 1200),
            })"""
        )
        if not isinstance(page_context, dict):
            page_context = {}
    except Exception:
        page_context = {}
    page_context = {
        "url": str(page_context.get("url") or getattr(page, "url", "") or ""),
        "title": str(page_context.get("title") or ""),
        "bodyTextPreview": str(page_context.get("bodyTextPreview") or ""),
    }
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
        json.dumps({"page": page_context, "controls": controls}, ensure_ascii=False, indent=2), encoding="utf-8"
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


def _is_self_declaration_selected(page) -> bool:
    """确认“自主声明”同一行已经显示目标选项，避免误读下拉列表中的候选项。"""
    try:
        return bool(
            page.evaluate(
                """({label, option}) => {
                    const normalize = value => String(value || '').replace(/\\s+/g, '');
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    const all = Array.from(document.querySelectorAll('body *')).filter(visible);
                    const labelText = normalize(label);
                    const optionText = normalize(option);
                    const labels = all.filter(element => {
                        const text = normalize(element.innerText || element.textContent || '');
                        return text === labelText || (text.includes(labelText) && text.length <= labelText.length + 8);
                    });
                    for (const labelElement of labels) {
                        const labelRect = labelElement.getBoundingClientRect();
                        const labelCenterY = labelRect.y + labelRect.height / 2;
                        const selected = all.find(element => {
                            if (element === labelElement) return false;
                            const rect = element.getBoundingClientRect();
                            const text = normalize(element.innerText || element.textContent || '');
                            return text.includes(optionText)
                                && rect.x > labelRect.x + labelRect.width
                                && Math.abs((rect.y + rect.height / 2) - labelCenterY) < 70;
                        });
                        if (selected) return true;
                    }
                    return false;
                }""",
                {"label": DOUYIN_SELF_DECLARATION_LABEL_TEXT, "option": DOUYIN_SELF_DECLARATION_OPTION_TEXT},
            )
        )
    except Exception as exc:
        logger.debug("读取抖音自主声明当前选项失败: %s", exc)
        return False


def _click_self_declaration_dropdown(page) -> bool:
    """点击同一行“请选择自主声明”控件；不把外层父容器误当下拉框。"""
    placeholder_text = f"请选择{DOUYIN_SELF_DECLARATION_LABEL_TEXT}"
    try:
        placeholder = page.get_by_text(placeholder_text, exact=True)
        if placeholder.count() == 1 and placeholder.is_visible():
            placeholder.click(timeout=2_000, force=True)
            logger.info("已点击抖音自主声明控件：%s", placeholder_text)
            return True
    except Exception as exc:
        logger.debug("通过唯一文本点击抖音自主声明控件失败，继续 DOM 兜底：%s", exc)
    try:
        target = page.evaluate(
                """label => {
                    const normalize = value => String(value || '').replace(/\\s+/g, '');
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    const all = Array.from(document.querySelectorAll('body *')).filter(visible);
                    const labels = all.filter(element => {
                        const text = normalize(element.innerText || element.textContent || '');
                        return text === normalize(label) || (text.includes(normalize(label)) && text.length <= normalize(label).length + 8);
                    });
                    const placeholderText = normalize(`请选择${label}`);
                    for (const labelElement of labels) {
                        const labelRect = labelElement.getBoundingClientRect();
                        const labelCenterY = labelRect.y + labelRect.height / 2;
                        const candidates = all.map(element => {
                            const rect = element.getBoundingClientRect();
                            const className = String(element.className || '').toLowerCase();
                            const role = String(element.getAttribute('role') || '').toLowerCase();
                            const aria = String(element.getAttribute('aria-haspopup') || '').toLowerCase();
                            const text = normalize(element.innerText || element.textContent || '');
                            const isPlaceholder = text === placeholderText;
                            const score = (isPlaceholder ? 400 : 0)
                                + (role === 'combobox' ? 80 : 0)
                                + (aria.includes('listbox') ? 60 : 0)
                                + (className.includes('select') ? 40 : 0)
                                + (text && !text.includes(normalize(label)) ? 10 : 0)
                                - Math.round(Math.abs((rect.y + rect.height / 2) - labelCenterY));
                            return {element, rect, score};
                        }).filter(item => item.rect.x > labelRect.x + labelRect.width
                            && item.rect.width >= 80
                            && item.rect.height >= 20
                            && Math.abs((item.rect.y + item.rect.height / 2) - labelCenterY) < 90);
                        candidates.sort((left, right) => right.score - left.score);
                        if (candidates[0]) {
                            candidates[0].element.scrollIntoView({block: 'center', inline: 'nearest'});
                            const rect = candidates[0].element.getBoundingClientRect();
                            return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                        }
                    }
                    return false;
                }""",
                DOUYIN_SELF_DECLARATION_LABEL_TEXT,
            )
        if isinstance(target, dict) and isinstance(target.get("x"), (int, float)) and isinstance(target.get("y"), (int, float)):
            page.mouse.click(target["x"], target["y"])
            return True
        return bool(target)
    except Exception as exc:
        logger.debug("点击抖音自主声明下拉失败: %s", exc)
        return False


def _click_self_declaration_option(page) -> bool:
    """在已展开下拉中点击目标自主声明选项。"""
    try:
        option = page.get_by_text(DOUYIN_SELF_DECLARATION_OPTION_TEXT, exact=True)
        if option.count() == 1 and option.is_visible():
            option.click(timeout=2_000, force=True)
            page.wait_for_timeout(300)
            confirm = page.get_by_text("确定", exact=True)
            if confirm.count() != 1 or not confirm.is_visible() or not confirm.is_enabled():
                logger.error("抖音自主声明弹窗的唯一“确定”按钮不可用")
                return False
            confirm.click(timeout=2_000, force=True)
            logger.info("已选择并确认抖音自主声明: %s", DOUYIN_SELF_DECLARATION_OPTION_TEXT)
            return True
    except Exception as exc:
        logger.debug("通过弹窗唯一文本选择抖音自主声明失败，继续 DOM 兜底：%s", exc)
    try:
        result = page.evaluate(
                """option => {
                    const normalize = value => String(value || '').replace(/\\s+/g, '');
                    const visible = element => {
                        const rect = element.getBoundingClientRect();
                        const style = window.getComputedStyle(element);
                        return rect.width > 0 && rect.height > 0
                            && style.visibility !== 'hidden'
                            && style.display !== 'none';
                    };
                    const optionText = normalize(option);
                    const candidates = Array.from(document.querySelectorAll('[role="option"], li, div, span'))
                        .filter(visible)
                        .map(element => {
                            const text = normalize(element.innerText || element.textContent || '');
                            const className = String(element.className || '').toLowerCase();
                            const role = String(element.getAttribute('role') || '').toLowerCase();
                            const inPopup = Boolean(element.closest('[role="listbox"], [class*="option"], [class*="dropdown"], [class*="popover"], [class*="portal"]'));
                            return {element, text, role, className, inPopup};
                        })
                        .filter(item => item.text === optionText || (item.text.includes(optionText) && item.text.length <= optionText.length + 12));
                    candidates.sort((left, right) => {
                        const leftScore = (left.role === 'option' ? 100 : 0) + (left.inPopup ? 50 : 0) + (left.className.includes('option') ? 30 : 0);
                        const rightScore = (right.role === 'option' ? 100 : 0) + (right.inPopup ? 50 : 0) + (right.className.includes('option') ? 30 : 0);
                        return rightScore - leftScore;
                    });
                    const visibleTexts = Array.from(document.querySelectorAll('body *'))
                        .filter(visible)
                        .map(element => normalize(element.innerText || element.textContent || ''))
                        .filter(text => text && text.length <= 80 && (text.includes('声明') || text.includes('观点') || text.includes('内容')))
                        .filter((text, index, values) => values.indexOf(text) === index)
                        .slice(0, 80);
                    if (!candidates[0]) return {clicked: false, visibleTexts};
                    candidates[0].element.click();
                    return {clicked: true, visibleTexts};
                }""",
                DOUYIN_SELF_DECLARATION_OPTION_TEXT,
            )
        if isinstance(result, dict):
            if not result.get("clicked"):
                logger.info("抖音自主声明展开后的可见候选项：%s", result.get("visibleTexts", []))
            return bool(result.get("clicked"))
        return bool(result)
    except Exception as exc:
        logger.debug("点击抖音自主声明目标选项失败: %s", exc)
        return False


def select_self_declaration(page, artifact_dir: Path) -> bool:
    """发布前强制选择“内容为个人观点或见解”；不可确认时拒绝继续发布。"""
    if _is_self_declaration_selected(page):
        logger.info("抖音自主声明已选择: %s", DOUYIN_SELF_DECLARATION_OPTION_TEXT)
        return True
    if not _click_self_declaration_dropdown(page):
        logger.error("未能定位或点击抖音“自主声明”下拉框")
        capture_controls(page, artifact_dir, "douyin_self_declaration_failed")
        return False
    page.wait_for_timeout(500)
    if not _click_self_declaration_option(page):
        logger.error("未能选择抖音自主声明选项: %s", DOUYIN_SELF_DECLARATION_OPTION_TEXT)
        capture_controls(page, artifact_dir, "douyin_self_declaration_failed")
        return False
    page.wait_for_timeout(500)
    if not _is_self_declaration_selected(page):
        logger.error("抖音自主声明选择后无法确认当前值: %s", DOUYIN_SELF_DECLARATION_OPTION_TEXT)
        capture_controls(page, artifact_dir, "douyin_self_declaration_unconfirmed")
        return False
    logger.info("已选择抖音自主声明: %s", DOUYIN_SELF_DECLARATION_OPTION_TEXT)
    return True


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
    try:
        visible_text = page.locator("body").inner_text(timeout=3_000)
    except Exception:
        return True
    if has_active_upload_progress(visible_text):
        return True
    if has_post_upload_form(page, visible_text=visible_text):
        return False
    # 标题、正文和“发布”在尚未选择视频时已经存在；没有真实预览不能证明
    # 平台已接受文件，继续等待而不是提前进入封面/声明步骤。
    return True


def has_active_upload_progress(visible_text: str) -> bool:
    """只把动态上传/转码状态视为未完成；固定发布提示不能阻塞或误判。"""
    compact = " ".join((visible_text or "").split())
    if not compact:
        return True
    compact = compact.replace("点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。", "")
    compact = compact.replace("点击发布后，如作品还在上传中，请勿关闭页面", "")
    compact = compact.replace("预览转码中，请稍后", "")
    compact = compact.replace("转码过程也可以发布作品", "")
    # “视频素材已按原始分辨率上传”是预览功能的固定成功说明，其中的
    # “已上传”不是正在传输；保留它会使已出现视频预览的页面空等至超时。
    compact = compact.replace("视频素材已按原始分辨率上传，为保证预览体验，视频会被压缩预览，实际播放时根据环境自动选组最佳分辨率播放。", "")
    dynamic_markers = (
        "上传进度",
        "上传过程中",
        "已上传",
        "剩余时间",
        "当前速度",
    )
    if any(marker in compact for marker in dynamic_markers):
        return True
    if "%" in compact and any(marker in compact for marker in ("上传", "进度", "剩余", "速度", "处理")):
        return True
    if "作品还在上传中" in compact and not compact.startswith("点击发布后"):
        return True
    return False


def has_post_upload_form(page, *, visible_text: Optional[str] = None) -> bool:
    """只在真实视频预览已出现时确认上传完成，拒绝空投稿页的静态表单。"""
    if visible_text is None:
        try:
            visible_text = page.locator("body").inner_text(timeout=3_000)
        except Exception:
            return False
    compact = "".join((visible_text or "").split())
    return "预览视频" in compact and "重新上传" in compact


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
    horizontal_cover_path: Optional[str] = None,
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
        if not fill_publish_fields(
            page,
            title_text or "",
            description_text or "",
            artifact_dir,
            cover_path=cover_path,
            horizontal_cover_path=horizontal_cover_path,
        ):
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
        target = source.with_name(f"{source.stem}_{suffix}.jpg")
        background.save(target, format="JPEG", quality=95, optimize=True)
        logger.info(
            "已生成抖音专用 JPEG 封面副本: %s (%sx%s -> %sx%s)",
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


def _click_bottom_text_button(page, texts: Iterable[str]) -> bool:
    """点击页面底部区域最靠下的可见文本按钮，适配封面弹窗右下角 CTA。"""
    try:
        target = page.evaluate(
            """texts => {
                const wanted = new Set(texts);
                const candidates = [];
                for (const element of Array.from(document.querySelectorAll('button, [role="button"], span, div'))) {
                    const text = (element.innerText || element.textContent || '').trim().replace(/\\s+/g, '');
                    if (!wanted.has(text)) continue;
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    const disabled = element.disabled || element.getAttribute('aria-disabled') === 'true';
                    if (
                        disabled || rect.width <= 0 || rect.height <= 0 ||
                        style.visibility === 'hidden' || style.display === 'none'
                    ) {
                        continue;
                    }
                    candidates.push({
                        x: rect.x + rect.width / 2,
                        y: rect.y + rect.height / 2,
                        width: rect.width,
                        height: rect.height,
                        top: rect.y,
                        text,
                    });
                }
                candidates.sort((left, right) => right.top - left.top || (right.width * right.height) - (left.width * left.height));
                return candidates[0] || null;
            }""",
            [text.replace(" ", "") for text in texts],
        )
    except Exception as exc:
        logger.debug("查找底部文本按钮失败: %s", exc)
        return False
    if not target:
        return False
    page.mouse.click(target["x"], target["y"])
    page.wait_for_timeout(1500)
    logger.info("已点击底部文本按钮：%s", target.get("text"))
    return True


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
        # 未选中封面时应优先使用初始上传 input；replace input 只作为后备，
        # 否则某些页面会把文件投递到上一张竖封面的替换控件。
        score -= 5
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
    """仅通过当前封面面板的图片 input 注入绝对路径，绝不打开 Finder。"""
    try:
        file_inputs = modal.locator("input[type='file']")
        candidates = []
        for i in range(file_inputs.count()):
            candidate = file_inputs.nth(i)
            if not _is_cover_file_input_candidate(candidate):
                logger.warning("跳过疑似抖音视频 input，accept=%s", _get_file_accept(candidate))
                continue
            candidates.append((_cover_file_input_score(candidate), candidate))
        if not candidates:
            logger.error("当前抖音封面面板不存在可用图片 input；拒绝打开 Finder 兜底")
            return False
        for score, file_input in sorted(candidates, key=lambda item: item[0], reverse=True):
            try:
                file_input.set_input_files(cover_path_abs, timeout=3_000)
                logger.info("已通过当前抖音封面面板图片 input 直接注入封面，score=%s", score)
                return True
            except Exception as exc:
                logger.debug("当前抖音图片 input 注入失败，尝试下一个候选：%s", exc)
    except Exception as exc:
        logger.debug("定位当前抖音封面图片 input 失败: %s", exc)
    logger.error("当前抖音封面图片无法直接注入；拒绝打开 Finder 兜底")
    return False


def _visible_modal_cover_images(modal) -> list[dict[str, object]]:
    """返回当前封面弹窗的可见图片与几何信息，避免误点发布页预览图。"""
    try:
        images = modal.evaluate(
            """root => Array.from(root.querySelectorAll('img')).map(image => {
                const rect = image.getBoundingClientRect();
                const style = getComputedStyle(image);
                return {
                    source: image.currentSrc || image.src || '',
                    x: rect.x,
                    y: rect.y,
                    width: rect.width,
                    height: rect.height,
                    visible: rect.width > 0 && rect.height > 0
                        && style.visibility !== 'hidden' && style.display !== 'none',
                };
            }).filter(item => item.visible && item.source)"""
        )
    except Exception as exc:
        logger.debug("读取当前抖音封面弹窗候选图失败: %s", exc)
        return []
    return [item for item in (images or []) if isinstance(item, dict)]


def _select_new_cover_candidate(page, modal, known_sources: set[str]) -> bool:
    """点击刚由本地上传产生的小候选图，确保平台真正选中而不只显示大预览。"""
    candidates = []
    for image in _visible_modal_cover_images(modal):
        source = str(image.get("source") or "").strip()
        width = float(image.get("width") or 0)
        height = float(image.get("height") or 0)
        if (
            not source
            or source in known_sources
            or width < 40 or height < 40
            or width > 240 or height > 240
        ):
            continue
        candidates.append(image)
    if not candidates:
        return False
    # 候选图通常位于大裁剪预览右侧；同尺寸时优先最靠右者，避免选回主预览。
    candidate = sorted(
        candidates,
        key=lambda item: (float(item.get("x") or 0), -(float(item.get("width") or 0) * float(item.get("height") or 0))),
        reverse=True,
    )[0]
    try:
        page.mouse.click(
            float(candidate["x"]) + float(candidate["width"]) / 2,
            float(candidate["y"]) + float(candidate["height"]) / 2,
        )
        page.wait_for_timeout(1_000)
        logger.info("已选中抖音本地上传后新生成的封面候选缩略图")
        return True
    except Exception as exc:
        logger.error("点击抖音新生成封面候选缩略图失败: %s", exc)
        return False


def _apply_cover_in_current_panel(
    page,
    modal,
    cover_path_abs: str,
    *,
    artifact_dir: Optional[Path],
    artifact_prefix: str,
    allow_thumbnail_match_fallback: bool = False,
) -> bool:
    known_sources = {
        str(image.get("source") or "").strip()
        for image in _visible_modal_cover_images(modal)
        if str(image.get("source") or "").strip()
    }
    _open_cover_upload_tab(page, modal)
    if not _inject_cover_file_in_modal(page, modal, cover_path_abs):
        logger.error("抖音封面图片未能注入当前封面面板: %s", cover_path_abs)
        return False
    page.wait_for_timeout(2000)
    if artifact_dir:
        capture_cover_evidence(page, artifact_dir, f"{artifact_prefix}_after_input_injection", cover_path_abs)
    candidate_selected = _select_new_cover_candidate(page, modal, known_sources)
    if _is_cover_preview_matched(page, cover_path_abs):
        if candidate_selected:
            logger.info("抖音封面候选已选中且大预览匹配")
        else:
            logger.info("抖音封面注入后大预览已匹配，未出现新候选缩略图")
        return True
    if not _click_matching_cover_thumbnail(page, cover_path_abs):
        return False
    if not _is_cover_preview_matched(page, cover_path_abs):
        if allow_thumbnail_match_fallback:
            logger.warning(
                "抖音%s候选缩略图已匹配，但大预览哈希仍不匹配；继续交由保存后卡槽与平台封面检测确认",
                artifact_prefix,
            )
            return True
        return False
    return True


def _accept_horizontal_cover_recommendation(page, *, timeout_seconds: int = 8) -> bool:
    """确认已观测到的双封面推荐弹窗，且只点击弹窗自身的横封面 CTA。

    竖封面上传后，编辑器的“设置横封面”会先打开一层说明弹窗。若在该
    弹窗仍覆盖编辑器时向 hidden input 注入文件，平台会把文件投递给错误的
    面板并报出误导性的图片格式错误。因此弹窗一旦出现，必须先等待其关闭。
    """
    state_script = """shouldClick => {
        const normalize = value => (value || '').replace(/\\s+/g, '');
        const visible = element => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0
                && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const dialogs = Array.from(document.querySelectorAll(
            '.dy-creator-content-modal-content, .dy-creator-content-modal-wrap, .semi-modal-wrap, [role="dialog"]'
        )).filter(visible);
        const dialog = dialogs.find(element => normalize(element.innerText).includes('设置横封面获更多流量'));
        if (!dialog) return { visible: false, clicked: false };
        if (!shouldClick) return { visible: true, clicked: false };
        const target = Array.from(dialog.querySelectorAll('button, [role="button"]')).find(button => {
            const text = normalize(button.innerText || button.textContent);
            return text === '设置横封面' && visible(button)
                && !button.disabled && button.getAttribute('aria-disabled') !== 'true';
        });
        if (!target) return { visible: true, clicked: false };
        target.click();
        return { visible: true, clicked: true };
    }"""

    popup_seen = False
    for elapsed in range(max(1, timeout_seconds)):
        try:
            state = page.evaluate(state_script, True) or {}
        except Exception as exc:
            logger.error("读取抖音横封面推荐弹窗失败：%s", exc)
            return False
        if not state.get("visible"):
            # 平台有两种界面：一种直接切换横封面 Tab，另一种先给说明弹窗。
            # 未出现弹窗时，给 Tab 一小段稳定时间后继续即可。
            if elapsed >= 2:
                return True
            page.wait_for_timeout(1_000)
            continue

        popup_seen = True
        if not state.get("clicked"):
            logger.error("抖音横封面推荐弹窗出现，但未找到可用的“设置横封面”按钮")
            return False
        logger.info("已确认抖音“设置横封面获更多流量”弹窗，等待进入横封面面板")
        for close_elapsed in range(max(1, timeout_seconds)):
            try:
                remaining = page.evaluate(state_script, False) or {}
            except Exception as exc:
                logger.error("确认抖音横封面推荐弹窗是否关闭失败：%s", exc)
                return False
            if not remaining.get("visible"):
                return True
            if close_elapsed and close_elapsed % 3 == 0:
                logger.info("抖音横封面推荐弹窗仍在切换，已等待 %s 秒", close_elapsed)
            page.wait_for_timeout(1_000)
        logger.error("抖音横封面推荐弹窗未在 %s 秒内关闭", timeout_seconds)
        return False

    if popup_seen:
        logger.error("抖音横封面推荐弹窗状态未确认，拒绝继续上传横封面")
        return False
    return True


def _continue_saved_horizontal_to_vertical_cover(page, *, timeout_seconds: int = 8) -> Optional[bool]:
    """在横封面保存后按平台要求切回竖封面；无该建议层时返回 ``False``。"""
    state_script = """shouldClick => {
        const normalize = value => (value || '').replace(/\\s+/g, '');
        const visible = element => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0
                && style.visibility !== 'hidden' && style.display !== 'none';
        };
        const dialogs = Array.from(document.querySelectorAll(
            '.dy-creator-content-modal-content, .dy-creator-content-modal-wrap, .semi-modal-wrap, [role="dialog"]'
        )).filter(visible);
        const dialog = dialogs.find(element => normalize(element.innerText).includes('设置竖封面获更多流量'));
        if (!dialog) return { visible: false, clicked: false };
        if (!shouldClick) return { visible: true, clicked: false };
        const target = Array.from(dialog.querySelectorAll('button, [role="button"]')).find(button => {
            const text = normalize(button.innerText || button.textContent);
            return text === '设置竖封面' && visible(button)
                && !button.disabled && button.getAttribute('aria-disabled') !== 'true';
        });
        if (!target) return { visible: true, clicked: false };
        target.click();
        return { visible: true, clicked: true };
    }"""
    try:
        state = page.evaluate(state_script, True) or {}
    except Exception as exc:
        logger.error("读取抖音横封面保存后的竖封面建议层失败：%s", exc)
        return None
    if not state.get("visible"):
        return False
    if not state.get("clicked"):
        logger.error("抖音竖封面建议层出现，但未找到精确的“设置竖封面”按钮")
        return None
    logger.info("已确认抖音横封面保存后的“设置竖封面”建议层")
    for elapsed in range(max(1, timeout_seconds)):
        try:
            remaining = page.evaluate(state_script, False) or {}
        except Exception as exc:
            logger.error("确认抖音竖封面建议层是否关闭失败：%s", exc)
            return None
        if not remaining.get("visible"):
            return True
        if elapsed and elapsed % 3 == 0:
            logger.info("抖音竖封面建议层仍在关闭，已等待 %s 秒", elapsed)
        page.wait_for_timeout(1_000)
    logger.error("抖音竖封面建议层未在 %s 秒内关闭", timeout_seconds)
    return None


def _click_cover_confirm(page, modal, timeout_seconds: int = 90) -> bool:
    """等待封面编辑器完成生成并点击可用的“完成”；不可用时不得继续发布。"""
    confirm_selectors = [
        "button:has-text('完成')", "span:has-text('完成')", "button:has-text('保存')", "text=保存",
        "text=完成", "text=确定", "text=确认", "text=裁剪并保存"
    ]
    for elapsed in range(timeout_seconds):
        confirm_btn = _find_visible_element(modal, confirm_selectors)
        try:
            if confirm_btn and confirm_btn.is_enabled():
                confirm_btn.click(timeout=2000)
                logger.info("已点击右下角'完成'保存封面！")
                page.wait_for_timeout(2000)
                return True
        except Exception as exc:
            logger.debug("点击抖音封面完成按钮失败，继续等待：%s", exc)
        if elapsed and elapsed % 15 == 0:
            logger.info("抖音封面编辑器仍在生成，已等待 %s 秒", elapsed)
        page.wait_for_timeout(1_000)
    logger.error("抖音封面编辑器的“完成”按钮在 %s 秒内始终不可用", timeout_seconds)
    return False


def _wait_for_cover_editor_closed(page, modal, *, timeout_seconds: int = 10) -> bool:
    """等待当前封面编辑器保存落地；不能用 Escape 取消平台的异步保存。"""
    editor_still_open = True
    try:
        for elapsed in range(timeout_seconds):
            editor_still_open = (
                _find_visible_element(page, ["button:has-text('保存')", "button:has-text('取消')"], timeout_ms=500) is not None
                if modal is page
                else modal.is_visible(timeout=500)
            )
            if not editor_still_open:
                return True
            if elapsed and elapsed % 3 == 0:
                logger.info("抖音封面仍在保存，已等待 %s 秒", elapsed)
            page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.error("无法确认抖音封面编辑器是否关闭：%s", exc)
        return False
    logger.error("抖音封面编辑器在保存后仍未关闭，拒绝继续自主声明或发布")
    return False


def _accept_set_vertical_cover_recommendation(page) -> bool:
    """仅处理已观测的“设置封面获更多流量”弹窗中的“设置竖封面”下一步。"""
    try:
        return bool(page.evaluate(
            """() => {
                const buttons = Array.from(document.querySelectorAll('button, [role="button"]'));
                const matches = buttons.map(button => {
                    const text = (button.innerText || button.textContent || '').trim().replace(/\\s+/g, '');
                    const rect = button.getBoundingClientRect();
                    return { button, text, rect };
                }).filter(item => item.text === '设置竖封面' && item.rect.width > 0 && item.rect.height > 0)
                    .sort((left, right) => left.rect.y - right.rect.y);
                const target = matches[0]?.button;
                if (!target) return false;
                target.click();
                return true;
            }"""
        ))
    except Exception as exc:
        logger.debug("读取抖音“设置竖封面”推荐弹窗失败：%s", exc)
        return False


def _opened_cover_editor(page):
    """返回已实际打开的封面编辑器；主页面回退不算一次成功点击。"""
    modal = _find_active_modal(page, [
        ".dy-creator-content-modal-body", ".dy-creator-content-modal-wrap",
        ".semi-modal-wrap", "div[role='dialog']", ".modal-container",
    ])
    return None if modal is page else modal


def _click_cover_entry(page, selectors: Iterable[str], *, artifact_dir: Optional[Path], artifact_name: str, cover_path_abs: str):
    """将指定比例的封面卡槽滚入视口并打开编辑器；不猜测其它比例的入口。"""
    cover_entry = _find_visible_element(page, selectors)
    if not cover_entry:
        logger.warning("未找到抖音%s封面设置入口", artifact_name)
        return None
    try:
        cover_entry.scroll_into_view_if_needed(timeout=2_000)
    except Exception as exc:
        logger.debug("抖音%s封面入口滚动到视口失败，继续由点击闸门确认：%s", artifact_name, exc)
    try:
        cover_entry.click(timeout=2_000)
    except Exception as exc:
        # 新版创作者中心会先打开编辑器，再让 Playwright 因底层节点重绘报
        # timeout。截图证据表明该异常不是可靠的失败信号，必须先读取结果态，
        # 否则第二次点击会把已经打开的编辑器误报为失败。
        page.wait_for_timeout(300)
        opened_editor = _opened_cover_editor(page)
        if opened_editor:
            logger.info("抖音%s封面入口点击返回异常，但编辑器已实际打开", artifact_name)
            return opened_editor
        logger.debug("抖音%s封面入口普通点击受阻，尝试同一入口 force 点击：%s", artifact_name, exc)
        try:
            cover_entry.click(timeout=2_000, force=True)
        except Exception as force_exc:
            page.wait_for_timeout(300)
            opened_editor = _opened_cover_editor(page)
            if opened_editor:
                logger.info("抖音%s封面入口 force 点击返回异常，但编辑器已实际打开", artifact_name)
                return opened_editor
            logger.error("抖音%s封面入口无法点击：%s", artifact_name, force_exc)
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, f"douyin_{artifact_name}_cover_entry_click_failed", cover_path_abs)
            return None
    page.wait_for_timeout(2_000)
    if artifact_dir:
        capture_cover_evidence(page, artifact_dir, f"douyin_{artifact_name}_cover_entry_opened", cover_path_abs)
    return _find_active_modal(page, [
        ".dy-creator-content-modal-body", ".dy-creator-content-modal-wrap",
        ".semi-modal-wrap", "div[role='dialog']", ".modal-container",
    ])


def wait_for_cover_validation(page, timeout_seconds: int = 120) -> bool:
    """等待平台封面检测完成；失败、超时或页面不可读都不允许进入发布。"""
    success_markers = (
        "封面效果检测通过",
        "封面检测通过",
        "暂未发现封面低质问题",
    )
    failed_markers = (
        "封面检测未通过", "封面不合格", "封面违规", "封面异常",
    )
    missing_markers = (
        "横/竖双封面缺失", "横竖双封面缺失", "横封面缺失", "竖封面缺失",
        "建议同时设置横版和竖版的封面",
    )
    refreshed = False
    try:
        for elapsed in range(timeout_seconds):
            text = get_page_text(page)
            if any(marker in text for marker in failed_markers):
                logger.error("抖音封面检测明确拒绝")
                return False
            # 保存双封面时平台会短暂保留前一轮“横/竖双封面缺失”提示；
            # 同一页面已经给出具名成功态时，成功态才是当前检测结果。
            if any(marker in text for marker in success_markers):
                logger.info("抖音封面检测已明确通过")
                return True
            # 卡槽已完成持久化后，检测区域仍可能保留上传前的缺失结果。
            # 给异步保存短暂收敛时间，然后仅重新检测一次；不可因旧提示立即熔断。
            if elapsed >= 3 and not refreshed and any(marker in text for marker in missing_markers):
                refresh = _find_visible_element(page, ['button:has-text("重新检测")'])
                if refresh:
                    refresh.click(timeout=2_000)
                    refreshed = True
                    logger.info("双封面保存后已请求一次重新检测，等待最新结果")
            if elapsed and elapsed % 15 == 0:
                logger.info("抖音封面仍在检测，已等待 %s 秒", elapsed)
            page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.error("等待抖音封面检测时页面不可读：%s", exc)
        return False
    logger.error("抖音封面检测超过 %s 秒未完成，拒绝发布", timeout_seconds)
    return False


def _visible_cover_slot_image_sources(page) -> dict[str, str]:
    """读取可见横竖卡槽的缩略图地址，供保存后证明平台确已替换默认图。"""
    try:
        slots = page.evaluate(
            """() => Object.fromEntries(Array.from(document.querySelectorAll('[class*="coverControl"]'))
                .filter(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0;
                })
                .map(element => {
                    const text = (element.innerText || element.textContent || '').replace(/\\s+/g, '');
                    const image = element.querySelector('img');
                    const source = image?.currentSrc || image?.src || '';
                    const slot = text.includes('竖封面3:4') ? 'vertical'
                        : text.includes('横封面4:3') ? 'horizontal' : '';
                    return [slot, source];
                }).filter(([slot, source]) => slot && source))"""
        )
    except Exception as exc:
        logger.error("抖音封面保存后无法读取卡槽缩略图：%s", exc)
        return {}
    return {
        str(slot): str(source)
        for slot, source in (slots or {}).items()
        if str(slot) in {"vertical", "horizontal"} and str(source).strip()
    }


def _wait_for_cover_slot_source_change(
    page,
    *,
    slot: str,
    original_source: str,
    timeout_seconds: int = 20,
) -> bool:
    """等待指定封面卡槽从原视频默认缩略图切换到平台已保存的新图。"""
    original = (original_source or "").strip()
    if not original:
        logger.error("抖音%s封面卡槽缺少保存前缩略图，不能确认平台已落库", slot)
        return False
    for elapsed in range(max(1, timeout_seconds)):
        current = _visible_cover_slot_image_sources(page).get(slot, "").strip()
        if current and current != original:
            logger.info("抖音%s封面卡槽缩略图已变更，平台保存已落库", slot)
            return True
        if elapsed and elapsed % 5 == 0:
            logger.info("抖音%s封面卡槽仍未替换缩略图，已等待 %s 秒", slot, elapsed)
        page.wait_for_timeout(1_000)
    logger.error("抖音%s封面保存后卡槽缩略图未变化，拒绝后续发布", slot)
    return False


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
        initial_slot_sources = _visible_cover_slot_image_sources(page)
        if not initial_slot_sources.get("vertical") or (
            horizontal_cover_path_abs and not initial_slot_sources.get("horizontal")
        ):
            logger.error("抖音横竖封面卡槽初始缩略图不完整，不能证明后续保存已落库")
            return False

        # 平台当前每次弹窗只保存一种比例。必须先保存竖封面并等待弹窗关闭，
        # 再打开横封面卡槽；在同一弹窗内切换比例会丢失前一种封面。
        modal = _click_cover_entry(
            page,
            ["[class*='coverControl']:has-text('竖封面3:4')", "text=竖封面3:4"],
            artifact_dir=artifact_dir,
            artifact_name="vertical",
            cover_path_abs=cover_path_abs,
        )
        if not modal:
            return False

        if not _apply_cover_in_current_panel(
            page,
            modal,
            cover_path_abs,
            artifact_dir=artifact_dir,
            artifact_prefix="douyin_cover",
            allow_thumbnail_match_fallback=True,
        ):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_vertical_cover_unconfirmed", cover_path_abs)
            return False

        if not _click_cover_confirm(page, modal):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_vertical_cover_confirm_unavailable", cover_path_abs)
            return False
        if horizontal_cover_path_abs:
            # 新版页面在保存竖封面后弹出“设置横封面获更多流量”说明层，
            # 其关闭后仍保留同一个封面编辑器，并已切换到横封面面板。若此处
            # 先等编辑器关闭，会把平台期待的下一步误判为超时。
            if not _accept_horizontal_cover_recommendation(page):
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_recommendation_unconfirmed", horizontal_cover_path_abs)
                return False
            modal = _find_active_modal(page, [
                ".dy-creator-content-modal-body", ".dy-creator-content-modal-wrap",
                ".semi-modal-wrap", "div[role='dialog']", ".modal-container",
            ])
            # `_find_active_modal` 为单封面页面保留 page 回退；此处竖封面
            # 编辑器已经关闭，主页面不是横封面面板，必须重新点 4:3 卡槽。
            if modal is page:
                modal = None
            if not modal:
                modal = _click_cover_entry(
                    page,
                    ["[class*='coverControl']:has-text('横封面4:3')", "text=横封面4:3"],
                    artifact_dir=artifact_dir,
                    artifact_name="horizontal",
                    cover_path_abs=horizontal_cover_path_abs,
                )
            if not modal:
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_entry_failed", horizontal_cover_path_abs)
                return False
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_entry_opened", horizontal_cover_path_abs)
            if not _apply_cover_in_current_panel(
                page,
                modal,
                horizontal_cover_path_abs,
                artifact_dir=artifact_dir,
                artifact_prefix="douyin_horizontal_cover",
                allow_thumbnail_match_fallback=True,
            ):
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_unconfirmed", horizontal_cover_path_abs)
                return False
            if not _click_cover_confirm(page, modal):
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_confirm_unavailable", horizontal_cover_path_abs)
                return False
            needs_vertical_cover = _continue_saved_horizontal_to_vertical_cover(page)
            if needs_vertical_cover is None:
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_vertical_cover_recommendation_unconfirmed", horizontal_cover_path_abs)
                return False
            if needs_vertical_cover:
                modal = _find_active_modal(page, [
                    ".dy-creator-content-modal-body", ".dy-creator-content-modal-wrap",
                    ".semi-modal-wrap", "div[role='dialog']", ".modal-container",
                ])
                if modal is page:
                    logger.error("抖音要求设置竖封面后未保留封面编辑器，拒绝猜测页面控件")
                    if artifact_dir:
                        capture_cover_evidence(page, artifact_dir, "douyin_required_vertical_editor_missing", cover_path_abs)
                    return False
                if not _apply_cover_in_current_panel(
                    page,
                    modal,
                    cover_path_abs,
                    artifact_dir=artifact_dir,
                    artifact_prefix="douyin_required_vertical_cover",
                    allow_thumbnail_match_fallback=True,
                ):
                    if artifact_dir:
                        capture_cover_evidence(page, artifact_dir, "douyin_required_vertical_cover_unconfirmed", cover_path_abs)
                    return False
                if not _click_cover_confirm(page, modal):
                    if artifact_dir:
                        capture_cover_evidence(page, artifact_dir, "douyin_required_vertical_cover_confirm_unavailable", cover_path_abs)
                    return False
            if not _wait_for_cover_editor_closed(page, modal):
                if artifact_dir:
                    capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_modal_unclosed", horizontal_cover_path_abs)
                return False

        if not _wait_for_cover_slot_source_change(
            page, slot="vertical", original_source=initial_slot_sources["vertical"],
        ):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_vertical_cover_persistence_unconfirmed", cover_path_abs)
            return False
        if horizontal_cover_path_abs and not _wait_for_cover_slot_source_change(
            page, slot="horizontal", original_source=initial_slot_sources["horizontal"],
        ):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_horizontal_cover_persistence_unconfirmed", horizontal_cover_path_abs)
            return False

        saved_slot_sources = _visible_cover_slot_image_sources(page)
        if saved_slot_sources.get("vertical") == initial_slot_sources.get("vertical") or (
            horizontal_cover_path_abs
            and saved_slot_sources.get("horizontal") == initial_slot_sources.get("horizontal")
        ):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_cover_slots_unconfirmed", cover_path_abs)
            return False
        if not wait_for_cover_validation(page):
            if artifact_dir:
                capture_cover_evidence(page, artifact_dir, "douyin_cover_validation_blocked", cover_path_abs)
            return False
        if artifact_dir:
            capture_cover_evidence(page, artifact_dir, "douyin_cover_applied", cover_path_abs)
        return True

    except Exception as e:
        logger.warning("抖音封面应用过程发生异常: %s", e)
        if artifact_dir:
            capture_cover_evidence(page, artifact_dir, "douyin_cover_interaction_failed", cover_path)

    return False


def _normalized_metadata_text(text: str) -> str:
    """移除平台编辑器用于排版的不可见字符后比较可见元信息。"""
    return "".join(
        (text or "").replace("\u200b", "").replace("\ufeff", "").replace("\u2060", "").split(),
    )


def _is_terminal_hashtag_platform_expansion(expected: str, actual: str) -> bool:
    """只接受末尾同源话题被平台加 1--6 个中文限定字的规范化。

    平台会把 ``#英文阅读`` 显示为 ``#英文阅读书单`` 一类推荐话题。正文及此前
    所有话题必须完全相同，且标题永远不走本例外，避免把平台改写误当作原文一致。
    """
    expected_prefix, expected_marker, expected_tag = expected.rpartition("#")
    actual_prefix, actual_marker, actual_tag = actual.rpartition("#")
    if not expected_marker or not actual_marker or expected_prefix != actual_prefix:
        return False
    if not expected_tag or not actual_tag.startswith(expected_tag):
        return False
    extension = actual_tag[len(expected_tag):]
    return 1 <= len(extension) <= 6 and all("\u4e00" <= char <= "\u9fff" for char in extension)


def _filled_text_matches(control, expected: str, *, is_title: bool) -> bool:
    """回读已填写的作品元信息；任何无法读取或不一致均按失败处理。"""
    expected_normalized = _normalized_metadata_text(expected)
    if not expected_normalized:
        return False
    try:
        actual = control.input_value() if is_title else control.inner_text()
    except Exception as exc:
        logger.error("抖音%s填写后无法回读：%s", "标题" if is_title else "作品描述", exc)
        return False
    actual_normalized = _normalized_metadata_text(actual)
    if (
        not is_title
        and _is_terminal_hashtag_platform_expansion(expected_normalized, actual_normalized)
    ):
        logger.warning(
            "抖音仅将末尾话题规范化扩写，正文与此前话题保持一致：expected=%r actual=%r",
            expected[-80:], str(actual)[-80:],
        )
        return True
    if actual_normalized != expected_normalized:
        logger.error(
            "抖音%s填写后回读不一致，拒绝发布：expected=%r actual=%r",
            "标题" if is_title else "作品描述",
            expected[:80],
            str(actual)[:80],
        )
        return False
    return True


def final_metadata_matches(page, title_text: str, description_text: str) -> bool:
    """最终点击前回读元信息，防止平台异步替换标题或话题。"""
    title_input = get_title_input(page)
    editor = get_description_editor(page)
    if not title_input or not editor:
        logger.error("抖音最终提交前无法定位标题或正文，拒绝发布")
        return False
    title = " ".join((title_text or "").split()).strip()[:50]
    description = (description_text or "").strip()
    return _filled_text_matches(title_input, title, is_title=True) and _filled_text_matches(
        editor,
        description,
        is_title=False,
    )


def fill_publish_fields(
    page,
    title_text: str,
    description_text: str,
    artifact_dir: Path,
    cover_path: Optional[str] = None,
    horizontal_cover_path: Optional[str] = None,
) -> bool:
    """填入作品标题和描述并应用封面，停在提交前页面；不保存草稿、不发布。"""
    title_input = get_title_input(page)
    editor = get_description_editor(page)
    if not title_input or not editor:
        return False
    title = " ".join((title_text or "").split()).strip()
    description = (description_text or "").strip()
    if not title or not description or not cover_path or not Path(cover_path).is_file():
        logger.error("抖音发布元信息不完整：title=%s description=%s cover=%s", bool(title), bool(description), bool(cover_path and Path(cover_path).is_file()))
        return False
    if horizontal_cover_path and not Path(horizontal_cover_path).is_file():
        logger.error("抖音横封面文件不存在: %s", horizontal_cover_path)
        return False
    title = title[:50]
    title_input.fill(title)
    editor.fill(description)
    # 平台候选可能把原话题扩写为另一个话题；不得点击候选或让它替换本地审计包。
    # 仅关闭浮层、失焦，再做逐字回读和封面动作。
    try:
        editor.press("Escape")
        editor.evaluate("element => element.blur()")
        page.keyboard.press("Escape")
    except Exception as exc:
        logger.debug("关闭抖音作品描述建议浮层失败，继续由后续点击闸门验证: %s", exc)
    page.wait_for_timeout(500)
    if not _filled_text_matches(title_input, title, is_title=True):
        return False
    if not _filled_text_matches(editor, description, is_title=False):
        return False

    logger.info("开始应用抖音封面: %s", cover_path)
    cover_upload_path = prepare_douyin_cover_upload_file(cover_path)
    horizontal_source = horizontal_cover_path or cover_path
    horizontal_cover_upload_path = prepare_douyin_horizontal_cover_upload_file(horizontal_source)
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

    if not select_self_declaration(page, artifact_dir):
        logger.error("抖音自主声明未能确认，停止后续发布")
        return False
    
    capture_controls(page, artifact_dir, "douyin_ready_to_submit")
    logger.info("已填入抖音作品标题、描述和自主声明，仍未保存草稿或发布")
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


def _is_capacity_congestion_only_quick_check(text: str) -> bool:
    """仅识别平台检测服务拥堵的完整固定提示，绝不吞掉其它风险。"""
    if not all(marker in text for marker in DOUYIN_CAPACITY_CONGESTION_REQUIRED_TEXT):
        return False
    return not any(
        marker in text
        for marker in DOUYIN_BLOCKING_QUICK_CHECK_MARKERS
        if marker not in DOUYIN_CAPACITY_CONGESTION_COMPATIBLE_MARKERS
    )


def quick_detection_allows_submission(page, timeout_seconds: int = DOUYIN_QUICK_CHECK_TIMEOUT_SECONDS) -> bool:
    """刷新并读取最终提交前的快速检测区；仅服务拥堵固定提示可受控放行。"""
    refresh_requested = False
    try:
        refresh_button = page.get_by_text("重新检测", exact=True)
        if (
            refresh_button.count() == 1
            and refresh_button.is_visible(timeout=1_000) is True
            and refresh_button.is_enabled() is True
        ):
            refresh_button.click(timeout=2_000)
            refresh_requested = True
            logger.info("已点击抖音快速检测“重新检测”，等待本次封面状态刷新")
            page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.debug("抖音快速检测重新检测按钮不可用，读取当前结果：%s", exc)
    try:
        for elapsed in range(max(1, timeout_seconds)):
            text = _normalize_page_text(get_page_text(page))
            if not text:
                logger.error("抖音快速检测区域为空或不可读，拒绝发布")
                return False
            if _is_capacity_congestion_only_quick_check(text):
                logger.warning("抖音快速检测服务拥堵；其它发布前闸门已通过，按受控例外继续提交")
                return True
            matched = tuple(marker for marker in DOUYIN_BLOCKING_QUICK_CHECK_MARKERS if marker in text)
            pending = tuple(marker for marker in DOUYIN_PENDING_QUICK_CHECK_MARKERS if marker in text)
            if not matched and not pending:
                logger.info("抖音快速检测未发现已知红黄阻断提示")
                return True
            if matched and (not refresh_requested or elapsed == max(1, timeout_seconds) - 1):
                logger.error("抖音快速检测出现阻断提示 %s，停止最终发布", "、".join(matched))
                return False
            if pending and elapsed == max(1, timeout_seconds) - 1:
                logger.error("抖音快速检测仍在进行 %s，超时后停止最终发布", "、".join(pending))
                return False
            if elapsed and elapsed % 10 == 0:
                waiting_for = "、".join(matched or pending)
                logger.info("抖音快速检测仍在刷新（%s），已等待 %s 秒", waiting_for, elapsed)
            page.wait_for_timeout(1_000)
    except Exception as exc:
        logger.error("抖音快速检测区域无法读取，拒绝发布：%s", exc)
        return False
    return False


def wait_for_publish_submission(
    page,
    *,
    title_text: str,
    description_text: str,
    timeout_seconds: int = 180,
) -> bool:
    """等待抖音接受提交；最终可见状态仍交给作品管理回查确认。"""
    success_markers = ("发布成功", "提交成功", "作品发布成功", "等待审核", "发布完成")
    failure_markers = ("发布失败", "提交失败", "不成功")
    upload_markers = ("作品上传中", "上传完成后将自动发布", "请勿关闭页面")
    for elapsed in range(timeout_seconds):
        if "manage" in page.url:
            logger.info("已成功跳转至抖音作品管理页面: %s", page.url)
            return True
        text = get_page_text(page)
        if "作品管理" in text and any(marker in text for marker in success_markers):
            logger.info("检测到抖音作品管理页发布成功提示")
            return True
        if any(marker in text for marker in success_markers):
            logger.info("检测到抖音成功发布提示文本")
            return True
        if any(marker in text for marker in upload_markers):
            if elapsed and elapsed % 30 == 0:
                logger.info("抖音发布后仍在上传，已等待 %s 秒", elapsed)
            page.wait_for_timeout(1_000)
            continue
        if any(marker in text for marker in failure_markers):
            logger.error("抖音页面提示提交失败: %s", " ".join(text.split())[:500])
            return False
        page.wait_for_timeout(1_000)
    return False


def submission_preflight_allows_publish(page, artifact_dir: Path, *, title_text: str, description_text: str) -> bool:
    """在最终点击前复核声明、元信息和快速检测；通过也不点击发布。"""
    # 填发表单后若有模态弹窗拦截（如 Douyin / Semi Design 封面弹窗），主动尝试清理。
    # 这只处理已完成的残留遮罩，不把 Escape 当成封面保存手段。
    try:
        modal = page.locator(".dy-creator-content-modal-wrap, .semi-modal-wrap").first
        if modal.count() > 0 and modal.is_visible(timeout=500):
            logger.warning("发现未关闭的弹窗遮罩，发送 Escape 键清理")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception:
        pass

    if not select_self_declaration(page, artifact_dir):
        return False

    if not final_metadata_matches(page, title_text, description_text):
        capture_controls(page, artifact_dir, "douyin_final_metadata_mismatch")
        return False

    if not quick_detection_allows_submission(page):
        capture_controls(page, artifact_dir, "douyin_quick_detection_blocked")
        return False

    capture_controls(page, artifact_dir, "douyin_preflight_ready")
    logger.info("抖音最终提交前核验通过；尚未点击发布")
    return True


def publish_after_review(
    page,
    artifact_dir: Path,
    *,
    title_text: str,
    description_text: str,
    preflight_checked: bool = False,
) -> bool:
    """点击最终发布并采集提交后页面；只表示提交已被平台接受，不直接记 PUBLISHED。"""
    if not preflight_checked and not submission_preflight_allows_publish(
        page,
        artifact_dir,
        title_text=title_text,
        description_text=description_text,
    ):
        return False

    button = get_publish_button(page)
    if not button:
        return False
    try:
        button.click(timeout=5000)
    except Exception as exc:
        logger.error("抖音最终发布按钮点击未确认，拒绝强制重点击: %s", exc)
        capture_controls(page, artifact_dir, "douyin_submit_click_failed")
        return False
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
    horizontal_cover_path: Optional[str] = None,
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
        horizontal_cover_path=horizontal_cover_path,
    ):
        return EXIT_UNCONFIRMED
    if not submission_preflight_allows_publish(
        page,
        artifact_dir,
        title_text=title_text,
        description_text=description_text,
    ):
        return EXIT_UNCONFIRMED
    if publish_after_review(
        page,
        artifact_dir,
        title_text=title_text,
        description_text=description_text,
        preflight_checked=True,
    ):
        return EXIT_UNDER_REVIEW
    return EXIT_SUBMISSION_UNCONFIRMED


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
    parser.add_argument("--horizontal-cover", type=Path, help="横版封面图片路径；省略时由竖版封面生成")
    parser.add_argument("--copy", type=Path, help="发布文案路径")
    parser.add_argument("--title-file", type=Path, help="发布标题路径")
    parser.add_argument(
        "--douyin-launch-ticket",
        dest="douyin_launch_ticket_id",
        help="由已领取账本签发的一次性浏览器启动 ticket；不能由来源文本替代",
    )
    parser.add_argument(
        "--douyin-launch-token",
        help="与 --douyin-launch-ticket 成对的单次启动 token；不写入日志或账本明文",
    )
    parser.add_argument("--state", type=Path, default=Path("output/douyin_state.json"), help="Playwright 登录态文件")
    parser.add_argument("--evidence-dir", type=Path, help="本次动作的独立页面证据目录")
    parser.add_argument("--no-headless", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--fail-fast-login", action="store_true", help="登录失效时立即退出，不等待扫码")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--login-only", action="store_true", help="仅打开创作者中心并保存登录态")
    actions.add_argument("--calibrate", action="store_true", help="采集当前发布页控件快照，不上传、不发布")
    actions.add_argument("--calibrate-after-upload", action="store_true", help="仅上传并采集表单控件，绝不填写或发布")
    parser.add_argument("--upload-wait-seconds", type=int, default=900, help="等待抖音文件上传完成的最长秒数")
    parser.add_argument("--prepare-description", action="store_true", help="仅填入标题和作品描述，停在提交前页面")
    actions.add_argument("--preflight-only", action="store_true", help="上传并完成最终提交前核验，但绝不点击发布")
    actions.add_argument("--publish", action="store_true", help="发布视频；校准完成前会安全拒绝")
    actions.add_argument("--verify-only", action="store_true", help="仅核对作品状态；校准完成前会安全拒绝")
    parser.add_argument(
        "--operator-recovery-stage",
        choices=[DOUYIN_UI_STAGE_PUBLISH_PRE_SUBMIT, DOUYIN_UI_STAGE_MANAGEMENT_VERIFY],
        help="仅人工恢复校准：声明本次采集的熔断阶段；不能与 --publish 合用",
    )
    parser.add_argument(
        "--operator-recovery-reason",
        help="仅人工恢复校准：本次非最终校准的具体原因，连同证据目录写入审计记录",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (args.publish or args.preflight_only) and (not args.video or not args.copy or not args.title_file or not args.cover):
        logger.error("--publish/--preflight-only requires --video, --copy, --title-file and --cover")
        return EXIT_FAILED
    if args.calibrate_after_upload and not args.video:
        logger.error("--calibrate-after-upload requires --video")
        return EXIT_FAILED
    if args.verify_only and not args.copy:
        logger.error("--verify-only requires --copy for an exact work identity check")
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
    if args.cover and not args.cover.is_file():
        logger.error("封面文件不存在: %s", args.cover)
        return EXIT_FAILED
    if args.horizontal_cover and not args.horizontal_cover.is_file():
        logger.error("横版封面文件不存在: %s", args.horizontal_cover)
        return EXIT_FAILED

    guard_exit = _guard_before_browser(args)
    if guard_exit is not None:
        return guard_exit

    artifact_dir = args.evidence_dir or args.state.parent / "douyin_calibration"
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
                horizontal_cover_path=str(args.horizontal_cover) if args.prepare_description and args.horizontal_cover else None,
            )
            browser.close()
            return EXIT_UPLOADED_FOR_CALIBRATION if uploaded else EXIT_UNCONFIRMED

        if args.verify_only:
            title_text = args.title_file.read_text(encoding="utf-8") if args.title_file else ""
            state = verify_management_publication(
                page,
                artifact_dir,
                args.copy.read_text(encoding="utf-8"),
                title_text,
            )
            browser.close()
            if state == MANAGEMENT_PUBLISHED:
                logger.info("抖音作品管理页已确认本次作品已发布")
                return EXIT_OK
            if state == MANAGEMENT_UNDER_REVIEW:
                logger.info("抖音作品管理页显示本次作品仍在审核中")
                return EXIT_UNDER_REVIEW
            logger.warning("作品管理页未能确认本次作品状态，保守返回未确认")
            return EXIT_SUBMISSION_UNCONFIRMED

        if args.preflight_only:
            if not wait_for_video_upload_input(page):
                browser.close()
                return EXIT_UNCONFIRMED
            title_text = args.title_file.read_text(encoding="utf-8") if args.title_file else ""
            description_text = args.copy.read_text(encoding="utf-8") if args.copy else ""
            if not title_text.strip() or not description_text.strip():
                logger.error("抖音预检标题或文案为空，拒绝上传")
                browser.close()
                return EXIT_UNCONFIRMED
            prepared = upload_for_calibration(
                page,
                str(args.video),
                artifact_dir,
                upload_wait_seconds=args.upload_wait_seconds,
                title_text=title_text,
                description_text=description_text,
                cover_path=str(args.cover),
                horizontal_cover_path=str(args.horizontal_cover) if args.horizontal_cover else None,
            )
            if not prepared or not submission_preflight_allows_publish(
                page,
                artifact_dir,
                title_text=title_text,
                description_text=description_text,
            ):
                browser.close()
                return EXIT_UNCONFIRMED
            browser.close()
            return EXIT_OK

        if args.publish:
            if not wait_for_video_upload_input(page):
                browser.close()
                return EXIT_UNCONFIRMED
            title_text = args.title_file.read_text(encoding="utf-8") if args.title_file else ""
            description_text = args.copy.read_text(encoding="utf-8") if args.copy else ""
            if not title_text.strip() or not description_text.strip():
                logger.error("抖音发布标题或文案为空，拒绝上传")
                browser.close()
                return EXIT_UNCONFIRMED
            result = upload_and_publish(
                page,
                str(args.video),
                artifact_dir,
                upload_wait_seconds=args.upload_wait_seconds,
                title_text=title_text,
                description_text=description_text,
                cover_path=str(args.cover) if args.cover else None,
                horizontal_cover_path=str(args.horizontal_cover) if args.horizontal_cover else None,
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
