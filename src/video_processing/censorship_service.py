"""内容审查执行服务 — 违法层(P0/P1/P2) + 频道策略层(CP) 的判定与落地动作

架构 B：从 PipelineManager 抽出 _check_censorship（~120 行），形成可独立测试的内聚单元。
- 判定 委托 censor_engine（纯规则引擎）；
- 执行 由本服务负责：写审查状态、状态机迁移、扣分、加黑名单、发 Telegram。
依赖通过构造注入（db + notify 回调），不与编排器其它职责耦合。

行为与抽出前逐字一致（含 fail-open：审查过程异常 → 返回 False 放行，保持原语义）。

# Modification History
| Version | Date       | Author          | Description                                                    |
|---------|------------|-----------------|---------------------------------------------------------------|
| 1.0.0   | 2026-06-22 | Claude_Opus_4.8 | 从 pipeline_manager._check_censorship 抽出 CensorshipService（行为逐字保留） |
| 1.1.0   | 2026-06-25 | Claude_Opus_4.8 | P2 命中手动锁定(is_manually_scored=1)视频时改为挂起人工复核(FAILED+TG)而非 force 清零回弹——根治"调分后反复弹回待筛选且分数归0"的困惑；非锁定视频仍按原 deprioritize |
| 1.2.0   | 2026-06-28 | Claude_Opus_4.8 | 受信任频道白名单：channel_id 在 settings.censorship_bypass_channel_set 中→跳过全部审查层(P0/P1/P2/CP)。供运营对自审过的优质频道整体开绿灯（如财经频道的地缘共现词不再误杀） |
| 1.3.0   | 2026-07-09 | Codex | 新增频道策略临时 fail-open 开关：命中 CP 告警时可按紧急策略放行 |
| 1.4.0   | 2026-07-26 | Codex | 审查命中写入 censorship_incidents 独立台账，沉淀规则、上下文和处置决策供专项复盘 |
| 1.5.0   | 2026-07-26 | Codex | 收紧绕过口：频道白名单只跳过 CP，人工复核放行不能绕过 P0 红线 |
"""
import re
import html
import logging
from typing import Callable

from config.settings import settings
from . import censor_engine
# 动作常量在 import 时绑定即可（不会被运行时替换）；判定函数 check_text/check_channel_policy
# 通过 censor_engine.<fn> 在调用时查找，保证测试 monkeypatch censor_engine.check_text 生效。
from .censor_engine import (
    ACTION_REJECT_SIGTERM, ACTION_SUSPEND_MANUAL,
    ACTION_DEPRIORITIZE, ACTION_CHANNEL_POLICY,
)

logger = logging.getLogger(__name__)


