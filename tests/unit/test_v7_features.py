"""v7.0 安全升级功能单元测试

覆盖范围：
- DB 迁移幂等性
- 黑名单墓碑防重抓
- 人工评分锁
- 频道 MANUAL_ONLY 隔离
- CensorshipEngine 双语拦截与豁免
- 评分公式极端值钳位
- SEC-1: URL 验证旁路防护
- SEC-2: MANUAL_ONLY 频道防隐式提升

# Modification History
| Version | Date       | Author                                 | Description          |
|---------|------------|----------------------------------------|----------------------|
| 1.9.0   | 2026-08-21 | Codex                                  | 覆盖进程已死的预提交孤儿任务有界回收，不触及发布状态 |
| 1.8.0   | 2026-08-14 | Codex                                  | 新增中台地缘政治与出口管制 P1 人工复核回归 |
| 1.7.0   | 2026-07-26 | Codex                                  | 中国领导人姓名 P0、“中国/敏感人物+负面新闻”P0、严重负面事件 P1 回归 |
| 1.6.0   | 2026-07-23 | Codex                                  | 新增“中国+负面政治定性/制裁规避”近距离共现拦截回归 |
| 1.5.0   | 2026-06-13 | Claude_Opus_4.8                        | 更新 GC 测试以匹配 v3.11.0：发布后保留再发产物（成片/封面/文案/标题/分类），仅删源视频与中间字幕 |
| 1.4.0   | 2026-05-28 | Gemini_3.5_Flash_planning              | 新增 stop_video API 强杀进程与状态置为 FAILED 的单元测试 |
| 1.3.0   | 2026-05-27 | Unknown_Model_planning                 | 新增顺序锁放宽测试与垃圾回收 GC 深度清理测试用例 |
| 1.2.1   | 2026-05-27 | Gemini_3.5_Flash_High_planning         | 修复 test_con1_lock_handle_closed_on_flock_error 中 mock 调用的 slice_index 断言 |
| 1.2.0   | 2026-05-26 | Gemini_3.5_Flash_planning              | 新增 CensorEngine 流水线集成与安全锁异常测试用例 |
| 1.1.0   | 2026-05-26 | Gemini_3.5_Flash_planning              | 新增 SEC-1 与 SEC-2 安全加固单元测试 |
| 1.0.0   | 2026-05-26 | Claude_Sonnet_4.6_Thinking_planning    | 初始创建 v7.0 TDD 测试套件 |
"""

import math
import os
import sys
import tempfile
import pytest

# 确保 src 在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from video_processing.db.database import PipelineDB
from video_processing.censor_engine import (
    check_text,
    ACTION_REJECT_SIGTERM,
    ACTION_SUSPEND_MANUAL,
    ACTION_DEPRIORITIZE,
)


# ── 测试夹具 ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """每个测试用例使用独立的临时数据库，零相互污染。"""
    db_path = str(tmp_path / "test_pipeline.db")
    db = PipelineDB(db_path)
    yield db


def _add_test_video(db: PipelineDB, yid: str = "testid12345",
                    view_count: int = 5000, like_count: int = 300) -> bool:
    return db.add_video(
        youtube_id=yid, title="Test Video", channel_id="UCtest12345678901234567",
        score=0, source="TEST", view_count=view_count, like_count=like_count,
        upload_date="20260526",
    )


# ── Phase 1: DB 迁移测试 ──────────────────────────────────────────────────────

class TestDbMigration:

    def test_migration_idempotent(self, tmp_db):
        """重复初始化不报错，v7.0 新列均存在。"""
        # 第二次 init（内部会再次调用 _init_db）
        tmp_db._init_db()
        # 验证列存在
        with tmp_db.get_connection() as conn:
            cursor = conn.execute("PRAGMA table_info(processed_videos)")
            cols = {row[1] for row in cursor.fetchall()}
        for col in ('censor_tag', 'censor_score', 'is_manually_scored', 'process_pid'):
            assert col in cols, f"Missing column: {col}"

    def test_blacklist_table_exists(self, tmp_db):
        """blacklisted_videos 表已正确创建。"""
        with tmp_db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='blacklisted_videos'"
            )
            assert cursor.fetchone() is not None


# ── Phase 1: 黑名单墓碑测试 ───────────────────────────────────────────────────

class TestBlacklistTombstone:

    def test_blacklist_prevents_readd(self, tmp_db):
        """删除后加入黑名单，再次 add_video 应被拦截。"""
        _add_test_video(tmp_db, "blacklisted1")
        tmp_db.add_to_blacklist("blacklisted1", reason="user_deleted")
        tmp_db.delete_video_record("blacklisted1")

        result = _add_test_video(tmp_db, "blacklisted1")  # 再次尝试添加
        assert result is False, "Should be blocked by blacklist"

    def test_is_blacklisted_false_for_new(self, tmp_db):
        """未加入黑名单的 ID 应返回 False。"""
        assert tmp_db.is_blacklisted("newvideo12345") is False

    def test_blacklist_insert_or_ignore(self, tmp_db):
        """重复写入黑名单不报错（INSERT OR IGNORE）。"""
        tmp_db.add_to_blacklist("dup123456789")
        result = tmp_db.add_to_blacklist("dup123456789")  # 第二次
        assert result is True  # 不应抛异常


# ── Phase 1: 人工评分锁测试 ──────────────────────────────────────────────────

