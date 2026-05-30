"""
Alibaba Cloud CosyVoice Voice Cloning & Subtitle Synthesis Pipeline

Modification History:
- 2026-05-30: Gemini_3.5_Flash_planning: Created full cloning, subtitle synthesis, and mixing pipeline.
- 2026-05-30: Gemini_3.5_Flash_planning: Upgraded to use local Aliyun OSS signed URLs for fully automated zero-shot voice cloning.
"""

import os
import re
import time
import subprocess
import oss2
import dashscope
from dotenv import load_dotenv
from dashscope.audio.tts_v2 import VoiceEnrollmentService, SpeechSynthesizer

# Load environment variables
load_dotenv()

# Configure dashscope API key
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "sk-d2d0ca986de94c47990a3015bb585f7c")

MODEL_NAME = "cosyvoice-v3-plus"  # High-quality model (use "cosyvoice-v3-flash" for low-latency)
SOURCE_VIDEO = "output/XcSdPK5Xwbk.mp4"
ASS_FILE = "output/XcSdPK5Xwbk.ass"
REF_AUDIO = "scratch/denzel_ref.wav"
TEMP_DIR = "scratch/temp_cosyvoice"
FINAL_AUDIO_PURE = f"output/XcSdPK5Xwbk_cosyvoice_plus_zh_pure.mp3"
FINAL_VIDEO_PURE = f"output/XcSdPK5Xwbk_cosyvoice_plus_zh_pure.mp4"
FINAL_VIDEO_MIXED = f"output/XcSdPK5Xwbk_cosyvoice_plus_zh_mixed.mp4"

# OSS Configuration
OSS_KEY_ID = os.getenv("OSS_ACCESS_KEY_ID")
OSS_KEY_SECRET = os.getenv("OSS_ACCESS_KEY_SECRET")
OSS_BUCKET = os.getenv("OSS_BUCKET_NAME")
OSS_ENDPOINT = os.getenv("OSS_ENDPOINT", "oss-cn-beijing.aliyuncs.com")

