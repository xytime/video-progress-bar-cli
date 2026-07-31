"""封面生成引擎 v2.0 单元测试 (test_cover_v2.py)

# Modification History
| Version | Date       | Author                       | Description                                                  |
|---------|------------|------------------------------|--------------------------------------------------------------|
| 1.0.0   | 2026-05-26 | Gemini_3.5_Flash_planning    | 初始创建，针对语义分析、主题映射、布局装配与 Facade 入口进行单元测试 |
| 1.1.0 | 2026-07-31 | Codex                         | 覆盖专属主视觉与受控标题位置的布局规划 |
"""

import os
import json
import pytest
from pathlib import Path
from src.cover.semantic import SemanticAnalyzer, ContentSignal
from src.cover.themes import ThemeRegistry
from src.cover.layout import LayoutComposer
from src.cover.engine import CoverEngine

@pytest.fixture
def temp_config_paths(tmp_path):
    """
    [Gemini_3.5_Flash_planning] 准备测试用临时 rules/themes json 配置文件
    """
    rules_data = {
        "rules": [
            {
                "id": "policy_security",
                "hints": ["policy", "quantum"],
                "keywords": ["和谈", "政策"],
                "accent": "red_alert",
                "base_gradient": "policy_security",
                "metaphor": "shield-off",
                "metaphor_placement": "bottom-left",
                "emotion_temperature": "cold",
                "default_badge": "安全局势"
            },
            {
                "id": "default",
                "hints": [],
                "keywords": [],
                "accent": "cyan_pulsing",
                "base_gradient": "deep_blue",
                "metaphor": "zap",
                "metaphor_placement": "top-right",
                "emotion_temperature": "neutral",
                "default_badge": "科技观察"
            }
        ]
    }
    
    themes_data = {
        "themes": {
            "policy_security": {
                "background_gradient_start": "#080202",
                "background_gradient_end": "#090d16",
                "noise_opacity": 0.05,
                "grid_color": "rgba(239,68,68,0.05)",
                "orbs": [
                    {"cx_pct": 1.2, "cy_pct": 0.2, "radius_pct": 0.65, "color_rgba": [239, 68, 68, 140]}
                ]
            },
            "deep_blue": {
                "background_gradient_start": "#020b18",
                "background_gradient_end": "#041428",
                "noise_opacity": 0.04,
                "grid_color": "rgba(56,189,248,0.06)",
                "orbs": [
                    {"cx_pct": -0.2, "cy_pct": 0.15, "radius_pct": 0.65, "color_rgba": [56, 189, 248, 160]}
                ]
            }
        },
        "accents": {
            "red_alert": {
                "color": "#ef4444",
                "glow": "0 0 30px rgba(239,68,68,0.5)"
            },
            "cyan_pulsing": {
                "color": "#00f0ff",
                "glow": "0 0 30px rgba(0,240,255,0.6)"
            }
        }
    }
    
    rules_file = tmp_path / "rules.json"
    themes_file = tmp_path / "themes.json"
    
    rules_file.write_text(json.dumps(rules_data), encoding="utf-8")
    themes_file.write_text(json.dumps(themes_data), encoding="utf-8")
    
    return rules_file, themes_file

def test_semantic_analyzer_matching(temp_config_paths):
    """
    测试语义分析器的优先匹配与兜底逻辑
    """
    rules_file, _ = temp_config_paths
    analyzer = SemanticAnalyzer(rules_file)
    
    # A. 精准 content_hints 匹配
    p1 = {"title": "随意标题", "content_hints": ["quantum"]}
    sig1 = analyzer.analyze(p1)
    assert sig1.id == "policy_security"
    assert sig1.accent == "red_alert"
    
    # B. 模糊关键词匹配
    p2 = {"title": "这是一个关于政策的研究", "content_hints": []}
    sig2 = analyzer.analyze(p2)
    assert sig2.id == "policy_security"
    assert sig2.default_badge == "安全局势"
    
    # C. Default 规则兜底
    p3 = {"title": "无匹配内容", "content_hints": []}
    sig3 = analyzer.analyze(p3)
    assert sig3.id == "default"
    assert sig3.accent == "cyan_pulsing"