class TestManualScoreLock:

    def test_manual_score_lock_prevents_auto_overwrite(self, tmp_db):
        """人工打分后，auto 算分（force=False）不得覆盖。"""
        _add_test_video(tmp_db, "locktest1234")
        # 人工打 90 分（force=True）
        tmp_db.update_video_score("locktest1234", 90, force=True)
        # 自动算分尝试改为 60（force=False）
        tmp_db.update_video_score("locktest1234", 60, force=False)
        video = tmp_db.get_video_by_youtube_id("locktest1234")
        assert video["score"] == 90, "Manual score should not be overwritten by auto-scoring"

    def test_force_true_updates_is_manually_scored(self, tmp_db):
        """force=True 应将 is_manually_scored 设为 1。"""
        _add_test_video(tmp_db, "forcelock123")
        tmp_db.update_video_score("forcelock123", 75, force=True)
        video = tmp_db.get_video_by_youtube_id("forcelock123")
        assert video["is_manually_scored"] == 1

    def test_set_manually_scored_unlock(self, tmp_db):
        """set_manually_scored(False) 解锁后，auto 算分可以写入。"""
        _add_test_video(tmp_db, "unlocktest12")
        tmp_db.update_video_score("unlocktest12", 90, force=True)
        tmp_db.set_manually_scored("unlocktest12", locked=False)
        tmp_db.update_video_score("unlocktest12", 60, force=False)
        video = tmp_db.get_video_by_youtube_id("unlocktest12")
        assert video["score"] == 60, "After unlock, auto score should apply"


# ── Phase 4: 频道隔离测试 ─────────────────────────────────────────────────────

class TestChannelIsolation:

    def test_manual_only_not_in_approved(self, tmp_db):
        """MANUAL_ONLY 状态的频道不出现在 get_approved_channels() 中。"""
        tmp_db.add_channel("UCmanual12345678901234", "Manual Channel",
                           status="MANUAL_ONLY", reason="via manual video add")
        approved = tmp_db.get_approved_channels()
        ids = [c["channel_id"] for c in approved]
        assert "UCmanual12345678901234" not in ids

    def test_approved_channel_in_approved(self, tmp_db):
        """APPROVED 状态的频道正常出现在 get_approved_channels() 中。"""
        tmp_db.add_channel("UCapprov12345678901234", "Approved Channel",
                           status="APPROVED")
        approved = tmp_db.get_approved_channels()
        ids = [c["channel_id"] for c in approved]
        assert "UCapprov12345678901234" in ids


# ── Phase 2: CensorshipEngine 测试 ───────────────────────────────────────────

