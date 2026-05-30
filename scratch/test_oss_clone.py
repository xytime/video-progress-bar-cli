import os
import dashscope
from dashscope.audio.tts_v2 import VoiceEnrollmentService
from dashscope.utils.oss_utils import OssUtils

# Configure dashscope API key
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")

def test_clone():
    print("=== Testing CosyVoice Voice Enrollment with oss:// URL ===")
    ref_audio = "scratch/denzel_ref.wav"
    
    # 1. Extract audio if not exists
    if not os.path.exists(ref_audio):
        print("Extracting audio from video...")
        import subprocess
        cmd = [
            "ffmpeg", "-y", "-i", "output/XcSdPK5Xwbk.mp4",
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            ref_audio
        ]
        subprocess.run(cmd, check=True)
        print("Audio extracted successfully.")
        
    # 2. Upload file to DashScope temporary OSS storage using OssUtils
    print("Uploading reference audio to DashScope temporary OSS...")
    try:
        # OssUtils.upload returns (file_url, upload_certificate)
        oss_url, _ = OssUtils.upload(
            model="cosyvoice-v3-flash",
            file_path=ref_audio,
            api_key=dashscope.api_key
        )
        print(f"OSS URL: {oss_url}")
    except Exception as e:
        print(f"OSS upload failed: {e}")
        return
        
    # 3. Create Custom Voice
    print("Enrolling voice using oss:// url...")
    try:
        service = VoiceEnrollmentService()
        voice_id = service.create_voice(
            target_model="cosyvoice-v3-flash",
            prefix="denzel",
            url=oss_url
        )
        print(f"Voice enrolled successfully! Voice ID: {voice_id}")
        return voice_id
    except Exception as e:
        print(f"Voice enrollment failed: {e}")
        return None

if __name__ == "__main__":
    test_clone()
