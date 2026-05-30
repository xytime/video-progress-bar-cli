import os
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")
VOICE_ID = "cosyvoice-v3-flash-denzel-5452c7a4407c46119ef096d9860711ff"

def test_single():
    print("Testing segment 2 fixed synthesis...")
    try:
        synthesizer = SpeechSynthesizer(model="cosyvoice-v3-flash", voice=VOICE_ID)
        audio = synthesizer.call("我们越闪耀，我们吸引的美好事物就越多。")
        print(f"Success! Audio size: {len(audio)} bytes")
        with open("scratch/temp_cosyvoice/seg_2_fixed.mp3", "wb") as f:
            f.write(audio)
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_single()