def test_theme_registry_resolution(temp_config_paths):
    """
    测试主题配色字典的映射和数据提取
    """
    _, themes_file = temp_config_paths
    registry = ThemeRegistry(themes_file)
    
    sig = ContentSignal(
        id="policy_security",
        accent="red_alert",
        base_gradient="policy_security",
        metaphor="shield-off",
        metaphor_placement="bottom-left",
        emotion_temperature="cold",
        default_badge="安全局势"
    )
    
    res = registry.resolve(sig)
    assert res["background_gradient_start"] == "#080202"
    assert res["accent_color"] == "#ef4444"
    assert len(res["orbs"]) == 1
    
    # 兜底查询不存在的主题
    bad_sig = ContentSignal(
        id="unknown",
        accent="unknown",
        base_gradient="unknown",
        metaphor="zap",
        metaphor_placement="top-right",
        emotion_temperature="neutral",
        default_badge="Default"
    )
    res_bad = registry.resolve(bad_sig)
    assert res_bad["background_gradient_start"] == "#020b18"  # 降级到 deep_blue
    assert res_bad["accent_color"] == "#00f0ff"             # 降级到 cyan_pulsing

def test_layout_composer():
    """
    测试 LayoutComposer 对各子组件输出的完整拼接
    """
    composer = LayoutComposer()
    payload = {
        "title": "大模型的发展",
        "subtitle": "副标题补充",
        "category": "科技"
    }
    sig = ContentSignal(
        id="default",
        accent="cyan_pulsing",
        base_gradient="deep_blue",
        metaphor="zap",
        metaphor_placement="top-right",
        emotion_temperature="neutral",
        default_badge="科技观察"
    )
    theme_resolved = {
        "background_gradient_start": "#020b18",
        "background_gradient_end": "#041428",
        "noise_opacity": 0.04,
        "grid_color": "rgba(56,189,248,0.06)",
        "orbs": [],
        "accent_color": "#00f0ff",
        "accent_glow": "0 0 30px rgba(0,240,255,0.6)"
    }
    
    spec = composer.compose(payload, sig, theme_resolved)
    assert spec["title"] == "大模型的发展"
    assert spec["subtitle"] == "副标题补充"
    assert spec["badge"] == "科技"  # 优先采用 payload.category
    assert spec["metaphor"] == "zap"
    assert spec["safe_zone"]["top_pct"] == 12


def test_layout_composer_uses_dedicated_visual_and_safe_headline_position():
    composer = LayoutComposer()
    signal = ContentSignal(
        id="mindset_growth",
        accent="purple_mindset",
        base_gradient="mindset_change",
        metaphor="brain",
        metaphor_placement="top-right",
        emotion_temperature="neutral",
        default_badge="思维跃迁",
        template_variant="cover_minimal",
    )
    theme = {
        "background_gradient_start": "#1a1632",
        "background_gradient_end": "#0d1020",
        "noise_opacity": 0.04,
        "grid_color": "rgba(255,255,255,0.04)",
        "orbs": [],
        "accent_color": "#b898ff",
        "accent_glow": "none",
    }

    spec = composer.compose(
        {
            "title": "自己定义成功",
            "visual_asset_path": "/tmp/dedicated-visual.png",
            "headline_position": "upper_left",
        },
        signal,
        theme,
    )

    assert spec["style_id"] == "mindset_growth"
    assert spec["has_visual_asset"] is True
    assert spec["headline_position"] == "upper_left"
    assert spec["show_metaphor"] is False

def test_cover_engine_e2e_mocked(temp_config_paths, tmp_path, monkeypatch):
    """
    Mock 渲染器以进行 Facade 全生命周期集成测试
    """
    rules_file, themes_file = temp_config_paths
    
    template_file = tmp_path / "cover.html.j2"
    template_file.write_text("<html>{{ title }}</html>", encoding="utf-8")
    
    metaphors_dir = tmp_path / "metaphors"
    metaphors_dir.mkdir()
    (metaphors_dir / "zap.svg").write_text("<svg>zap</svg>", encoding="utf-8")
    
    # 模拟 HTMLRenderer.render, 避免真正调用 Playwright 消耗资源和环境依赖
    renders = []
    def mock_render(self, layout_spec, output_path):
        renders.append((layout_spec, output_path))
        # 模拟生成输出图片文件
        Path(output_path).touch()
        
    from src.cover.renderer import HTMLRenderer
    monkeypatch.setattr(HTMLRenderer, "render", mock_render)
    
    engine = CoverEngine(
        rules_path=rules_file,
        themes_path=themes_file,
        template_path=template_file,
        metaphors_dir=metaphors_dir
    )
    
    payload = {
        "title": "谷歌CEO深度预测",
        "subtitle": "量子计算将如何重塑世界",
        "content_hints": ["quantum"]
    }
    output_img = tmp_path / "output_test_cover.jpg"
    
    engine.generate(payload, str(output_img))
    
    assert output_img.exists()
    assert len(renders) == 1
    layout_rendered = renders[0][0]
    assert layout_rendered["title"] == "谷歌CEO深度预测"
    assert layout_rendered["badge"] == "安全局势"  # 由 quantum 匹配的 policy_security default_badge