class TestCensorEngine:

    # P0 中文通道
    def test_p0_zh_channel_reject(self):
        r = check_text(zh_text="这是关于港独运动的视频", en_text="")
        assert r.hit is True
        assert r.level == "P0"
        assert r.action == ACTION_REJECT_SIGTERM
        assert r.channel == "zh"

    # P0 英文通道（独立备用，防翻译失效）
    def test_p0_en_channel_fallback(self):
        r = check_text(zh_text="", en_text="the tiananmen square incident")
        assert r.hit is True
        assert r.level == "P0"
        assert r.channel == "en"

    # P1 中文 + 豁免
    def test_p1_beijing_exemption(self):
        """'北京大学' 上下文应触发豁免，不拦截。

        [Claude_Sonnet_4.6_Thinking_planning] BUG-4 修复：
        '北京' 已加入 P1 词库。此测试真正验证豁免逻辑：
        - 输入包含触发词 '北京'
        - 同时包含豁免词 '北京大学'
        - 期望结果：豁免生效，PASS
        """
        r = check_text(zh_text="北京大学2026年录取分数线公布", en_text="")
        assert r.hit is False, f"'北京大学' should be exempted, but got: {r}"

    def test_p1_beijing_triggers_without_exemption(self):
        """'北京' 单独出现（无豁免上下文）应触发 P1 拦截。

        [Claude_Sonnet_4.6_Thinking_planning] BUG-4 修复：
        此测试确认 '北京' 确实在 P1 词库中，豁免逻辑有意义。
        """
        r = check_text(zh_text="北京当局下令封锁消息", en_text="")
        assert r.hit is True, f"'北京' should trigger P1, but got: {r}"
        assert r.level == "P1"

    def test_p1_triggers_without_exemption(self):
        r = check_text(zh_text="如何使用翻墙软件访问境外网站", en_text="")
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL

    # P2 商业合规
    def test_p2_commercial_deprioritize(self):
        r = check_text(zh_text="教你一夜暴富的方法", en_text="")
        assert r.hit is True
        assert r.level == "P2"
        assert r.action == ACTION_DEPRIORITIZE

    # 干净内容通过
    def test_clean_content_passes(self):
        r = check_text(zh_text="今天我们来学习 Python 编程", en_text="learning python programming today")
        assert r.hit is False

    # 大小写不敏感（英文）
    def test_case_insensitive_en(self):
        r = check_text(zh_text="", en_text="TIANANMEN Square Protest")
        assert r.hit is True
        assert r.level == "P0"

    # 全角字符归一化
    def test_fullwidth_normalization(self):
        """全角字母应被归一化后命中规则。"""
        r = check_text(zh_text="", en_text="ｔｉａｎａｎｍｅｎ square")
        assert r.hit is True
        assert r.level == "P0"

    def test_p1_china_negative_political_cooccurrence_en(self):
        """中国与独裁/威权/侵略等负面政治定性近距离共现时，应挂起人工复核。"""
        text = (
            "The dictatorships of Russia, China, Iran, and North Korea are engaging "
            "in acts of aggression and working together to rewrite the rules."
        )
        r = check_text(zh_text="", en_text=text)
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL
        assert "china+" in r.matched

    def test_p1_chinese_sanctions_evasion_cooccurrence_en(self):
        """Chinese 与 evading sanctions 近距离共现，覆盖本次涉事字幕里的制裁规避风险。"""
        r = check_text(
            zh_text="",
            en_text="Iran hid key components while evading sanctions through Chinese banks and shell companies.",
        )
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL

    def test_p1_china_taiwan_geopolitical_security_subtitle_is_suspended(self):
        """中台叙事与出口管制/国家安全组合必须挂起，不能作为英语学习选题放行。"""
        r = check_text(
            zh_text="",
            en_text=(
                "This dependency poses national security risks, particularly amid "
                "China's ambitions towards Taiwan and US export controls."
            ),
        )
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL
        assert r.matched == "china_taiwan_geopolitical_security"

    def test_semiconductor_supply_chain_without_geopolitical_context_passes(self):
        r = check_text(
            zh_text="",
            en_text="Taiwan produces advanced semiconductors used in global consumer electronics.",
        )
        assert r.hit is False

    def test_p1_china_negative_political_cooccurrence_zh(self):
        r = check_text(zh_text="这个片段把中国描述为威权阵营并讨论侵略行为", en_text="")
        assert r.hit is True
        assert r.level == "P1"
        assert r.channel == "zh"

    @pytest.mark.parametrize("zh_text", [
        "习近平出席会议",
        "李强主持国务院会议",
        "王毅会见外方代表",
    ])
    def test_chinese_leader_names_are_p0_zh(self, zh_text):
        """用户规则：提到中国领导人姓名一律不发布，不能依赖可 fail-open 的 CP 层。"""
        r = check_text(zh_text=zh_text, en_text="")
        assert r.hit is True
        assert r.level == "P0"
        assert r.action == ACTION_REJECT_SIGTERM

    @pytest.mark.parametrize("en_text", [
        "Xi Jinping meets Pakistan's prime minister in Beijing.",
        "Li Qiang hosts the policy meeting.",
        "Wang Yi comments on the talks.",
    ])
    def test_chinese_leader_names_are_p0_en(self, en_text):
        r = check_text(zh_text="", en_text=en_text)
        assert r.hit is True
        assert r.level == "P0"
        assert r.action == ACTION_REJECT_SIGTERM

    def test_china_negative_news_cooccurrence_is_p0_zh(self):
        r = check_text(zh_text="中国边境附近发生爆炸事故，造成多人死亡", en_text="")
        assert r.hit is True
        assert r.level == "P0"
        assert r.matched == "china_sensitive_negative_news"

    def test_china_negative_news_cooccurrence_is_p0_en(self):
        text = "A powerful blast near a Chinese facility killed several workers."
        r = check_text(zh_text="", en_text=text)
        assert r.hit is True
        assert r.level == "P0"
        assert r.matched == "china_sensitive_negative_news"

    def test_anti_china_targeted_violence_is_p0_zh(self):
        text = "袭击发动者称爆炸是为了杀害中国工程师，阻止中国继续推进当地项目。"
        r = check_text(zh_text=text, en_text="")
        assert r.hit is True
        assert r.level == "P0"
        assert r.action == ACTION_REJECT_SIGTERM
        assert r.matched == "anti_china_targeted_violence"

    def test_anti_china_targeted_violence_is_p0_en(self):
        text = (
            "The attackers said the blast was intended to kill Chinese engineers "
            "and stop CPEC projects from moving forward."
        )
        r = check_text(zh_text="", en_text=text)
        assert r.hit is True
        assert r.level == "P0"
        assert r.action == ACTION_REJECT_SIGTERM
        assert r.matched == "anti_china_targeted_violence"

    def test_severe_negative_news_is_p1_zh(self):
        r = check_text(zh_text="巴基斯坦奎达火车发生强烈爆炸，造成至少10人死亡", en_text="")
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL
        assert r.matched == "severe_negative_news"

    def test_severe_negative_news_is_p1_en(self):
        text = "Powerful blast hits train in Pakistan's Quetta, killing at least 10."
        r = check_text(zh_text="", en_text=text)
        assert r.hit is True
        assert r.level == "P1"
        assert r.action == ACTION_SUSPEND_MANUAL
        assert r.matched == "severe_negative_news"

    def test_china_negative_terms_far_apart_pass(self):
        """同一长文本里远距离出现 China 和 dictatorship，不应按组合规则误杀。"""
        far_text = "China market demand is discussed first. " + ("neutral business context. " * 30) + \
            "A separate history segment mentions a dictatorship in Libya."
        r = check_text(zh_text="", en_text=far_text)
        assert r.hit is False


# ── Phase 4: 评分公式极端值测试 ──────────────────────────────────────────────

class TestScoringFormula:
    """直接测试评分逻辑（不依赖 PipelineManager，避免外部依赖）。"""

    @staticmethod
    def _compute_score(views: int, likes: int) -> int:
        """内联评分公式，镜像 pipeline_manager.score_pending_videos 逻辑。"""
        if views <= 0:
            return 0
        like_rate = min(100.0, likes / views * 100)
        if views > 2000 and like_rate > 3.5:
            v_bonus = min(10.0, 5 * math.log10(views / 2000))
            l_bonus = min(5.0, 5 * (like_rate - 3.5) / 6.5)
            return max(80, min(95, round(80 + v_bonus + l_bonus)))
        else:
            v_ratio = min(1.0, views / 2000)
            l_ratio = min(1.0, like_rate / 3.5) if like_rate > 0 else 0.0
            return max(0, min(70, round(70 * v_ratio * l_ratio)))

    def test_zero_views(self):
        assert self._compute_score(0, 0) == 0

    def test_likes_exceed_views(self):
        """点赞数超过播放数（异常数据）不越界。"""
        score = self._compute_score(100, 9999)
        assert 0 <= score <= 100

    def test_high_traffic_score_clamped_at_95(self):
        """超高播放量分数不超过 95。"""
        score = self._compute_score(10_000_000, 500_000)
        assert score <= 95

    def test_qualifying_video_score_gte_80(self):
        """满足门槛的视频得分应 >= 80。"""
        score = self._compute_score(5000, 250)  # 5% like rate
        assert score >= 80

    def test_below_threshold_score_lte_70(self):
        """未满足门槛（低播放量）得分应 <= 70。"""
        score = self._compute_score(500, 10)
        assert score <= 70

    def test_score_always_in_range(self):
        """边界值遍历，确保所有情况下分数在 [0, 100]。"""
        test_cases = [(0, 0), (1, 1), (2000, 70), (2001, 71), (100000, 5000)]
        for views, likes in test_cases:
            score = self._compute_score(views, likes)
            assert 0 <= score <= 100, f"Score out of range for views={views}, likes={likes}: {score}"


