"""编辑版式的安全边界、全部文本、评论邀请与媒体入口验证。"""
import copy
from pathlib import Path

import pysubs2
import pytest
from PIL import Image

from video_processing.core.insight_script import InsightScriptV2
from video_processing.processors import insight_editorial as e
from video_processing.utils.insight_v2_prompt import FEW_SHOT_EXAMPLE_CORNELL


def plan():
    return InsightScriptV2.model_validate(copy.deepcopy(FEW_SHOT_EXAMPLE_CORNELL))


def test_cta_is_shared_by_voice_and_review():
    script = plan()
    assert script.outro.comment_invitation in script.review_text()
    assert script.outro.comment_invitation in script.outro.tts_narration
    assert script.outro.tts_narration.count(script.outro.comment_invitation) == 1


def test_six_points_and_subtitles_stay_outside_picture(tmp_path):
    source = tmp_path / "source.ass"
    source.write_text("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                      "Dialogue: 0,0:00:01.00,0:00:08.00,Default,,0,0,0,,cannot redeem the entire amount\\N无法赎回全部本金。\n")
    output = tmp_path / "body.ass"
    script = plan()
    timeline = e.write_body_subtitles(output, source, script, 180)
    assert len(timeline) == 6
    assert [p['keyword'] for p in timeline] == [p.keyword for c in script.cards for p in c.points]
    assert [(p['start'],p['end']) for p in timeline][0][0] == script.cards[0].start_sec
    assert timeline[-1]['end'] == script.cards[-1].end_sec
    rendered = pysubs2.load(str(output))
    assert 'cannot redeem the entire amount' in '\n'.join(s.plaintext for s in rendered)
    for event in rendered:
        import re
        y = int(re.search(r'\\pos\(\d+,(\d+)\)',event.text).group(1))
        assert e.VIDEO_Y + e.VIDEO_H < y < 1765


def test_slice_never_uses_parent_original(tmp_path):
    (tmp_path / "video.mp4").touch()
    (tmp_path / "video.ass").touch()
    with pytest.raises(ValueError, match="对应原片"):
        e.resolve_inputs(tmp_path / "video_s1_vertical.mp4")


def test_subtitle_without_both_languages_or_out_of_range_rejected(tmp_path):
    source = tmp_path / "source.ass"
    source.write_text("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                      "Dialogue: 0,0:00:01.00,0:00:08.00,Default,,0,0,0,,only English\n")
    with pytest.raises(ValueError, match="双语"):
        e.bilingual_events(source,180)
    source.write_text(source.read_text().replace('only English','English\\N中文'))
    with pytest.raises(ValueError, match="时码"):
        e.bilingual_events(source,2)


def test_long_outro_preserves_all_options_and_brand_code(tmp_path):
    script = plan()
    script.outro.reflection_question = '这个问题值得我们深入思考你会如何做出自己的判断和最终选择呢？'
    script.outro.poll_options = ['优先考虑长期收益并且保持耐心', '更加重视现金流动性与安全性', '两者之间寻求更加稳妥的平衡']
    path = tmp_path / 'outro.png'
    e.render_outro(path,script.outro)
    image = Image.open(path)
    assert image.size == (1080,1920)
    assert image.getpixel((76,1540)) == (255,255,255)
    # 静区内品牌码像素来自受控原资产，非合成占位图。
    expected = e.ImageOps.contain(Image.open(e.QR).convert('RGB'),(228,228))
    x,y = 76+(260-expected.width)//2,1540+(260-expected.height)//2
    assert image.crop((x,y,x+expected.width,y+expected.height)).tobytes() == expected.tobytes()


def test_long_intro_has_no_clipped_title(tmp_path):
    photo = tmp_path / "photo.png"
    Image.new("RGB", (1280,720), (45,60,75)).save(photo)
    e.render_intro(tmp_path / "intro.png", "当流动性需求遇到长期资产锁定我们应如何作出理性选择", photo)
    assert (tmp_path / "intro.png").is_file()


def test_number_percent_and_short_last_line_remain_readable():
    text = "非上市商业开发公司季度流动性上限仅为净资产5%"
    lines = e.wrap(text, 42, 912)
    assert "".join(lines) == text
    assert any("5%" in line for line in lines)
    assert len(lines[-1]) >= 5


def test_chinese_punctuation_does_not_start_line():
    lines = e.wrap("违约会迫使资产进行公开减记，这将降低报告的资产净值。", 46, 912)
    assert not any(line.startswith(("，", "。")) for line in lines)
