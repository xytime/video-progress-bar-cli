"""Curated multi-page lyrics and study notes layout for David Kushner - Daylight.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Full 6-page bilingual journal layout, word timestamps, and study cards for Daylight |
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from PIL import Image, ImageDraw

from .canvas_builder import CanvasBuilder, is_cjk
from .contracts import LyricLine, LyricWord


def get_daylight_pages_data() -> List[Dict[str, Any]]:
    """Returns the 6 curated movements of David Kushner - Daylight with word timestamps."""
    return [
        # =====================================================================
        # Page 1: 【第一幕 · 罪与挣扎】Verse 1 (Lines 1~6, 0.0s - 31.5s)
        # =====================================================================
        {
            "page_idx": 1,
            "chapter_title": "【第一幕 · 罪与挣扎】 Verse 1 渊薮自省",
            "time_range": (0.0, 31.5),
            "is_cover_page": True,
            "lyrics": [
                {
                    "en": "Telling myself I won't go there",
                    "zh": "告诫自己不可深陷其中",
                    "words": [
                        {"word": "Telling", "start": 2.392, "end": 3.549},
                        {"word": "myself", "start": 3.549, "end": 4.540},
                        {"word": "I", "start": 4.540, "end": 4.705},
                        {"word": "won't", "start": 4.705, "end": 5.531},
                        {"word": "go", "start": 5.531, "end": 5.862},
                        {"word": "there", "start": 5.862, "end": 6.688},
                    ],
                },
                {
                    "en": "Oh, but I know that I won't care",
                    "zh": "噢，但我深知自己难以自拔",
                    "words": [
                        {"word": "Oh,", "start": 6.771, "end": 7.028},
                        {"word": "but", "start": 7.028, "end": 7.414},
                        {"word": "I", "start": 7.414, "end": 7.543},
                        {"word": "know", "start": 7.543, "end": 8.057},
                        {"word": "that", "start": 8.057, "end": 8.572},
                        {"word": "I", "start": 8.572, "end": 8.700},
                        {"word": "won't", "start": 8.700, "end": 9.343},
                        {"word": "care", "start": 9.343, "end": 9.858},
                    ],
                },
                {
                    "en": "Tryna wash away all the blood I've spilt",
                    "zh": "试图洗净双手沾染的罪愆与伤痛",
                    "words": [
                        {"word": "Tryna", "start": 9.941, "end": 10.677},
                        {"word": "wash", "start": 10.677, "end": 11.168},
                        {"word": "away", "start": 11.168, "end": 11.658},
                        {"word": "all", "start": 11.658, "end": 12.026},
                        {"word": "the", "start": 12.026, "end": 12.395},
                        {"word": "blood", "start": 12.395, "end": 13.008},
                        {"word": "I've", "start": 13.008, "end": 13.499},
                        {"word": "spilt", "start": 13.499, "end": 14.112},
                    ],
                },
                {
                    "en": "This lust is a burden that we both share",
                    "zh": "这种欲望是我们共同背负的沉沦与枷锁",
                    "words": [
                        {"word": "This", "start": 17.449, "end": 18.062},
                        {"word": "lust", "start": 18.062, "end": 18.675},
                        {"word": "is", "start": 18.675, "end": 19.135},
                        {"word": "a", "start": 19.135, "end": 19.442},
                        {"word": "burden", "start": 19.442, "end": 20.055},
                        {"word": "that", "start": 20.055, "end": 20.362},
                        {"word": "we", "start": 20.362, "end": 20.669},
                        {"word": "both", "start": 20.669, "end": 20.976},
                        {"word": "share", "start": 20.976, "end": 21.119},
                    ],
                },
                {
                    "en": "Two sinners can't atone from a lone prayer",
                    "zh": "两个罪人岂能凭一人的祈祷救赎",
                    "words": [
                        {"word": "Two", "start": 21.202, "end": 21.682},
                        {"word": "sinners", "start": 21.682, "end": 22.322},
                        {"word": "can't", "start": 22.322, "end": 22.962},
                        {"word": "atone", "start": 22.962, "end": 23.602},
                        {"word": "from", "start": 23.602, "end": 24.082},
                        {"word": "a", "start": 24.082, "end": 24.242},
                        {"word": "lone", "start": 24.242, "end": 24.562},
                        {"word": "prayer", "start": 24.562, "end": 25.040},
                    ],
                },
                {
                    "en": "Souls tied, intertwined by our pride and guilt",
                    "zh": "灵魂被傲慢与愧疚深深纠缠交织",
                    "words": [
                        {"word": "Souls", "start": 25.123, "end": 25.568},
                        {"word": "tied,", "start": 25.568, "end": 26.013},
                        {"word": "intertwined", "start": 26.013, "end": 27.126},
                        {"word": "by", "start": 27.126, "end": 27.422},
                        {"word": "our", "start": 27.422, "end": 27.719},
                        {"word": "pride", "start": 27.719, "end": 28.164},
                        {"word": "and", "start": 28.164, "end": 28.461},
                        {"word": "guilt", "start": 28.461, "end": 28.960},
                    ],
                },
            ],
            "study_notes": [
                "• atone /əˈtəʊn/：v. 弥补，赎罪（源自 at-one，表化解罪孽与神圣和解）",
                "• intertwine /ˌɪntəˈtwaɪn/：v. 缠绕，交织纠葛（喻情感与宿命难分难舍）",
                "• lone prayer：孤单无依的祈祷（强调个体在面对宏大宿命时的无力感）",
                "• lust is a burden：欲望是一种沉重的负担（深刻的人性自省表达）",
            ],
        },

        # =====================================================================
        # Page 2: 【第二幕 · 暗影初临】Pre-Chorus 1 + Chorus 1 (Lines 7~12, 31.5s - 58.5s)
        # =====================================================================
        {
            "page_idx": 2,
            "chapter_title": "【第二幕 · 暗影初临】 Pre-Chorus & Chorus 宿命爱恨",
            "time_range": (31.5, 58.5),
            "is_cover_page": False,
            "lyrics": [
                {
                    "en": "There's darkness in the distance",
                    "zh": "极目远方，尽是无边暗影",
                    "words": [
                        {"word": "There's", "start": 33.631, "end": 34.350},
                        {"word": "darkness", "start": 34.350, "end": 35.320},
                        {"word": "in", "start": 35.320, "end": 35.610},
                        {"word": "the", "start": 35.610, "end": 35.900},
                        {"word": "distance", "start": 35.900, "end": 36.801},
                    ],
                },
                {
                    "en": "From the way that I've been living",
                    "zh": "映照着我沉沦放逐的过往生活",
                    "words": [
                        {"word": "From", "start": 36.885, "end": 37.380},
                        {"word": "the", "start": 37.380, "end": 37.750},
                        {"word": "way", "start": 37.750, "end": 38.300},
                        {"word": "that", "start": 38.300, "end": 38.800},
                        {"word": "I've", "start": 38.800, "end": 39.300},
                        {"word": "been", "start": 39.300, "end": 39.750},
                        {"word": "living", "start": 39.750, "end": 40.430},
                    ],
                },
                {
                    "en": "But I know I can't resist it",
                    "zh": "但我深知自己无力抵抗这股引力",
                    "words": [
                        {"word": "But", "start": 40.513, "end": 41.200},
                        {"word": "I", "start": 41.200, "end": 41.600},
                        {"word": "know", "start": 41.600, "end": 42.400},
                        {"word": "I", "start": 42.400, "end": 42.900},
                        {"word": "can't", "start": 42.900, "end": 44.200},
                        {"word": "resist", "start": 44.200, "end": 45.400},
                        {"word": "it", "start": 45.400, "end": 46.353},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在撕扯中沦陷",
                    "words": [
                        {"word": "Oh,", "start": 46.811, "end": 47.150},
                        {"word": "I", "start": 47.150, "end": 47.350},
                        {"word": "love", "start": 47.350, "end": 47.750},
                        {"word": "it", "start": 47.750, "end": 47.950},
                        {"word": "and", "start": 47.950, "end": 48.250},
                        {"word": "I", "start": 48.250, "end": 48.450},
                        {"word": "hate", "start": 48.450, "end": 48.850},
                        {"word": "it", "start": 48.850, "end": 49.050},
                        {"word": "at", "start": 49.050, "end": 49.300},
                        {"word": "the", "start": 49.300, "end": 49.550},
                        {"word": "same", "start": 49.550, "end": 49.950},
                        {"word": "time", "start": 49.950, "end": 50.357},
                    ],
                },
                {
                    "en": "You and I drink the poison from the same vine",
                    "zh": "你我饮下的毒汁，本就同根而生",
                    "words": [
                        {"word": "You", "start": 50.440, "end": 50.750},
                        {"word": "and", "start": 50.750, "end": 51.050},
                        {"word": "I", "start": 51.050, "end": 51.250},
                        {"word": "drink", "start": 51.250, "end": 51.750},
                        {"word": "the", "start": 51.750, "end": 52.050},
                        {"word": "poison", "start": 52.050, "end": 52.850},
                        {"word": "from", "start": 52.850, "end": 53.250},
                        {"word": "the", "start": 53.250, "end": 53.550},
                        {"word": "same", "start": 53.550, "end": 53.950},
                        {"word": "vine", "start": 53.950, "end": 54.277},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在沉溺中挣扎",
                    "words": [
                        {"word": "Oh,", "start": 54.361, "end": 54.700},
                        {"word": "I", "start": 54.700, "end": 54.900},
                        {"word": "love", "start": 54.900, "end": 55.300},
                        {"word": "it", "start": 55.300, "end": 55.500},
                        {"word": "and", "start": 55.500, "end": 55.800},
                        {"word": "I", "start": 55.800, "end": 56.000},
                        {"word": "hate", "start": 56.000, "end": 56.400},
                        {"word": "it", "start": 56.400, "end": 56.600},
                        {"word": "at", "start": 56.600, "end": 56.900},
                        {"word": "the", "start": 56.900, "end": 57.150},
                        {"word": "same", "start": 57.150, "end": 57.550},
                        {"word": "time", "start": 57.550, "end": 58.156},
                    ],
                },
            ],
            "study_notes": [
                "• resist /rɪˈzɪst/：v. 抵制，抗拒（can't resist 表难以抗拒诱惑/情愫）",
                "• at the same time：同时，兼备（描摹既深爱又痛恨的剧烈心理矛盾）",
                "• poison from the same vine：同根而生之毒（源自同一株葡萄藤，宿命隐喻）",
                "• darkness in the distance：远方暗影（喻潜意识里对未来命运的未知恐惧）",
            ],
        },

        # =====================================================================
        # Page 3: 【第三幕 · 逃避白昼】Chorus 1 奔逃高潮 (Lines 13~18, 58.5s - 75.0s)
        # =====================================================================
        {
            "page_idx": 3,
            "chapter_title": "【第三幕 · 逃避白昼】 Chorus 1 烈日狂奔与隐匿之罪",
            "time_range": (58.5, 75.0),
            "is_cover_page": False,
            "lyrics": [
                {
                    "en": "Hiding all of our sins from the daylight",
                    "zh": "将我们所有的罪孽，悄悄隐匿于白昼之下",
                    "words": [
                        {"word": "Hiding", "start": 58.239, "end": 58.750},
                        {"word": "all", "start": 58.750, "end": 59.100},
                        {"word": "of", "start": 59.100, "end": 59.350},
                        {"word": "our", "start": 59.350, "end": 59.650},
                        {"word": "sins", "start": 59.650, "end": 60.300},
                        {"word": "from", "start": 60.300, "end": 60.700},
                        {"word": "the", "start": 60.700, "end": 61.000},
                        {"word": "daylight", "start": 61.000, "end": 61.576},
                    ],
                },
                {
                    "en": "From the daylight",
                    "zh": "逃避烈日与破晓",
                    "words": [
                        {"word": "From", "start": 61.659, "end": 62.100},
                        {"word": "the", "start": 62.100, "end": 62.400},
                        {"word": "daylight", "start": 62.400, "end": 63.119},
                    ],
                },
                {
                    "en": "Running from the daylight",
                    "zh": "在白昼的追捕下疯狂奔逃",
                    "words": [
                        {"word": "Running", "start": 63.203, "end": 63.850},
                        {"word": "from", "start": 63.850, "end": 64.250},
                        {"word": "the", "start": 64.250, "end": 64.550},
                        {"word": "daylight", "start": 64.550, "end": 64.996},
                    ],
                },
                {
                    "en": "From the daylight",
                    "zh": "逃避真相的刺目光芒",
                    "words": [
                        {"word": "From", "start": 65.079, "end": 65.500},
                        {"word": "the", "start": 65.500, "end": 65.800},
                        {"word": "daylight", "start": 65.800, "end": 66.788},
                    ],
                },
                {
                    "en": "Running from the daylight",
                    "zh": "在日光倾泻时仓皇躲藏",
                    "words": [
                        {"word": "Running", "start": 66.871, "end": 67.550},
                        {"word": "from", "start": 67.550, "end": 67.950},
                        {"word": "the", "start": 67.950, "end": 68.250},
                        {"word": "daylight", "start": 68.250, "end": 68.921},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在沉沦中难以割舍",
                    "words": [
                        {"word": "Oh,", "start": 69.004, "end": 69.450},
                        {"word": "I", "start": 69.450, "end": 69.750},
                        {"word": "love", "start": 69.750, "end": 70.350},
                        {"word": "it", "start": 70.350, "end": 70.650},
                        {"word": "and", "start": 70.650, "end": 71.050},
                        {"word": "hate", "start": 71.050, "end": 71.650},
                        {"word": "it", "start": 71.650, "end": 71.950},
                        {"word": "at", "start": 71.950, "end": 72.350},
                        {"word": "the", "start": 72.350, "end": 72.650},
                        {"word": "same", "start": 72.650, "end": 73.050},
                        {"word": "time", "start": 73.050, "end": 73.460},
                    ],
                },
            ],
            "study_notes": [
                "• daylight /ˈdeɪlaɪt/：n. 日光，白昼；歌中深层隐喻‘道德审判与真相’",
                "• hide sins from daylight：隐匿罪孽（逃避被世人与光明审判）",
                "• run from：从……逃跑 / 逃离（表主观上强烈的恐慌与逃避机制）",
                "• Oxymoron（矛盾修辞）：爱（沉迷之欢愉）与恨（道德之折磨）并存",
            ],
        },

        # =====================================================================
        # Page 4: 【第四幕 · 绝境祈援】Verse 2 (Lines 19~24, 75.0s - 105.0s)
        # =====================================================================
        {
            "page_idx": 4,
            "chapter_title": "【第四幕 · 绝境祈援】 Verse 2 屈膝长跪与深渊追光",
            "time_range": (75.0, 105.0),
            "is_cover_page": False,
            "lyrics": [
                {
                    "en": "Telling myself it's the last time",
                    "zh": "告诫自己，这定然是最后一次",
                    "words": [
                        {"word": "Telling", "start": 77.013, "end": 77.850},
                        {"word": "myself", "start": 77.850, "end": 78.850},
                        {"word": "it's", "start": 78.850, "end": 79.250},
                        {"word": "the", "start": 79.250, "end": 79.550},
                        {"word": "last", "start": 79.550, "end": 80.050},
                        {"word": "time", "start": 80.050, "end": 80.222},
                    ],
                },
                {
                    "en": "Can you spare any mercy that you might find",
                    "zh": "你可否赐予哪怕一丝残存的怜悯与宽恕",
                    "words": [
                        {"word": "Can", "start": 80.305, "end": 80.750},
                        {"word": "you", "start": 80.750, "end": 81.050},
                        {"word": "spare", "start": 81.050, "end": 81.750},
                        {"word": "any", "start": 81.750, "end": 82.250},
                        {"word": "mercy", "start": 82.250, "end": 83.150},
                        {"word": "that", "start": 83.150, "end": 83.550},
                        {"word": "you", "start": 83.550, "end": 83.850},
                        {"word": "might", "start": 83.850, "end": 84.250},
                        {"word": "find", "start": 84.250, "end": 84.604},
                    ],
                },
                {
                    "en": "If I'm down on my knees again?",
                    "zh": "若我再度绝望地跪倒在尘埃里？",
                    "words": [
                        {"word": "If", "start": 84.688, "end": 85.050},
                        {"word": "I'm", "start": 85.050, "end": 85.450},
                        {"word": "down", "start": 85.450, "end": 86.150},
                        {"word": "on", "start": 86.150, "end": 86.450},
                        {"word": "my", "start": 86.450, "end": 86.750},
                        {"word": "knees", "start": 86.750, "end": 87.550},
                        {"word": "again?", "start": 87.550, "end": 88.188},
                    ],
                },
                {
                    "en": "Deep down, way down, Lord, I try",
                    "zh": "在灵魂至深之处，主啊，我曾竭力追寻救赎",
                    "words": [
                        {"word": "Deep", "start": 91.229, "end": 91.850},
                        {"word": "down,", "start": 91.850, "end": 92.450},
                        {"word": "way", "start": 92.450, "end": 93.050},
                        {"word": "down,", "start": 93.050, "end": 93.650},
                        {"word": "Lord,", "start": 93.650, "end": 94.350},
                        {"word": "I", "start": 94.350, "end": 94.650},
                        {"word": "try", "start": 94.650, "end": 94.981},
                    ],
                },
                {
                    "en": "I try to follow your light, but it's nighttime",
                    "zh": "我试图追逐你的光芒，周遭却唯有永夜",
                    "words": [
                        {"word": "I", "start": 95.065, "end": 95.350},
                        {"word": "try", "start": 95.350, "end": 95.850},
                        {"word": "to", "start": 95.850, "end": 96.150},
                        {"word": "follow", "start": 96.150, "end": 96.850},
                        {"word": "your", "start": 96.850, "end": 97.250},
                        {"word": "light,", "start": 97.250, "end": 97.850},
                        {"word": "but", "start": 97.850, "end": 98.150},
                        {"word": "it's", "start": 98.150, "end": 98.450},
                        {"word": "nighttime", "start": 98.450, "end": 99.066},
                    ],
                },
                {
                    "en": "Please, don't leave me in the end",
                    "zh": "恳求你，莫在终局之时将我抛弃……",
                    "words": [
                        {"word": "Please,", "start": 99.150, "end": 99.950},
                        {"word": "don't", "start": 99.950, "end": 100.550},
                        {"word": "leave", "start": 100.550, "end": 101.450},
                        {"word": "me", "start": 101.450, "end": 102.050},
                        {"word": "in", "start": 102.050, "end": 102.550},
                        {"word": "the", "start": 102.550, "end": 102.950},
                        {"word": "end", "start": 102.950, "end": 103.656},
                    ],
                },
            ],
            "study_notes": [
                "• spare mercy：赐予怜悯 / 宽恕（spare 表‘免去责罚，手下留情’）",
                "• down on one's knees：屈膝跪拜（表极度忏悔、祈求或精神崩溃）",
                "• deep down：在内心深处，本质上（指卸下伪装后最真实的内心）",
                "• in the end：归根到底 / 在人生的终局（不同于 at the end 表具体终点）",
            ],
        },

        # =====================================================================
        # Page 5: 【第五幕 · 宽恕与纠葛】Pre-Chorus 2 + Chorus 2 (Lines 25~31, 105.0s - 136.0s)
        # =====================================================================
        {
            "page_idx": 5,
            "chapter_title": "【第五幕 · 宽恕与纠葛】 Pre-Chorus 2 忏悔之音与爱恨撕扯",
            "time_range": (105.0, 136.0),
            "is_cover_page": False,
            "lyrics": [
                {
                    "en": "There's darkness in the distance",
                    "zh": "极目远方，依然尽是无边暗影",
                    "words": [
                        {"word": "There's", "start": 107.247, "end": 107.850},
                        {"word": "darkness", "start": 107.850, "end": 108.650},
                        {"word": "in", "start": 108.650, "end": 108.950},
                        {"word": "the", "start": 108.950, "end": 109.250},
                        {"word": "distance", "start": 109.250, "end": 110.040},
                    ],
                },
                {
                    "en": "I'm begging for forgiveness",
                    "zh": "我声声泣求着宽恕与救赎",
                    "words": [
                        {"word": "I'm", "start": 111.127, "end": 111.650},
                        {"word": "begging", "start": 111.650, "end": 112.550},
                        {"word": "for", "start": 112.550, "end": 112.950},
                        {"word": "forgiveness", "start": 112.950, "end": 113.840},
                    ],
                },
                {
                    "en": "But I know I might resist it, oh",
                    "zh": "却深知内心仍在不可遏制地抗拒，噢",
                    "words": [
                        {"word": "But", "start": 114.380, "end": 115.100},
                        {"word": "I", "start": 115.100, "end": 115.600},
                        {"word": "know", "start": 115.600, "end": 116.400},
                        {"word": "I", "start": 116.400, "end": 117.100},
                        {"word": "might", "start": 117.100, "end": 118.000},
                        {"word": "resist", "start": 118.000, "end": 119.200},
                        {"word": "it,", "start": 119.200, "end": 119.800},
                        {"word": "oh", "start": 119.800, "end": 120.340},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在撕扯中沦陷",
                    "words": [
                        {"word": "Oh,", "start": 120.428, "end": 120.950},
                        {"word": "I", "start": 120.950, "end": 121.350},
                        {"word": "love", "start": 121.350, "end": 121.950},
                        {"word": "it", "start": 121.950, "end": 122.250},
                        {"word": "and", "start": 122.250, "end": 122.650},
                        {"word": "I", "start": 122.650, "end": 122.950},
                        {"word": "hate", "start": 122.950, "end": 123.550},
                        {"word": "it", "start": 123.550, "end": 123.850},
                        {"word": "at", "start": 123.850, "end": 124.150},
                        {"word": "the", "start": 124.150, "end": 124.350},
                        {"word": "same", "start": 124.350, "end": 124.550},
                        {"word": "time", "start": 124.550, "end": 124.750},
                    ],
                },
                {
                    "en": "You and I drink the poison from the same vine",
                    "zh": "你我饮下的毒汁，本就同根而生",
                    "words": [
                        {"word": "You", "start": 124.832, "end": 125.250},
                        {"word": "and", "start": 125.250, "end": 125.550},
                        {"word": "I", "start": 125.550, "end": 125.850},
                        {"word": "drink", "start": 125.850, "end": 126.350},
                        {"word": "the", "start": 126.350, "end": 126.650},
                        {"word": "poison", "start": 126.650, "end": 127.350},
                        {"word": "from", "start": 127.350, "end": 127.650},
                        {"word": "the", "start": 127.650, "end": 127.850},
                        {"word": "same", "start": 127.850, "end": 128.050},
                        {"word": "vine", "start": 128.050, "end": 128.256},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，难以解脱",
                    "words": [
                        {"word": "Oh,", "start": 128.340, "end": 128.750},
                        {"word": "I", "start": 128.750, "end": 129.050},
                        {"word": "love", "start": 129.050, "end": 129.650},
                        {"word": "it", "start": 129.650, "end": 129.950},
                        {"word": "and", "start": 129.950, "end": 130.350},
                        {"word": "I", "start": 130.350, "end": 130.650},
                        {"word": "hate", "start": 130.650, "end": 131.250},
                        {"word": "it", "start": 131.250, "end": 131.450},
                        {"word": "at", "start": 131.450, "end": 131.650},
                        {"word": "the", "start": 131.650, "end": 131.850},
                        {"word": "same", "start": 131.850, "end": 132.050},
                        {"word": "time", "start": 132.050, "end": 132.312},
                    ],
                },
                {
                    "en": "Hiding all of our sins from the daylight",
                    "zh": "将我们所有的罪孽，悄悄隐匿于白昼之下",
                    "words": [
                        {"word": "Hiding", "start": 132.395, "end": 132.950},
                        {"word": "all", "start": 132.950, "end": 133.350},
                        {"word": "of", "start": 133.350, "end": 133.650},
                        {"word": "our", "start": 133.650, "end": 133.950},
                        {"word": "sins", "start": 133.950, "end": 134.550},
                        {"word": "from", "start": 134.550, "end": 134.850},
                        {"word": "the", "start": 134.850, "end": 135.050},
                        {"word": "daylight", "start": 135.050, "end": 135.150},
                    ],
                },
            ],
            "study_notes": [
                "• beg for forgiveness：乞求宽恕赦免（beg for 表低微虔诚的哀求）",
                "• resist /rɪˈzɪst/：v. 抵抗，抵受（might resist 表意志力的摇摆）",
                "• drink poison：饮鸩止渴（明知有害却甘之如饴的宿命悲剧感）",
                "• sins from daylight：日光下的罪愆（基督教文化中对光与暗的经典意象）",
            ],
        },

        # =====================================================================
        # Page 6: 【第六幕 · 终局破晓】Grand Finale & Outro (Lines 32~45, 136.0s - 190.5s)
        # =====================================================================
        {
            "page_idx": 6,
            "chapter_title": "【第六幕 · 终局破晓】 Grand Finale 遁入永夜与同生之毒",
            "time_range": (136.0, 190.5),
            "is_cover_page": False,
            "lyrics": [
                {
                    "en": "From the daylight, running from the daylight",
                    "zh": "逃避白昼，在烈日倾泻下奔逃",
                    "words": [
                        {"word": "From", "start": 135.234, "end": 135.650},
                        {"word": "the", "start": 135.650, "end": 135.950},
                        {"word": "daylight,", "start": 135.950, "end": 136.650},
                        {"word": "running", "start": 136.650, "end": 137.350},
                        {"word": "from", "start": 137.350, "end": 137.650},
                        {"word": "the", "start": 137.650, "end": 137.950},
                        {"word": "daylight", "start": 137.950, "end": 138.650},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在撕扯中沦陷",
                    "words": [
                        {"word": "Oh,", "start": 142.574, "end": 143.150},
                        {"word": "I", "start": 143.150, "end": 143.550},
                        {"word": "love", "start": 143.550, "end": 144.250},
                        {"word": "it", "start": 144.250, "end": 144.650},
                        {"word": "and", "start": 144.650, "end": 145.150},
                        {"word": "I", "start": 145.150, "end": 145.550},
                        {"word": "hate", "start": 145.550, "end": 146.250},
                        {"word": "it", "start": 146.250, "end": 146.650},
                        {"word": "at", "start": 146.650, "end": 147.150},
                        {"word": "the", "start": 147.150, "end": 147.450},
                        {"word": "same", "start": 147.450, "end": 148.250},
                        {"word": "time", "start": 148.250, "end": 149.622},
                    ],
                },
                {
                    "en": "You and I drink the poison from the same vine",
                    "zh": "你我饮下的毒液，本就同根而生",
                    "words": [
                        {"word": "You", "start": 153.877, "end": 154.250},
                        {"word": "and", "start": 154.250, "end": 154.550},
                        {"word": "I", "start": 154.550, "end": 154.850},
                        {"word": "drink", "start": 154.850, "end": 155.350},
                        {"word": "the", "start": 155.350, "end": 155.650},
                        {"word": "poison", "start": 155.650, "end": 156.350},
                        {"word": "from", "start": 156.350, "end": 156.650},
                        {"word": "the", "start": 156.650, "end": 156.850},
                        {"word": "same", "start": 156.850, "end": 157.050},
                        {"word": "vine", "start": 157.050, "end": 157.172},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，我爱恨交织，在沉溺中无法自拔",
                    "words": [
                        {"word": "Oh,", "start": 157.255, "end": 157.650},
                        {"word": "I", "start": 157.650, "end": 157.950},
                        {"word": "love", "start": 157.950, "end": 158.550},
                        {"word": "it", "start": 158.550, "end": 158.850},
                        {"word": "and", "start": 158.850, "end": 159.250},
                        {"word": "I", "start": 159.250, "end": 159.550},
                        {"word": "hate", "start": 159.550, "end": 160.150},
                        {"word": "it", "start": 160.150, "end": 160.450},
                        {"word": "at", "start": 160.450, "end": 160.750},
                        {"word": "the", "start": 160.750, "end": 160.950},
                        {"word": "same", "start": 160.950, "end": 161.150},
                        {"word": "time", "start": 161.150, "end": 161.296},
                    ],
                },
                {
                    "en": "Hiding all of our sins from the daylight",
                    "zh": "将我们所有的罪孽，悄悄隐匿于白昼之下",
                    "words": [
                        {"word": "Hiding", "start": 161.384, "end": 162.050},
                        {"word": "all", "start": 162.050, "end": 162.450},
                        {"word": "of", "start": 162.450, "end": 162.750},
                        {"word": "our", "start": 162.750, "end": 163.150},
                        {"word": "sins", "start": 163.150, "end": 163.850},
                        {"word": "from", "start": 163.850, "end": 164.150},
                        {"word": "the", "start": 164.150, "end": 164.450},
                        {"word": "daylight", "start": 164.450, "end": 164.763},
                    ],
                },
                {
                    "en": "From the daylight, running from the daylight",
                    "zh": "逃避白昼，在日光追捕中狂奔……",
                    "words": [
                        {"word": "From", "start": 164.846, "end": 165.250},
                        {"word": "the", "start": 165.250, "end": 165.550},
                        {"word": "daylight,", "start": 165.550, "end": 166.250},
                        {"word": "running", "start": 166.250, "end": 166.850},
                        {"word": "from", "start": 166.850, "end": 167.150},
                        {"word": "the", "start": 167.150, "end": 167.450},
                        {"word": "daylight", "start": 167.450, "end": 168.183},
                    ],
                },
                {
                    "en": "Oh, I love it and I hate it at the same time",
                    "zh": "噢，沉沦于此，亦无悔于此……（终章回音）",
                    "words": [
                        {"word": "Oh,", "start": 172.604, "end": 173.250},
                        {"word": "I", "start": 173.250, "end": 173.650},
                        {"word": "love", "start": 173.650, "end": 174.350},
                        {"word": "it", "start": 174.350, "end": 174.750},
                        {"word": "and", "start": 174.750, "end": 175.250},
                        {"word": "hate", "start": 175.250, "end": 175.850},
                        {"word": "it", "start": 175.850, "end": 176.150},
                        {"word": "at", "start": 176.150, "end": 176.550},
                        {"word": "the", "start": 176.550, "end": 176.850},
                        {"word": "same", "start": 176.850, "end": 177.050},
                        {"word": "time", "start": 177.050, "end": 177.192},
                    ],
                },
            ],
            "study_notes": [
                "• running from the daylight：向着暗影奔逃（隐喻无法面对现实与理性）",
                "• same vine：同根藤蔓（揭示爱人之间既相互救赎又彼此毁灭的宿命羁绊）",
                "• full song closure：全曲终章，钢琴以极弱音收尾，呈现出余音绕梁之美",
                "• 音乐与语言共振：在深沉低音旋律中，体会地道英文文学修辞的极致魅力",
            ],
        },
    ]


def render_daylight_page_canvas(
    page_data: Dict[str, Any],
    builder: CanvasBuilder,
) -> Tuple[Image.Image, List[LyricLine]]:
    """Renders a single 1080x1920 notebook page canvas and measures word coordinates for physics."""
    W, H = builder.config.width, builder.config.height
    canvas = Image.new("RGBA", (W, H), (254, 251, 246, 255))

    # 1. Paper texture
    tex_path = Path(__file__).parent / "assets" / "paper_texture_ivory.jpg"
    if tex_path.exists():
        tex = Image.open(tex_path).convert("RGBA").resize((W, H), Image.Resampling.BILINEAR)
        canvas = Image.blend(canvas, tex, alpha=0.14)

    draw = ImageDraw.Draw(canvas)

    # 2. Left margin line & binder holes
    draw.line([(130, 80), (130, 1840)], fill=(215, 95, 95, 160), width=2)
    for hy in [250, 600, 960, 1320, 1680]:
        draw.ellipse([45, hy - 14, 75, hy + 14], fill=(225, 220, 212, 255), outline=(190, 185, 178, 255), width=2)

    # 3. Horizontal ruled lines
    first_ry = 410 if page_data.get("is_cover_page") else 220
    for ry in range(first_ry, 1420, 64):
        draw.line([(110, ry), (1020, ry)], fill=(220, 230, 242, 160), width=1)

    # 4. Top Masthead (Consistent across all pages)
    builder.draw_handdrawn_circle_seal(canvas, (175, 82), radius=26, logo_size=42)
    draw.text((215, 66), "六维时空号", font=builder.font_zh_tian_32, fill=(30, 42, 60))
    draw.text((375, 68), "｜", font=builder.font_sym_hiragino_26, fill=(190, 175, 150))
    builder.draw_mixed_text(
        draw, (405, 72), "“不同的视角，看见更大的世界。”", builder.font_zh_tian_23, builder.font_sym_hiragino_21, fill=(195, 125, 30)
    )
    p_num = f"✎ 音乐手账 · NO.083 (P{page_data['page_idx']}/6)"
    builder.draw_mixed_text(draw, (770, 72), p_num, builder.font_zh_tian_22, builder.font_sym_arial_20, fill=(120, 130, 145))
    for dx in range(150, 1000, 16):
        draw.line([(dx, 120), (dx + 8, 120)], fill=(215, 205, 185, 180), width=1)

    is_cover = page_data.get("is_cover_page", False)

    if is_cover:
        # Title: Daylight (Dark Gothic Midnight + Ember Crimson)
        t1 = "Daylight"
        draw.text((150, 134), t1, font=builder.font_en_bradley_56, fill=(145, 35, 35))
        w_t1 = draw.textlength(t1, font=builder.font_en_bradley_56)

        zh_title_text = "《白昼暗影》"
        zh_w = builder.get_mixed_text_width(draw, zh_title_text, builder.font_zh_tian_36, builder.font_sym_hiragino_32)
        zh_x = 150 + w_t1 + 30
        draw.rounded_rectangle([zh_x - 8, 144, zh_x + zh_w + 8, 188], radius=8, fill=(255, 218, 90, 170))
        builder.draw_mixed_text(draw, (zh_x, 140), zh_title_text, builder.font_zh_tian_36, builder.font_sym_hiragino_32, fill=(30, 38, 48))

        underline_end = int(150 + w_t1 + 10)
        draw.line([(150, 204), (underline_end, 204)], fill=(145, 35, 35, 220), width=3)

        artist_desc = "原唱：David Kushner (2023)  ·  全球现象级暗黑福音诗意神作  ·  全曲双语伴读"
        builder.draw_mixed_text(draw, (150, 218), artist_desc, builder.font_zh_tian_22, builder.font_sym_hiragino_21, fill=(90, 100, 115))

        # Accolades Badges
        builder.draw_handdrawn_rect(draw, (145, 248, 1005, 376), fill=(255, 250, 240, 245), outline=(225, 175, 95, 240), width=2, roughness=1.4)
        badges = [
            ("★ 全球流媒体超 18 亿播放", (245, 130, 15), (255, 255, 255), (210, 85, 0)),
            ("◆ 现象级低音叙事殿堂神作", (20, 120, 210), (255, 255, 255), (10, 90, 170)),
            ("● Billboard 全球单曲榜 Top 5", (125, 60, 200), (255, 255, 255), (95, 35, 165)),
        ]
        box_x0 = 145
        box_w = 860
        by = 264
        b_widths = []
        for b_text, _, _, _ in badges:
            w = 0
            for ch in b_text:
                f = builder.font_zh_tian_22 if is_cjk(ch) else builder.font_sym_arial_21
                w += draw.textlength(ch, font=f)
            b_widths.append(w + 36)
        gap = (box_w - sum(b_widths)) / 4
        cur_bx = box_x0 + gap
        for idx, (b_text, b_fill, b_text_c, b_border) in enumerate(badges):
            bw = b_widths[idx]
            builder.draw_handdrawn_rect(draw, (cur_bx, by, cur_bx + bw, by + 40), fill=b_fill, outline=b_border, width=2, roughness=1.0)
            builder.draw_mixed_text(draw, (cur_bx + 18, by + 8), b_text, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=b_text_c)
            cur_bx += bw + gap

        quote_prefix = "✎ 策展手记: “以深沉男低音与管风琴大提琴，"
        quote_highlight = "写尽深渊中的挣扎、救赎与矛盾爱恨"
        quote_suffix = "。”"
        w_qp = builder.get_mixed_text_width(draw, quote_prefix, builder.font_zh_tian_22, builder.font_sym_arial_21)
        w_qh = builder.get_mixed_text_width(draw, quote_highlight, builder.font_zh_tian_22, builder.font_sym_arial_21)
        hl_x0 = 175 + w_qp
        hl_x1 = hl_x0 + w_qh
        draw.rounded_rectangle([hl_x0 - 4, 327, hl_x1 + 4, 353], radius=6, fill=(255, 215, 130, 160))
        builder.draw_mixed_text(draw, (175, 326), quote_prefix, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(100, 90, 80))
        builder.draw_mixed_text(draw, (hl_x0, 326), quote_highlight, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(175, 45, 20))
        builder.draw_mixed_text(draw, (hl_x1, 326), quote_suffix, builder.font_zh_tian_22, builder.font_sym_arial_21, fill=(100, 90, 80))

        # Stanza positions for Page 1
        stanza_y = [405, 565, 725, 885, 1045, 1205]
    else:
        # Chapter header for Pages 2..6
        chap_title = page_data["chapter_title"]
        ch_w = builder.get_mixed_text_width(draw, chap_title, builder.font_zh_tian_28, builder.font_sym_hiragino_26)
        builder.draw_handdrawn_rect(draw, (145, 136, 145 + ch_w + 40, 184), fill=(255, 245, 230, 240), outline=(220, 150, 70, 230), width=2, roughness=1.2)
        builder.draw_mixed_text(draw, (165, 142), chap_title, builder.font_zh_tian_28, builder.font_sym_hiragino_26, fill=(135, 40, 30))

        sub_tag = "全曲官方双语精读伴唱  ·  六维时空精修译文"
        builder.draw_mixed_text(draw, (150, 196), sub_tag, builder.font_zh_tian_22, builder.font_sym_hiragino_21, fill=(120, 130, 145))

        # Stanza positions for Pages 2..6
        n_lines = len(page_data["lyrics"])
        pitch = 152 if n_lines >= 7 else 162
        start_y = 230
        stanza_y = [start_y + i * pitch for i in range(n_lines)]

    # Draw Lyrics & Measure Word Coordinates
    tracking = -1.2
    font_en_40 = builder._resolve_font([("/System/Library/Fonts/Noteworthy.ttc", 40, 1)])
    measured_lines: List[LyricLine] = []

    doodle_specs = [
        ((895, 400), 95),
        ((890, 560), 95),
        ((895, 720), 90),
        ((880, 880), 105),
        ((900, 1040), 85),
        ((885, 1200), 95),
        ((890, 1320), 85),
    ]

    for i, item in enumerate(page_data["lyrics"]):
        en_text = item["en"]
        zh_text = item["zh"]
        raw_words = item["words"]
        sy = stanza_y[i]

        # Auto-scale font for long lines
        raw_w = sum(draw.textlength(ch, font=builder.font_en_noteworthy_45) + tracking for ch in en_text)
        cur_font = font_en_40 if raw_w > 680 else builder.font_en_noteworthy_45

        # 1. Draw English text
        cur_x = 150.0
        for ch in en_text:
            draw.text((cur_x, sy), ch, font=cur_font, fill=(22, 28, 38))
            cur_x += draw.textlength(ch, font=cur_font) + tracking

        # 2. Draw Chinese translation (+70px vertical separation)
        builder.draw_mixed_text(draw, (150, sy + 70), zh_text, builder.font_zh_tian_28, builder.font_sym_hiragino_26, fill=(75, 85, 100))

        # 3. Contextual Doodle
        if i < len(builder.doodles) and i < len(doodle_specs):
            d_img = builder.doodles[i]
            d_xy, d_w = doodle_specs[i]
            if not is_cover:
                d_xy = (d_xy[0], int(sy - 10))
            if cur_x + 15 > d_xy[0]:
                d_xy = (int(cur_x + 20), d_xy[1])
            aspect = d_img.height / d_img.width
            d_h = int(d_w * aspect)
            d_scaled = d_img.resize((d_w, d_h), Image.Resampling.LANCZOS)
            canvas.paste(d_scaled, d_xy, d_scaled)

        # 4. Measure word coordinates for Pen Physics
        line_words: List[LyricWord] = []
        cur_prefix = ""
        for w_info in raw_words:
            w_str = w_info["word"].strip()
            idx = en_text.find(w_str, len(cur_prefix))
            if idx == -1:
                idx = len(cur_prefix)
            prefix_before = en_text[:idx]
            prefix_after = en_text[: idx + len(w_str)]

            w_start_x = 150.0 + sum(draw.textlength(ch, font=cur_font) + tracking for ch in prefix_before)
            w_end_x = 150.0 + sum(draw.textlength(ch, font=cur_font) + tracking for ch in prefix_after)
            y_bottom = sy + 44.0

            line_words.append(
                LyricWord(
                    word=w_str,
                    start_time=float(w_info["start"]),
                    end_time=float(w_info["end"]),
                    x_start=float(w_start_x),
                    x_end=float(w_end_x),
                    y_bottom=float(y_bottom),
                )
            )
            cur_prefix = prefix_after

        measured_lines.append(
            LyricLine(
                line_index=i,
                en_text=en_text,
                zh_text=zh_text,
                y_en=float(sy),
                y_zh=float(sy + 70.0),
                ruled_line_y=float(sy + 46.0),
                words=line_words,
            )
        )

    # 5. Study Notes Card at bottom (y = 1395..1750)
    card_y0, card_y1 = 1395, 1750
    builder.draw_handdrawn_rect(draw, (145, card_y0, 1005, card_y1), fill=(255, 252, 245, 240), outline=(215, 200, 175, 230), width=2, roughness=1.5)
    header_txt = f"◆ 重点表达手账解析 ({page_data['chapter_title'][:8]}...)"
    hw = builder.get_mixed_text_width(draw, header_txt, builder.font_zh_tian_28, builder.font_sym_hiragino_26)
    draw.rounded_rectangle([170, card_y0 + 16, 170 + hw + 24, card_y0 + 58], radius=6, fill=(255, 220, 110, 180))
    builder.draw_mixed_text(draw, (182, card_y0 + 22), header_txt, builder.font_zh_tian_28, builder.font_sym_hiragino_26, fill=(40, 48, 60))

    ny = card_y0 + 78
    for note_text in page_data["study_notes"]:
        builder.draw_mixed_text(draw, (175, ny), note_text, builder.font_zh_tian_23, builder.font_sym_arial_21, fill=(48, 56, 68))
        ny += 54

    return canvas, measured_lines

