"""真实标题片长句必须保留完整英文并落在安全宽度内。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-11-01 | Codex | 回归7146长句实际字体宽度越界，验证既有安全边界保持。 |
"""
from pathlib import Path

from video_processing.processors.approved_caption_layout import approved_layout
from video_processing.processors.reviewed_caption_sources import SOURCES
from video_processing.processors.source_caption_fallback import caption_width
from video_processing.utils.subtitle_stylist import SubtitleLayout, SubtitleStylist


def test_reviewed_title_long_sentence_fits_actual_font_width():
    name = 'RYYM-6C4Vs4'
    framed = approved_layout(Path(name + '.mp4'), SOURCES[name]['source_sha256'])
    layout = SubtitleLayout(en_size=int(framed.font_size * .71),
        zh_size=int(framed.font_size * .81), safe_width=framed.wrap_width,
        max_height=framed.subtitle_bottom-framed.subtitle_top, outline=3.5)
    layout.spacer_px = 30
    rendered = SubtitleStylist(layout).render(
        en_text='I mean, when my mom was growing up in the oppressive olden days,',
        zh_text='我是说，当我妈妈在那个压抑的旧时代长大时，',
        vocab_items={'oppressive': '压抑的'}, bilingual=True)
    assert caption_width(rendered, 3.5) <= framed.subtitle_width
    assert 'oppressive' in rendered.ass_text
    assert framed.geometry(360, 640).video_y + framed.height < framed.subtitle_top