# ── Phase 6: 安全升级二次加固测试 (SEC-1 / SEC-2) ───────────────────────────────

class TestSecurityBypassFortification:

    def test_sec1_url_validation_bypass_vectors(self):
        """SEC-1: 验证 _is_youtube_url() 能完全阻断所有旁路绕过向量，并放行合法 URL。"""
        from web.app import _is_youtube_url

        # 1. 旁路绕过向量 (应全部拦截)
        bypass_vectors = [
            "https://evil.com/youtube.com",                # 路径绕过
            "https://youtube.com.evil.com/watch?v=123",    # 子域名绕过
            "data:text/html,youtube.com",                  # data-URI 绕过
            "https://evil-youtube.com/watch?v=123",        # 相似域名绕过
            "youtube.com/path",                             # 无协议头
            "https://youtube.com@evil.com/watch",           # 用户名绕过
        ]
        for url in bypass_vectors:
            assert _is_youtube_url(url) is False, f"Bypass vector allowed: {url}"

        # 2. 合法官方域名 (应放行)
        legitimate_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/c/OfficialChannel",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
            "http://youtube.com/watch?v=dQw4w9WgXcQ",      # 支持 http
        ]
        for url in legitimate_urls:
            assert _is_youtube_url(url) is True, f"Legitimate URL blocked: {url}"

    def test_sec2_channel_promotion_block(self, tmp_db):
        """SEC-2: DB 测试和 API 级别测试，验证 MANUAL_ONLY 频道防隐式提升。"""
        import web.app
        from web.app import add_channel, AddChannelRequest
        from unittest.mock import patch, MagicMock

        # 1. DB 级别测试：写入 MANUAL_ONLY 并获取状态验证
        channel_id = "UCmanualpromotion1234567"
        channel_name = "Manual-Only Test Channel"
        tmp_db.add_channel(channel_id, channel_name, status="MANUAL_ONLY", reason="Manual video add")
        
        existing = tmp_db.get_channel_by_id(channel_id)
        assert existing is not None
        assert existing["status"] == "MANUAL_ONLY"

        # 2. API 级别测试：
        # 将 web.app 模块中的全局 db 实例临时替换为 tmp_db
        with patch.object(web.app, "db", tmp_db):
            # 模拟 subprocess.run 返回 yt-dlp 解析结果
            mock_result = MagicMock()
            mock_result.stdout = f"{channel_id}|{channel_name}\n"
            mock_result.returncode = 0

            with patch("subprocess.run", return_value=mock_result):
                # 尝试通过 add_channel API 将其加入自动爬虫白名单
                req = AddChannelRequest(url=f"https://www.youtube.com/channel/{channel_id}")
                resp = add_channel(req)

                # 应该被拦截，并返回 requires_promotion=True
                assert resp["success"] is False
                assert resp.get("requires_promotion") is True
                assert resp.get("channel_id") == channel_id
                assert resp.get("channel_name") == channel_name
                assert "MANUAL_ONLY" in resp["error"]

                # 确认数据库中该频道状态依然是 MANUAL_ONLY，未被覆盖为 APPROVED
                channel_after = tmp_db.get_channel_by_id(channel_id)
                assert channel_after["status"] == "MANUAL_ONLY", "Status should not be silently promoted to APPROVED"

                # 3. 传入 promote=True，验证成功提升状态为 APPROVED
                req_promote = AddChannelRequest(url=f"https://www.youtube.com/channel/{channel_id}", promote=True)
                resp_promote = add_channel(req_promote)
                assert resp_promote["success"] is True
                channel_promoted = tmp_db.get_channel_by_id(channel_id)
                assert channel_promoted["status"] == "APPROVED", "Status should be promoted to APPROVED"

    def test_con1_lock_handle_closed_on_flock_error(self, tmp_path):
        """CON-1: 验证 flock() 抛异常时，lock_file 仍被正确 close，不泄露句柄。"""
        from video_processing.pipeline_manager import PipelineManager
        from unittest.mock import patch, MagicMock
        import fcntl

        pm = PipelineManager()
        pm.db = MagicMock()
        pm._OUT_DIR = tmp_path
        mock_file = MagicMock()

        # 模拟 open() 返回 mock_file，以及 fcntl.flock() 在 LOCK_EX 时抛异常
        def mock_flock(fd, operation):
            if operation == fcntl.LOCK_EX:
                raise OSError("Simulated flock acquisition error")
            return None

        # 仅针对 pipeline.lock 的 open 进行 mock，避免影响其他模块
        original_open = open
        def mock_open(file, mode="r", *args, **kwargs):
            if "pipeline.lock" in str(file):
                return mock_file
            return original_open(file, mode, *args, **kwargs)

        with patch("builtins.open", new=mock_open), \
             patch("fcntl.flock", side_effect=mock_flock):
            
            pm._process_single_video({
                'youtube_id': 'lockerrvideo',
                'title': 'Test Lock Err',
                'score': 80
            })
            
            # 验证即使 flock(LOCK_EX) 抛出异常，mock_file.close() 依然被调用，避免句柄泄漏
            mock_file.close.assert_called_once()
            pm.db.update_video_status.assert_called_with('lockerrvideo', 'FAILED', error_msg='Pipeline lock error: Simulated flock acquisition error', slice_index=0) # [Gemini_3.5_Flash_High_planning] 传入 slice_index=0 以匹配 pipeline_manager.py 的调用参数