class CensorshipService:
    """对单条视频（或切片）执行内容安全审查 + 频道策略检查。

    Args:
        db:     PipelineDB 实例（用于写审查状态/状态机/扣分/黑名单）。
        notify: Telegram 通知回调，签名 notify(html_message: str) -> None。
    """

    def __init__(self, db, notify: Callable[[str], None]):
        self.db = db
        self.notify = notify

    @staticmethod
    def _excerpt_for_match(*texts: str, matched: str = "") -> str:
        """从审查输入中截取命中词附近上下文；找不到则返回开头短摘录。"""
        joined = "\n".join(t for t in texts if t)
        if not joined:
            return ""
        needle = (matched or "").strip()
        if needle and needle not in {"china_sensitive_negative_news", "anti_china_targeted_violence", "severe_negative_news"}:
            lowered = joined.lower()
            idx = lowered.find(needle.lower())
            if idx >= 0:
                start = max(0, idx - 180)
                end = min(len(joined), idx + len(needle) + 180)
                return joined[start:end]
        return joined[:360]

    def _record_incident(
        self,
        yid: str,
        *,
        slice_index: int,
        stage: str,
        result,
        decision: str,
        title: str,
        zh_title: str,
        description: str,
        checked_text: str = "",
    ) -> None:
        """违规台账不能影响主审查流程；失败只记日志。"""
        try:
            matched = getattr(result, "matched", None)
            self.db.record_censorship_incident(
                yid,
                slice_index=slice_index,
                stage=stage,
                level=getattr(result, "level", None) or ("CP" if stage == "channel_policy" else None),
                action=getattr(result, "action", None),
                tag=getattr(result, "tag", None),
                score=getattr(result, "score", None),
                matched=matched,
                channel=getattr(result, "channel", None),
                decision=decision,
                title=title,
                zh_title=zh_title,
                description_preview=description,
                text_excerpt=self._excerpt_for_match(title, zh_title, description, checked_text, matched=str(matched or "")),
            )
        except Exception as exc:
            logger.warning("[CensorLedger] failed to record incident for %s: %s", yid, exc)

    def check(self, yid: str, title: str, description: str = "", zh_title: str = "",
              slice_index: int = 0, subtitle_text: str = "") -> bool:
        """执行审查。返回 True 表示命中（任意层）→ 需要拦截/中断；False 表示全部通过。

        subtitle_text（症结 8）：仅并入违法层 P0/P1/P2（精确词匹配，对长转录安全），
        刻意不并入 CP 共现层——CP「国名+冲突词」全文共现在长转录上几乎必然误杀。
        slice_index（BUG-1）：透传到每一处 db.* 写入，避免切片命中污染父行。
        """
        if not settings.enable_censorship_engine and not settings.enable_channel_policy_filter:
            return False

        manual_bypass = self.db.is_censorship_bypassed(yid, slice_index=slice_index)
        if manual_bypass:
            logger.warning(f"[Censor] Video {yid} BYPASSED by manual review — P0 redlines still enforced.")

        # 受信任频道白名单只豁免 CP 运营边界；违法层 P0/P1/P2 永远先跑。
        bypass_chs = settings.censorship_bypass_channel_set
        channel_policy_bypass = False
        if bypass_chs:
            _row = self.db.get_video_by_youtube_id(yid, slice_index=slice_index)
            _ch = _row.get("channel_id") if _row else None
            if _ch and _ch in bypass_chs:
                channel_policy_bypass = True
                logger.warning(f"[Censor] Video {yid} from trusted channel {_ch} — CP bypass only; P0/P1/P2 still enforced.")

        try:
            # ── A. 违法内容审查（P0/P1/P2） ────────────────────────────────
            if settings.enable_censorship_engine:
                # zh_text 用中文标题；为空但 title 含中文则 fallback 到 title
                zh_for_censor = zh_title or ""
                if not zh_for_censor and re.search(r"[一-龥]", title):
                    zh_for_censor = title

                en_for_censor = f"{title} {description}".strip()
                # 症结 8：字幕正文并入双通道（.ass 中英混排），仅作用于此处违法层。
                if subtitle_text:
                    zh_for_censor = f"{zh_for_censor} {subtitle_text}".strip()
                    en_for_censor = f"{en_for_censor} {subtitle_text}".strip()
                result = censor_engine.check_text(zh_text=zh_for_censor, en_text=en_for_censor)
                if result.hit:
                    if manual_bypass and result.level != "P0":
                        logger.warning(
                            "[Censor] Video %s manual bypass allowed non-P0 hit: %s",
                            yid,
                            result,
                        )
                        return False
                    logger.warning(f"[Censor] Video {yid} hit censorship rule: {result}")
                    self.db.update_video_censor_status(yid, result.tag, result.score, slice_index=slice_index)

                    if result.action == ACTION_REJECT_SIGTERM:
                        self._record_incident(
                            yid, slice_index=slice_index, stage="blocklist", result=result,
                            decision="REJECT_FAILED_BLACKLIST" if settings.enable_blacklist_tombstone else "REJECT_FAILED",
                            title=title, zh_title=zh_title, description=description,
                            checked_text=f"{zh_for_censor}\n{en_for_censor}",
                        )
                        logger.error(f"[Censor] P0 violation. Failing video {yid} and blacklisting.")
                        self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P0 Reject: {result.tag} (matched: '{result.matched}')", slice_index=slice_index)
                        if settings.enable_blacklist_tombstone:
                            self.db.add_to_blacklist(yid, reason=f"censor_p0_{result.matched}")
                        self.notify(
                            f"\U0001f534 <b>Censorship P0 Reject</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code> (via {result.channel})"
                        )
                        return True

                    elif result.action == ACTION_SUSPEND_MANUAL:
                        self._record_incident(
                            yid, slice_index=slice_index, stage="blocklist", result=result,
                            decision="SUSPEND_MANUAL_REVIEW", title=title,
                            zh_title=zh_title, description=description,
                            checked_text=f"{zh_for_censor}\n{en_for_censor}",
                        )
                        logger.warning(f"[Censor] P1 violation. Suspending video {yid} for manual review.")
                        self.db.update_video_status(yid, "FAILED", error_msg=f"Censorship P1 Suspend: {result.tag} (matched: '{result.matched}')", slice_index=slice_index)
                        self.notify(
                            f"\U0001f7e1 <b>Censorship P1 Suspend</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code> (via {result.channel})"
                        )
                        return True

                    elif result.action == ACTION_DEPRIORITIZE:
                        # 手动锁定（is_manually_scored=1）的视频命中 P2：不静默 force 清零回弹——
                        # 那会让用户在面板的调分凭空消失、反复弹回待筛选且无提示（2026-06-25 困惑根因）。
                        # 改为挂起人工复核（FAILED，分数保留），发 Telegram 让人工裁决；
                        # 复核确认安全后可在面板「🔓 复核放行」后重试。
                        if self.db.is_manually_scored(yid, slice_index=slice_index):
                            self._record_incident(
                                yid, slice_index=slice_index, stage="blocklist", result=result,
                                decision="P2_MANUAL_LOCK_SUSPEND", title=title,
                                zh_title=zh_title, description=description,
                                checked_text=f"{zh_for_censor}\n{en_for_censor}",
                            )
                            logger.warning(f"[Censor] P2 hit on manually-scored video {yid}; suspending for manual review (score preserved).")
                            self.db.update_video_status(
                                yid, "FAILED",
                                error_msg=f"Censorship P2 (manual review needed): {result.tag} (matched: '{result.matched}')",
                                slice_index=slice_index,
                            )
                            self.notify(
                                f"\U0001f7e0 <b>Censorship P2 — 人工复核</b>"
                                f"\nTitle: {html.escape(title or '')}\nMatched: <code>{html.escape(str(result.matched or ''))}</code>"
                                f"\n\n⚠️ 手动锁定视频命中 P2 商业合规预警，已挂起等待人工裁决"
                                f"（分数保留，未清零）。确认安全后可在面板「\U0001f513 复核放行」后重试。"
                            )
                            return True
                        self._record_incident(
                            yid, slice_index=slice_index, stage="blocklist", result=result,
                            decision="P2_DEPRIORITIZE", title=title,
                            zh_title=zh_title, description=description,
                            checked_text=f"{zh_for_censor}\n{en_for_censor}",
                        )
                        logger.info(f"[Censor] P2 violation. Deprioritizing video {yid} to 0 points.")
                        self.db.update_video_score(yid, 0, force=True, slice_index=slice_index)
                        self.db.update_video_status(yid, "PENDING", error_msg=f"Censorship P2 Deprioritized: {result.tag}", slice_index=slice_index)
                        self.notify(
                            f"\U0001f535 <b>Censorship P2 Deprioritized</b>"
                            f"\nTitle: {title}\nMatched: <code>{result.matched}</code>"
                        )
                        return True

            # ── B. 频道内容策略检查（CP 层） ────────────────────────────────
            if settings.enable_channel_policy_filter:
                if manual_bypass:
                    logger.warning(f"[ChannelPolicy] Video {yid} manual bypass enabled; skipping CP only.")
                    return False
                if channel_policy_bypass:
                    logger.warning(f"[ChannelPolicy] Video {yid} trusted-channel bypass enabled; skipping CP only.")
                    return False
                # TODO 临时兜底：当前 CP 规则会误杀“频道策略偏差场景”，先放行不中断发布。
                # 完成规则收敛后请将该开关关闭，恢复原有失败/告警流程。
                if settings.enable_channel_policy_fail_open:
                    logger.warning(f"[ChannelPolicy] TEMP_FAIL_OPEN enabled, skipping Channel Policy check for video {yid}.")
                    return False

                zh_for_policy = zh_title or ""
                if not zh_for_policy and re.search(r"[一-龥]", title):
                    zh_for_policy = title

                en_for_policy = f"{title} {description}".strip()
                cp_result = censor_engine.check_channel_policy(zh_text=zh_for_policy, en_text=en_for_policy)
                if cp_result.hit:
                    logger.warning(f"[ChannelPolicy] Video {yid} hit channel policy: {cp_result}")
                    self._record_incident(
                        yid, slice_index=slice_index, stage="channel_policy", result=cp_result,
                        decision="CHANNEL_POLICY_REJECT", title=title,
                        zh_title=zh_title, description=description,
                        checked_text=f"{zh_for_policy}\n{en_for_policy}",
                    )
                    self.db.update_video_censor_status(yid, cp_result.tag, score=0, slice_index=slice_index)
                    self.db.update_video_status(
                        yid, "FAILED",
                        error_msg=f"Channel Policy Reject: {cp_result.tag} (matched: '{cp_result.matched}' via {cp_result.channel})",
                        slice_index=slice_index
                    )
                    self.notify(
                        f"\U0001f6ab <b>Channel Policy Reject</b>"
                        f"\nTitle: {title}"
                        f"\nMatched: <code>{cp_result.matched}</code> (via {cp_result.channel})"
                        f"\n\n⚠️ 此视频超出频道内容定位边界，已拒绝处理。"
                    )
                    return True

        except Exception as e:
            logger.error(f"[Censor] Verification process error: {e}")

        return False
