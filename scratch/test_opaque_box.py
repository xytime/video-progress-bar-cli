# -*- coding: utf-8 -*-
"""[Gemini_3.5_Flash_planning] Run demo generation to test opaque background box subtitles on vertical video."""
import sys
import os
from pathlib import Path

# Adjust path to import src
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from video_processing.processors.vertical_processor import VerticalCaptionProcessor

def main():
    input_video = Path("XcSdPK5Xwbk.mp4")
    if not input_video.exists():
        print(f"❌ Input video {input_video} not found!")
        return

    output_video = Path("output_vertical_demo.mp4")
    
    print("🚀 Initializing VerticalCaptionProcessor...")
    processor = VerticalCaptionProcessor(
        input_path=input_video,
        output_path=output_video,
        style="default",
        title="Opaque Box Demo Title",
        bilingual=True,
        font_size=84,
    )
    
    # We can create some dummy segments to burn in
    segments = [
        {
            "start": 0.0,
            "end": 3.0,
            "text": "Your willingness to bet on yourself when no one else would was the point.",
            "zh_text": "当别人不愿意赌自己时，你愿意赌自己，这才是重点。"
        },
        {
            "start": 3.0,
            "end": 6.0,
            "text": "Keep moving forward and believe in your vision.",
            "zh_text": "继续前进，并坚信你的愿景。"
        }
    ]
    
    print("🔥 Generating ASS subtitle file...")
    ass_path = processor._generate_ass_file(segments)
    print(f"✅ Generated ASS file: {ass_path}")
    
    print("🔥 Burning subtitles (and creating vertical layout)...")
    final_output = processor._burn_subtitles(ass_path)
    print(f"🎉 Completed! Output video saved to: {final_output}")

if __name__ == "__main__":
    main()