def parse_time(time_str):
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def clean_text(text):
    text = re.sub(r'\{[^}]*\}', '', text)
    text = text.replace(r'\N', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_subtitles():
    print(f"Parsing subtitles from {ASS_FILE}...")
    if not os.path.exists(ASS_FILE):
        print(f"Error: {ASS_FILE} does not exist.")
        return []
        
    segments = []
    with open(ASS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("Dialogue:"):
                continue
            
            parts = line.split(',', 9)
            if len(parts) < 10:
                continue
                
            start_str = parts[1].strip()
            end_str = parts[2].strip()
            text_raw = parts[9].strip()
            
            start_time = parse_time(start_str)
            end_time = parse_time(end_str)
            
            # Extract Chinese part
            if r"{\fs50" in text_raw:
                zh_part = text_raw.split(r"{\fs50")[0]
            elif r"\N{\fs50" in text_raw:
                zh_part = text_raw.split(r"\N{\fs50")[0]
            else:
                zh_part = text_raw
                
            zh_cleaned = clean_text(zh_part)
            # Remove all spaces for Chinese text to prevent synthesis hallucinations
            zh_cleaned = zh_cleaned.replace(" ", "")
            
            if not zh_cleaned or not any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in zh_cleaned):
                continue
                
            segments.append({
                "start": start_time,
                "end": end_time,
                "text": zh_cleaned,
                "start_str": start_str,
                "end_str": end_str
            })
            
    print(f"Found {len(segments)} segments.")
    return segments

def get_or_create_voice_id():
    # If the user has configured OSS credentials, dynamically upload and enroll
    if OSS_KEY_ID and OSS_KEY_SECRET and OSS_BUCKET:
        print("\n[OSS] Uploading reference audio to your private bucket...")
        try:
            # 1. Upload to OSS
            auth = oss2.Auth(OSS_KEY_ID, OSS_KEY_SECRET)
            endpoint_url = f"https://{OSS_ENDPOINT}"
            bucket = oss2.Bucket(auth, endpoint_url, OSS_BUCKET)
            bucket.put_object_from_file("denzel_ref.wav", REF_AUDIO)
            print("  Upload successful!")
            
            # 2. Generate signed HTTPS URL
            print("  Generating signed HTTPS URL...")
            signed_url = bucket.sign_url('GET', "denzel_ref.wav", 300)
            
            # 3. Enroll voice via DashScope
            print("  Enrolling voice with prefix 'denzeloss'...")
            service = VoiceEnrollmentService()
            voice_id = service.create_voice(
                target_model=MODEL_NAME,
                prefix="denzelplus",
                url=signed_url
            )
            print(f"  Successfully Enrolled! Voice ID: {voice_id}")
            
            # [Gemini_3.5_Flash_planning] Automatically delete the temporary file from OSS bucket to avoid storage accumulation
            try:
                print("  Deleting temporary reference audio from OSS bucket...")
                bucket.delete_object("denzel_ref.wav")
                print("  OSS file deleted successfully.")
            except Exception as delete_error:
                print(f"  Failed to delete temporary OSS file: {delete_error}")
                
            return voice_id
        except Exception as e:
            print(f"  OSS Enrollment flow failed: {e}")
            print("  Falling back to previously generated voice ID...")
    else:
        print("\n[Config] OSS credentials not fully set in .env. Using fallback voice ID.")

    # Fallback/default Voice ID (Pre-enrolled on cosyvoice-v3-plus)
    return "cosyvoice-v3-plus-denzelplus-c7830e95a436407898127a767579600c"

def run_cosyvoice_clone_demo():
    print("=== Alibaba Cloud CosyVoice Voice Cloning & Synthesis ===")
    
    # 1. Extract reference audio from original video if not exists
    if not os.path.exists(REF_AUDIO):
        print("\nExtracting reference audio from video...")
        cmd = [
            "ffmpeg", "-y", "-i", SOURCE_VIDEO,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            REF_AUDIO
        ]
        try:
            subprocess.run(cmd, check=True)
            print("Audio extracted successfully.")
        except Exception as e:
            print(f"FFmpeg extraction failed: {e}")
            return

    # 2. Get or Enroll Voice ID
    voice_id = get_or_create_voice_id()
    print(f"Using Voice ID for synthesis: {voice_id}")
    
    # 3. Parse subtitles
    print("\n[1/4] Parsing subtitles...")
    segments = parse_subtitles()
    if not segments:
        print("No dialogue segments found.")
        return
        
    for idx, seg in enumerate(segments):
        print(f"  Segment #{idx+1} [{seg['start_str']} -> {seg['end_str']}]: {seg['text']}")
        
    # 4. Synthesize each Mandarin segment
    print("\n[2/4] Synthesizing Mandarin audio segments via CosyVoice...")
    os.makedirs(TEMP_DIR, exist_ok=True)
    input_files = []
    filter_complex_parts = []
    amix_inputs = []
    
    for idx, seg in enumerate(segments):
        seg_file = os.path.join(TEMP_DIR, f"seg_{idx}.mp3")
        input_files.append(seg_file)
        
        print(f"  [{idx+1}/{len(segments)}] Synthesizing text: '{seg['text']}'")
        try:
            synthesizer = SpeechSynthesizer(model=MODEL_NAME, voice=voice_id)
            audio_data = synthesizer.call(seg['text'])
            with open(seg_file, "wb") as f:
                f.write(audio_data)
        except Exception as e:
            print(f"  Synthesis failed for segment {idx}: {e}")
            return
            
        # Align segments on the timeline
        delay_ms = int(seg['start'] * 1000)
        filter_complex_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[a{idx}]")
        amix_inputs.append(f"[a{idx}]")

    # 5. Stitch and mix segments using FFmpeg
    print("\n[3/4] Aligning and stitching segments into single track...")
    filter_complex_str = "; ".join(filter_complex_parts)
    amix_str = f"{''.join(amix_inputs)}amix=inputs={len(segments)}:normalize=0[out]"
    full_filter_complex = f"{filter_complex_str}; {amix_str}"
    
    ffmpeg_mix_cmd = ["ffmpeg", "-y"]
    for f in input_files:
        ffmpeg_mix_cmd.extend(["-i", f])
    ffmpeg_mix_cmd.extend(["-filter_complex", full_filter_complex, "-map", "[out]", FINAL_AUDIO_PURE])
    
    try:
        subprocess.run(ffmpeg_mix_cmd, check=True)
        print(f"  Pure Mandarin audio track saved to: {FINAL_AUDIO_PURE}")
    except Exception as e:
        print(f"  FFmpeg mixing failed: {e}")
        return

    # 6. Assemble output videos
    print("\n[4/4] Assembling final dubbed video outputs...")
    
    # Version A: Pure cloned voice track (No background music / English vocal)
    print(f"  Creating pure Mandarin dubbed video ({FINAL_VIDEO_PURE})...")
    ffmpeg_merge_pure = [
        "ffmpeg", "-y", "-i", SOURCE_VIDEO, "-i", FINAL_AUDIO_PURE,
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-shortest",
        FINAL_VIDEO_PURE
    ]
    try:
        subprocess.run(ffmpeg_merge_pure, check=True)
        print(f"    Saved: {FINAL_VIDEO_PURE} (Size: {os.path.getsize(FINAL_VIDEO_PURE)} bytes)")
    except Exception as e:
        print(f"    Pure merge failed: {e}")
        
    # Version B: Mixed track with ducked original audio (Maintains background music, ducks English vocals)
    print(f"  Creating mixed Mandarin dubbed video with ducked BGM ({FINAL_VIDEO_MIXED})...")
    ffmpeg_merge_mixed = [
        "ffmpeg", "-y", "-i", SOURCE_VIDEO, "-i", FINAL_AUDIO_PURE,
        "-filter_complex", "[0:a]volume=0.12[bg]; [1:a]volume=1.0[fg]; [bg][fg]amix=inputs=2:normalize=0[outa]",
        "-map", "0:v:0", "-map", "[outa]", "-c:v", "copy", "-c:a", "aac", "-shortest",
        FINAL_VIDEO_MIXED
    ]
    try:
        subprocess.run(ffmpeg_merge_mixed, check=True)
        print(f"    Saved: {FINAL_VIDEO_MIXED} (Size: {os.path.getsize(FINAL_VIDEO_MIXED)} bytes)")
    except Exception as e:
        print(f"    Mixed merge failed: {e}")

    print("\n=== Alibaba Cloud CosyVoice Dubbing Pipeline Finished ===")

if __name__ == "__main__":
    run_cosyvoice_clone_demo()