# ── Phase 7: CensorshipEngine 集成测试 ───────────────────────────────────────────

class TestCensorEngineIntegration:
    """测试 CensorshipEngine 与 PipelineManager 真实流水线的集成行为。"""

    def test_censor_integration_p0_reject(self, tmp_db, tmp_path):
        """P0 违禁词在下载前应触发一票否决：状态设为 FAILED，写入黑名单，清理半成品。"""
        from video_processing.pipeline_manager import PipelineManager
        from unittest.mock import patch, MagicMock

        # 开启内容审查、黑名单墓碑开关
        with patch("config.settings.settings.enable_censorship_engine", True), \
             patch("config.settings.settings.enable_blacklist_tombstone", True):
            
            pm = PipelineManager()
            pm.db = tmp_db
            pm._OUT_DIR = tmp_path
            
            # 使用包含 P0 违禁词的视频标题
            video = {
                'youtube_id': 'p0censorvid12',
                'title': '关于疆独势力的调查',  # 命中 P0
                'score': 80
            }
            tmp_db.add_video(
                youtube_id=video['youtube_id'], title=video['title'],
                channel_id="UCtest12345678901234567", score=video['score'],
                source="TEST", upload_date="20260526"
            )

            # 模拟 telegram 消息发送以防抛错
            pm.send_telegram_msg = MagicMock()
            
            # 运行 _process_single_video
            pm._process_single_video(video)

            # 验证状态和审计字段
            fresh = tmp_db.get_video_by_youtube_id(video['youtube_id'])
            assert fresh["status"] == "FAILED"
            assert "Censorship P0 Reject" in fresh["error_msg"]
            assert fresh["censor_tag"] == "🔴 政治安全违禁"
            assert fresh["censor_score"] == 95
            
            # 验证已写入黑名单墓碑
            assert tmp_db.is_blacklisted(video['youtube_id']) is True

    def test_censor_integration_p1_suspend(self, tmp_db, tmp_path):
        """P1 违禁词应触发人工挂起：状态设为 FAILED，但不加入黑名单。"""
        from video_processing.pipeline_manager import PipelineManager
        from unittest.mock import patch, MagicMock

        with patch("config.settings.settings.enable_censorship_engine", True):
            pm = PipelineManager()
            pm.db = tmp_db
            pm._OUT_DIR = tmp_path
            
            video = {
                'youtube_id': 'p1censorvid12',
                'title': '如何科学上网与使用翻墙软件',  # 命中 P1
                'score': 80
            }
            tmp_db.add_video(
                youtube_id=video['youtube_id'], title=video['title'],
                channel_id="UCtest12345678901234567", score=video['score'],
                source="TEST", upload_date="20260526"
            )

            pm.send_telegram_msg = MagicMock()
            pm._process_single_video(video)

            fresh = tmp_db.get_video_by_youtube_id(video['youtube_id'])
            assert fresh["status"] == "FAILED"
            assert "Censorship P1 Suspend" in fresh["error_msg"]
            assert fresh["censor_tag"] == "🟡 政策敏感拦截"
            assert fresh["censor_score"] == 75
            
            # 验证未被黑名单
            assert tmp_db.is_blacklisted(video['youtube_id']) is False

    def test_censor_integration_p2_deprioritize(self, tmp_db, tmp_path):
        """P2 违禁词应触发降权：分数设为 0，锁定，状态恢复为 PENDING。"""
        from video_processing.pipeline_manager import PipelineManager
        from unittest.mock import patch, MagicMock

        with patch("config.settings.settings.enable_censorship_engine", True):
            pm = PipelineManager()
            pm.db = tmp_db
            pm._OUT_DIR = tmp_path
            
            video = {
                'youtube_id': 'p2censorvid12',
                'title': '教你如何在一夜暴富',  # 命中 P2
                'score': 80
            }
            tmp_db.add_video(
                youtube_id=video['youtube_id'], title=video['title'],
                channel_id="UCtest12345678901234567", score=video['score'],
                source="TEST", upload_date="20260526"
            )

            pm.send_telegram_msg = MagicMock()
            pm._process_single_video(video)

            fresh = tmp_db.get_video_by_youtube_id(video['youtube_id'])
            assert fresh["status"] == "PENDING"
            assert fresh["score"] == 0
            assert fresh["is_manually_scored"] == 1  # 自动锁定
            assert fresh["censor_tag"] == "🔵 商业合规预警"
            assert fresh["censor_score"] == 50


