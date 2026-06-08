import os
import oss2
import dashscope
from dotenv import load_dotenv
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer

# Load environment variables
load_dotenv()

# Get OSS credentials
OSS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID")
OSS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET")
OSS_BUCKET = os.getenv("OSS_BUCKET_NAME")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")

# Get DashScope credentials
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

def test_plus():
    print("=== Testing CosyVoice v3 Plus (High Quality Model) ===")
    local_file = "scratch/denzel_ref.wav"
    object_name = "denzel_ref_plus.wav"
    
    # 1. Upload to OSS
    try:
        auth = oss2.Auth(OSS_KEY_ID, OSS_KEY_SECRET)
        bucket = oss2.Bucket(auth, f"https://{OSS_ENDPOINT}", OSS_BUCKET)
        bucket.put_object_from_file(object_name, local_file)
        print("Upload successful!")
    except Exception as e:
        print(f"OSS Upload failed: {e}")
        return

    # 2. Sign URL
    signed_url = bucket.sign_url('GET', object_name, 300)
    print(f"Signed URL generated.")

    # 3. Enroll voice using target model "cosyvoice-v3-plus"
    try:
        service = VoiceEnrollmentService()
        voice_id = service.create_voice(
            target_model="cosyvoice-v3-plus",
            prefix="denzelplus",
            url=signed_url
        )
        print(f"Voice enrolled successfully! Voice ID: {voice_id}")
    except Exception as e:
        print(f"Voice enrollment failed: {e}")
        # Clean up
        bucket.delete_object(object_name)
        return

    # 4. Delete OSS file immediately after enrollment
    bucket.delete_object(object_name)
    print("OSS temporary file deleted.")

    # 5. Synthesize segment 0
    print("\nSynthesizing test segment via cosyvoice-v3-plus...")
    try:
        synthesizer = SpeechSynthesizer(model="cosyvoice-v3-plus", voice=voice_id)
        audio = synthesizer.call("每天早上告诉自己今天将是美好的一天。")
        output_file = "scratch/temp_cosyvoice/seg_0_plus.mp3"
        with open(output_file, "wb") as f:
            f.write(audio)
        print(f"Synthesis successful! Saved to {output_file}")
    except Exception as e:
        print(f"Synthesis failed: {e}")

if __name__ == "__main__":
    test_plus()
