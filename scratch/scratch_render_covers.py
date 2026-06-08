import os
import sys
from pathlib import Path

# [Gemini_3.5_Flash_planning]
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.cover.engine import CoverEngine

def main():
    engine = CoverEngine()
    out_dir = PROJECT_ROOT / "output" / "test_cover_renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    test_cases = [
        {
            "name": "case_cover",
            "payload": {
                "title": "AI真能提效？华尔街泼来一盆冷水",
                "subtitle": "大语言模型的商业回报率受到严重质疑",
                "category": "科技",
                "content_hints": ["ai"],
                "content_label": "独家"
            }
        },
        {
            "name": "case_drama",
            "payload": {
                "title": "美对华制裁再度加码，地缘冲突一触即发",
                "subtitle": "半导体供应链将迎来最大重组风暴",
                "category": "财经",
                "content_hints": ["policy"],
                "content_label": "重磅"
            }
        },
        {
            "name": "case_minimal",
            "payload": {
                "title": "如何打破认知局限，实现人生的二次成长",
                "subtitle": "阻碍你前进的往往是那些最熟悉的经验",
                "category": "成长",
                "content_hints": ["mindset"],
                "content_label": "最新"
            }
        }
    ]

    print("Generating cover images at 6:7 ratio...")
    
    for tc in test_cases:
        name = tc["name"]
        payload = tc["payload"]
        
        # 1. 正常的 6:7 生成
        out_6_7 = out_dir / f"{name}_6_7.jpg"
        print(f"Rendering {name} (6:7) -> {out_6_7.name}")
        engine.generate(payload, str(out_6_7))
            
    print("Done! Check output/test_cover_renders/")

if __name__ == "__main__":
    main()