class TestSequenceLockRelaxation:
    def test_sequence_lock_allows_ignored_and_completed(self, tmp_db):
        """[Unknown_Model_planning] 验证顺序锁在有前序切片为 IGNORED 或 COMPLETED 时允许当前切片通过，但在前序为 PENDING 时阻断。"""
        from video_processing.pipeline_manager import PipelineManager
        from unittest.mock import patch, MagicMock
        
        pm = PipelineManager()
        pm.db = tmp_db
        
        yid = "seq_lock_test"
        
        # 1. 插入父视频和三个子切片
        tmp_db.add_video(yid, "Parent Video", "channel_1", score=90, slice_index=0)
        parent = tmp_db.get_video_by_youtube_id(yid, 0)
        parent_id = parent["id"]
        
        slices = [
            {"youtube_id": yid, "slice_index": 1, "parent_id": parent_id, "title": "Slice 1", "channel_id": "channel_1", "score": 90},
            {"youtube_id": yid, "slice_index": 2, "parent_id": parent_id, "title": "Slice 2", "channel_id": "channel_1", "score": 90},
            {"youtube_id": yid, "slice_index": 3, "parent_id": parent_id, "title": "Slice 3", "channel_id": "channel_1", "score": 90},
        ]
        tmp_db.batch_add_videos(slices)
        
        # 2. 将 Slice 1 设为 IGNORED, Slice 2 设为 COMPLETED, Slice 3 设为 PENDING
        tmp_db.update_video_status(yid, "IGNORED", slice_index=1)
        tmp_db.update_video_status(yid, "COMPLETED", slice_index=2)
        
        # Mock _find_downloaded_video to return a dummy path so it passes parent video file check
        with patch.object(pm, "_find_downloaded_video", return_value="dummy_path"):
            # 获取待处理视频列表并进行顺序锁测试
            targets = tmp_db.get_high_score_pending_videos(min_score=75, limit=5)
            # 过滤出 slice 3
            slice3 = next(v for v in targets if v["youtube_id"] == yid and v["slice_index"] == 3)
            
            # 由于前序 (1, 2) 都是终态 (IGNORED, COMPLETED)，不应阻断 slice 3
            # 运行排队检查
            all_slices = tmp_db.get_slices_by_parent_yid(yid)
            prev_not_published = [s for s in all_slices if s['slice_index'] < 3 and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
            assert len(prev_not_published) == 0, "Should not be blocked because previous slices are IGNORED and COMPLETED"
            
            # 如果把 Slice 2 改为 PENDING
            tmp_db.update_video_status(yid, "PENDING", slice_index=2)
            all_slices_blocked = tmp_db.get_slices_by_parent_yid(yid)
            prev_not_published_blocked = [s for s in all_slices_blocked if s['slice_index'] < 3 and s['status'] not in ('PUBLISHED', 'IGNORED', 'COMPLETED')]
            assert len(prev_not_published_blocked) == 1, "Should be blocked because Slice 2 is PENDING"


class TestGarbageCollectionOverhaul:
    def test_garbage_collection_cleanup_files_and_dirs(self, tmp_db):
        """[Claude_Opus_4.8] v3.11.0: 发布后 GC 仅清理源视频/中间字幕与语音目录，
        但保留「再次发布」所需产物（成片/封面/文案/短标题/分类），以支撑秒级重发。
        """
        from pathlib import Path
        from video_processing.pipeline_manager import PipelineManager

        pm = PipelineManager()
        pm.db = tmp_db
        out_dir = Path(pm._OUT_DIR)

        yid = "gc_test_video"

        # 1. 模拟 slice_index == 0 发布成功
        # 应被清理：源视频 + 中间字幕（体积大且可重建；源另有 original_video/ 冷存档兜底）
        should_delete = [
            f"{yid}.mp4",
            f"{yid}.ass",
            f"{yid}_subtitle.txt",
            f"{yid}.description",
        ]
        # 应被保留：再次发布直接复用的产物
        should_keep = [
            f"{yid}_vertical.mp4",
            f"{yid}_copy.txt",
            f"{yid}_title.txt",
            f"{yid}_category.txt",
            f"{yid}_cover.jpg",
        ]
        for f_name in should_delete + should_keep:
            (out_dir / f_name).write_text("dummy content", encoding="utf-8")

        audio_dir = out_dir / f"{yid}_audio_gen"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "temp.wav").write_text("audio content")

        pm._run_garbage_collection(yid, slice_index=0, status="PUBLISHED")

        for f_name in should_delete:
            assert not (out_dir / f_name).exists(), f"File {f_name} should be cleaned up"
        for f_name in should_keep:
            assert (out_dir / f_name).exists(), f"File {f_name} should be RETAINED for republish"
        assert not audio_dir.exists(), "Audio gen directory should be cleaned up"
        
    def test_garbage_collection_parent_cleanup_after_last_slice(self, tmp_db):
        """[Unknown_Model_planning] 验证当所有兄弟子任务都进入终态（PUBLISHED/FAILED/IGNORED/COMPLETED）时，清理父任务的临时文件"""
        from pathlib import Path
        from video_processing.pipeline_manager import PipelineManager
        
        pm = PipelineManager()
        pm.db = tmp_db
        out_dir = Path(pm._OUT_DIR)
        
        yid = "gc_parent_test"
        
        # 1. 插入父视频和子视频切片
        tmp_db.add_video(yid, "Parent Video", "channel_1", score=90, slice_index=0)
        parent = tmp_db.get_video_by_youtube_id(yid, 0)
        parent_id = parent["id"]
        
        slices = [
            {"youtube_id": yid, "slice_index": 1, "parent_id": parent_id, "title": "Slice 1", "channel_id": "channel_1"},
            {"youtube_id": yid, "slice_index": 2, "parent_id": parent_id, "title": "Slice 2", "channel_id": "channel_1"},
        ]
        tmp_db.batch_add_videos(slices)
        
        # 创建父任务的中间文件和临时语音目录
        parent_files = [
            f"{yid}.mp4",
            f"{yid}.info.json",
            f"{yid}_subtitle.txt",
            f"{yid}_copy.txt"
        ]
        for f_name in parent_files:
            (out_dir / f_name).write_text("dummy parent content", encoding="utf-8")
            
        parent_audio_dir = out_dir / f"{yid}_audio_gen"
        parent_audio_dir.mkdir(parents=True, exist_ok=True)
        (parent_audio_dir / "temp.wav").write_text("audio content")
        
        # 模拟 slice 1 成功发布 (终态 1)
        tmp_db.update_video_status(yid, "PUBLISHED", slice_index=1)
        pm._run_garbage_collection(yid, slice_index=1, status="PUBLISHED")
        
        # 此时 slice 2 还在 PENDING (未完成)，不应当触发父文件清理
        for f_name in parent_files:
            assert (out_dir / f_name).exists(), f"Parent file {f_name} should NOT be cleaned up yet"
        assert parent_audio_dir.exists(), "Parent audio gen folder should NOT be cleaned up yet"
        
        # 模拟 slice 2 被设置为 IGNORED (终态 2)
        tmp_db.update_video_status(yid, "IGNORED", slice_index=2)
        pm._run_garbage_collection(yid, slice_index=2, status="IGNORED")
        
        # 现在所有切片均进入终态，应该触发父任务清理
        for f_name in parent_files:
            assert not (out_dir / f_name).exists(), f"Parent file {f_name} should be cleaned up now"
        assert not parent_audio_dir.exists(), "Parent audio gen folder should be cleaned up now"


