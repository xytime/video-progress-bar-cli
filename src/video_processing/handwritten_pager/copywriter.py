"""Viral copy generation for WeChat Channels and Douyin.

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-08 | Antigravity | Initial implementation of copywriter with platform constraints |
"""

from typing import Dict, List, Optional

from .contracts import CopywritingPackage, HandwrittenPagerError


class Copywriter:
    """Generates platform-compliant, viral copywriting packages."""

    @staticmethod
    def generate_copy(
        title: str = "Let Me Down Slowly",
        artist: str = "Alec Benjamin",
        chinese_title: str = "慢慢放手",
    ) -> CopywritingPackage:
        """Generates viral copy strictly complying with length and persona requirements."""
        # WeChat short title: strictly 6-16 characters
        wechat_short_title = f"听歌学英语：{chinese_title}"
        if len(wechat_short_title) > 16:
            wechat_short_title = wechat_short_title[:16]
        elif len(wechat_short_title) < 6:
            wechat_short_title = "沉浸式双语跟唱伴读"

        # WeChat post description
        wechat_copy = (
            f"🎵 经典英文神曲《{title}》（{chinese_title}）- 原唱：{artist}\n"
            "“如果结局注定是分开，请试着对我温柔一点……”\n"
            "沉浸式双语手写笔记跟唱伴读，带你一边听最治愈的歌，一边把实用地道英语表达记进脑海里！\n\n"
            "📌 核心表达积累：\n"
            "1. let sb down slowly：委婉提出分手 / 温柔地让某人面对失望\n"
            "2. sympathy /ˈsɪmpəθi/：n. 同情，怜悯；理解与共情\n"
            "3. wanna = want to：口语高频略缩，表示“想要”\n"
            "4. lonely /ˈləʊnli/：adj. 寂寞的，孤独的\n\n"
            "🎧 戴上耳机，跟着笔尖轻轻跟唱，感受音乐与语言的共鸣吧～"
        )

        # Douyin title: strictly <= 30 characters
        douyin_title = f"全网刷屏的治愈神曲《{chinese_title}》双语伴读"
        if len(douyin_title) > 30:
            douyin_title = douyin_title[:30]

        # Douyin post description
        douyin_copy = (
            f"单曲循环了无数次的经典神曲，{artist}《{title}》（{chinese_title}）手写双语伴读！"
            "温柔的旋律里藏着最深情的告别，边听歌边学地道英语表达。"
        )

        hashtags = [
            "#听歌学英语",
            "#英语学习",
            "#双语跟唱",
            "#治愈音乐",
            "#经典英文歌",
            f"#{title.replace(' ', '')}",
        ]

        package = CopywritingPackage(
            wechat_short_title=wechat_short_title,
            wechat_copy=wechat_copy,
            douyin_title=douyin_title,
            douyin_copy=douyin_copy,
            hashtags=hashtags,
        )
        package.validate()
        return package
