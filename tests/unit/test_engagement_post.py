"""互动建议与视频号回执回归。

# Modification History
| Version | Date | Author | Description |
|---------|------|--------|-------------|
| 1.0.0 | 2026-09-07 | Codex | 覆盖选择题、转义、缺失降级与公开状态单条通知。 |
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from video_processing.utils.engagement_post import normalize_engagement_post, engagement_receipt_section

POST = """视频讨论消费品牌客流下降后，如何区分短期需求波动和长期吸引力变化。单次业绩不能回答所有问题，持续观察消费者的选择更有意义。
你更倾向于哪种解释？
A. 短期消费需求波动
B. 产品创新暂时放缓
C. 品牌吸引力持续下降
D. 证据还不足，需要继续观察
什么数据出现，才会让你确认或改变自己的判断？"""


def test_post_and_html_receipt(tmp_path):
    post = POST.replace('短期需求波动', '<需求> & 波动')
    path = tmp_path / 'engagement.txt'
    path.write_text(post)
    assert normalize_engagement_post(post) == post
    receipt = engagement_receipt_section(path)
    assert '&lt;需求&gt; &amp; 波动' in receipt
    assert '未自动发布' in receipt
    assert len(receipt) < 4096


@pytest.mark.parametrize('post', ['', None, 'A. 简单投票', POST.replace('D.', 'C.'), POST.split('什么数据')[0], POST * 10])
def test_invalid_suggestions_are_not_presented(post):
    assert normalize_engagement_post(post) == ''


def test_missing_and_corrupt_artifacts_do_not_break_receipt(tmp_path):
    path = tmp_path / 'missing.txt'
    assert '待补充' in engagement_receipt_section(path)
    path.write_bytes(b'\xff')
    assert '待补充' in engagement_receipt_section(path)


@pytest.mark.parametrize('code, expected', [(0, 1), (6, 0), (8, 0), (3, 0)])
def test_only_confirmed_publication_sends_one_combined_receipt(tmp_path, monkeypatch, code, expected):
    from video_processing.pipeline_manager import PipelineManager, settings
    monkeypatch.setattr(settings, 'wechat_review_max_per_run', 1)
    manager = PipelineManager.__new__(PipelineManager)
    manager._OUT_DIR = tmp_path
    manager.db = Mock()
    manager.db.get_wechat_publications_by_states.return_value = [dict(
        id=7, youtube_id='video123', slice_index=2, platform_post_id='native123',
    )]
    manager._run_tracked = Mock(return_value=SimpleNamespace(returncode=code))
    manager.send_telegram_msg = Mock()
    evidence_dir = tmp_path / 'wechat_evidence/video123_s2/reconcile_7'
    evidence_dir.mkdir(parents=True)
    for name in ('published', 'under_review', 'rejected'):
        (evidence_dir / f'management_{name}.png').write_bytes(b'evidence')
    (tmp_path / 'video123_s2_engagement.txt').write_text(POST)
    (tmp_path / 'video123_engagement.txt').write_text('wrong parent')
    manager.reconcile_wechat_under_review()
    assert manager.send_telegram_msg.call_count == expected
    if expected:
        text = manager.send_telegram_msg.call_args.args[0]
        assert POST in text
        assert 'YouTube ID: video123_s2' in text
        assert 'wrong parent' not in text
    assert '--verify-only' in manager._run_tracked.call_args.args[0]
    assert '--publish' not in manager._run_tracked.call_args.args[0]


def test_copywriter_preserves_generated_suggestion_and_prompt():
    from scripts.copywriter import WeChatContentSchema, _build_gemini_base_content, _build_wechat_prompt
    parsed = WeChatContentSchema(
        short_title='消费品牌客流下降', display_title='消费品牌客流变化如何解读',
        hook_subtitle='如何判断品牌吸引力', wechat_copy='视频讨论消费品牌客流下降的不同原因。',
        category='财经', content_hints=['market'], content_label='', engagement_post=POST,
    )
    result = _build_gemini_base_content(parsed, '消费品牌客流下降', '视频讨论消费品牌客流下降的不同原因。')
    assert result['engagement_post'] == POST
    prompt = _build_wechat_prompt('品牌', '来源内容')
    assert 'engagement_post' in prompt
    assert '不编造数字' in prompt
    assert '来源内容' in prompt