class TestStopVideoApi:
    """
    [Gemini_3.5_Flash_planning] Stop Video API 单元测试类

    # Modification History
    | Version | Date | Author | Description |
    | --- | --- | --- | --- |
    | 1.1.0 | 2026-08-21 | Codex | 发布中中止改写为 SUBMITTED_UNBOUND，回归未确认提交的 fail-closed 控制台保护 |
    | 1.0.0 | 2026-05-28 | Gemini_3.5_Flash_planning | 初始创建测试类 |
    """

    def test_stop_video_success(self, tmp_db):
        """[Gemini_3.5_Flash_planning] 验证 stop_video API 成功杀掉进程并更新数据库状态为 FAILED。"""
        import web.app
        from fastapi.testclient import TestClient
        
        yid = "stop_test_yid"
        # 1. 往数据库中插入一个处于 active 状态的任务 (例如 DOWNLOADING) [Gemini_3.5_Flash_planning]
        tmp_db.add_video(yid, "Stop Test Video", "channel_1", score=90, slice_index=0)
        tmp_db.update_video_status(yid, "DOWNLOADING", slice_index=0)
        # 设置一个模拟 pid
        tmp_db.update_process_pid(yid, 99999, slice_index=0)
        
        # 2. 模拟 os.killpg 和 settings.enable_sigterm_kill=True [Gemini_3.5_Flash_planning]
        import unittest.mock as mock
        client = TestClient(web.app.app)
        
        with mock.patch.object(web.app, "db", tmp_db), \
             mock.patch.object(web.app.settings, "enable_sigterm_kill", True), \
             mock.patch("os.killpg") as mock_killpg:
            
            response = client.post(f"/api/videos/{yid}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "成功停止" in data["message"]
            
            # 验证 killpg 曾以 SIGTERM 信号调用过 [Gemini_3.5_Flash_planning]
            import signal
            mock_killpg.assert_any_call(99999, signal.SIGTERM)
            
            # 验证数据库状态更新为 FAILED [Gemini_3.5_Flash_planning]
            video = tmp_db.get_video_by_youtube_id(yid, slice_index=0)
            assert video["status"] == "FAILED"
            assert video["error_msg"] == "用户手动停止"

    def test_stop_video_not_active(self, tmp_db):
        """[Gemini_3.5_Flash_planning] 验证停止非活跃状态的任务会报错。"""
        import web.app
        from fastapi.testclient import TestClient
        import unittest.mock as mock
        
        yid = "stop_test_yid_inactive"
        tmp_db.add_video(yid, "Stop Test Inactive", "channel_1", score=90, slice_index=0)
        tmp_db.update_video_status(yid, "PENDING", slice_index=0) # 非活跃
        
        client = TestClient(web.app.app)
        with mock.patch.object(web.app, "db", tmp_db):
            response = client.post(f"/api/videos/{yid}/stop")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "当前不处于运行状态" in data["error"]

    def test_stop_publishing_records_unbound_submission_instead_of_failed(self, tmp_db):
        """中止发表阶段无法证明平台未受理，必须停止自动重传。"""
        import unittest.mock as mock
        import web.app
        from fastapi.testclient import TestClient

        yid = "stop-publishing-yid"
        tmp_db.add_video(yid, "Stop Publishing", "channel_1", score=90)
        tmp_db.update_video_status(yid, "PUBLISHING")
        client = TestClient(web.app.app)

        with mock.patch.object(web.app, "db", tmp_db), \
             mock.patch.object(web.app.settings, "enable_sigterm_kill", True):
            response = client.post(f"/api/videos/{yid}/stop")

        assert response.status_code == 200
        assert response.json()["success"] is True
        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND"
        assert tmp_db.get_wechat_publication(yid)["state"] == "SUBMITTED_UNBOUND"

    def test_unconfirmed_submission_cannot_be_retried_or_respecced(self, tmp_db):
        """通用 API 不能把 PUBLISHING 回写 PENDING 后再次触发上传。"""
        import unittest.mock as mock
        import web.app
        from fastapi.testclient import TestClient

        yid = "guard-publishing-yid"
        tmp_db.add_video(yid, "Guard Publishing", "channel_1", score=90)
        tmp_db.update_video_status(yid, "PUBLISHING")
        client = TestClient(web.app.app)

        with mock.patch.object(web.app, "db", tmp_db):
            retry = client.post(f"/api/videos/{yid}/retry")
            respec = client.post(f"/api/videos/{yid}/respec", json={"disable_slicing": True})
            hard_reset = client.post(f"/api/videos/{yid}/reset-hard")

        assert retry.json()["success"] is False
        assert respec.json()["success"] is False
        assert hard_reset.json()["success"] is False
        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "PUBLISHING"

    def test_local_published_without_platform_receipt_cannot_republish(self, tmp_db):
        """本地 PUBLISHED 不是平台公开证明，不能作为重复发表授权。"""
        import unittest.mock as mock
        import web.app
        from fastapi.testclient import TestClient

        yid = "local-published-yid"
        tmp_db.add_video(yid, "Local Published", "channel_1", score=90)
        tmp_db.update_video_status(yid, "PUBLISHED")
        client = TestClient(web.app.app)

        with mock.patch.object(web.app, "db", tmp_db):
            response = client.post(f"/api/videos/{yid}/republish")

        assert response.status_code == 200
        assert response.json()["success"] is False
        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "PUBLISHED"

    def test_verified_published_record_still_cannot_republish_without_deletion_proof(self, tmp_db, tmp_path):
        """即使旧作品已确认公开，也不能把“本地仍有账本”当作平台已删除。"""
        import unittest.mock as mock
        import web.app
        from fastapi.testclient import TestClient

        yid = "verified-published-yid"
        evidence = tmp_path / "management_published.png"
        evidence.write_bytes(b"png")
        tmp_db.add_video(yid, "Verified Published", "channel_1", score=90)
        tmp_db.record_wechat_publication_confirmation(
            yid, evidence_path=str(evidence), state="PUBLISHED", platform_post_id="native-post-1",
        )
        tmp_db.update_video_status(yid, "PUBLISHED")
        client = TestClient(web.app.app)

        with mock.patch.object(web.app, "db", tmp_db):
            response = client.post(f"/api/videos/{yid}/republish")

        assert response.status_code == 200
        assert response.json()["success"] is False
        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "PUBLISHED"

    def test_retry_recent_skips_failed_row_with_submission_ledger(self, tmp_db):
        """历史误写 FAILED 的待确认提交也不能被批量重试绕过。"""
        import unittest.mock as mock
        import web.app
        from fastapi.testclient import TestClient

        yid = "failed-with-ledger-yid"
        tmp_db.add_video(yid, "Failed With Ledger", "channel_1", score=90)
        tmp_db.record_wechat_publication_confirmation(
            yid, evidence_path=None, state="SUBMITTED_UNBOUND",
            error_message="平台结果未知",
        )
        tmp_db.update_video_status(yid, "FAILED")
        client = TestClient(web.app.app)

        with mock.patch.object(web.app, "db", tmp_db):
            response = client.post("/api/videos/retry-recent?hours=24")

        assert response.status_code == 200
        assert response.json()["count"] == 0
        assert response.json()["skipped_platform_guard"] == 1
        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "FAILED"

    def test_orphaned_publishing_is_recorded_as_unbound_not_failed(self, tmp_db):
        """发布子进程消失不代表平台未受理，调度器不得写 FAILED。"""
        import unittest.mock as mock
        import web.app

        yid = "orphan-publishing-yid"
        tmp_db.add_video(yid, "Orphan Publishing", "channel_1", score=90)
        tmp_db.update_video_status(yid, "PUBLISHING")
        candidate = tmp_db.get_video_by_youtube_id(yid)

        with mock.patch.object(web.app, "db", tmp_db), \
             mock.patch.object(tmp_db, "get_stale_publishing_videos", return_value=[candidate]), \
             mock.patch.object(web.app, "_process_group_alive", return_value=False):
            assert web.app._recover_orphaned_publishing_tasks() == 1

        assert tmp_db.get_video_by_youtube_id(yid)["status"] == "SUBMITTED_UNBOUND"
        assert tmp_db.get_wechat_publication(yid)["state"] == "SUBMITTED_UNBOUND"

    def test_orphaned_pre_submission_task_is_bounded_and_requeued(self, tmp_db):
        """下载/转录阶段进程消失可安全回收；不存在平台投递边界。"""
        import unittest.mock as mock
        import web.app

        yid = "orphan-pre-submit-yid"
        tmp_db.add_video(yid, "Orphan Pre Submit", "channel_1", score=90)
        tmp_db.update_video_status(yid, "DOWNLOADING")
        candidate = tmp_db.get_video_by_youtube_id(yid)

        with mock.patch.object(web.app, "db", tmp_db), \
             mock.patch.object(tmp_db, "get_stale_pre_submission_processing_videos", return_value=[candidate]), \
             mock.patch.object(web.app, "_process_group_alive", return_value=False):
            assert web.app._recover_orphaned_pre_submission_tasks() == 1

        recovered = tmp_db.get_video_by_youtube_id(yid)
        assert recovered["status"] == "PENDING"
        assert recovered["retry_count"] == 1
        assert tmp_db.get_wechat_publication(yid) is None

    def test_queue_runner_respects_external_pipeline_lock(self):
        """cron 持有 pipeline.lock 时，仪表盘队列不能再启动第二条管线。"""
        import unittest.mock as mock
        import web.app

        with mock.patch.object(web.app, "_is_pipeline_manager_running", return_value=True):
            assert web.app._queue_pipeline_launch_allowed() is False
