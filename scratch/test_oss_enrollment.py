import os
import oss2
import dashscope
from dotenv import load_dotenv
from dashscope.audio.tts_v2 import VoiceEnrollmentService

# Load environment variables
load_dotenv()

# Get OSS credentials
OSS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID")
OSS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET")
OSS_BUCKET = os.getenv("OSS_BUCKET_NAME")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")

# Get DashScope credentials
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")

def test_oss_enrollment():
    print("=== Testing CosyVoice Enrollment via Alibaba Cloud OSS Signed URL ===")
    print(f"Bucket: {OSS_BUCKET}")
    print(f"Endpoint: {OSS_ENDPOINT}")
    
    local_file = "scratch/denzel_ref.wav"
    object_name = "denzel_ref.wav"
    
    # 1. Upload file to OSS
    print("\n[1/3] Uploading reference audio to OSS...")
    try:
        # Connect to OSS
        auth = oss2.Auth(OSS_KEY_ID, OSS_KEY_SECRET)
        # Use https endpoint
        endpoint_url = f"https://{OSS_ENDPOINT}"
        bucket = oss2.Bucket(auth, endpoint_url, OSS_BUCKET)
        
        # Upload
        print(f"Uploading {local_file} as {object_name}...")
        bucket.put_object_from_file(object_name, local_file)
        print("Upload successful!")
    except Exception as e:
        print(f"OSS Upload failed: {e}")
        return

    # 2. Generate signed URL
    print("\n[2/3] Generating signed URL (valid for 300s)...")
    try:
        # Generate GET signed URL (V1 signature)
        signed_url = bucket.sign_url('GET', object_name, 300)
        print(f"Signed URL: {signed_url}")
    except Exception as e:
        print(f"Failed to generate signed URL: {e}")
        return

    # 3. Enroll voice using the signed URL
    print("\n[3/3] Enrolling voice with DashScope...")
    try:
        service = VoiceEnrollmentService()
        voice_id = service.create_voice(
            target_model="cosyvoice-v3-flash",
            prefix="denzeloss",
            url=signed_url
        )
        print(f"\nSuccess! Voice enrolled via OSS signed URL!")
        print(f"Enrolled Voice ID: {voice_id}")
        return voice_id
    except Exception as e:
        print(f"Voice enrollment failed: {e}")
        return None

if __name__ == "__main__":
    test_oss_enrollment()
