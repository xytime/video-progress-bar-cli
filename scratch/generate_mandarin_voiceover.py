import os
import re
import requests
import subprocess

API_KEY = "sk_27f394c51585c2245abe5e45f82b34584fb049995c62f9de"
VOICE_ID = "XrExE9yKIg1WjnnlVkGX"  # Matilda (Premade)
ASS_FILE = "output/jMCVK7NcFLA.ass"
TEMP_DIR = "scratch/temp_audio"
OUTPUT_FILE = os.path.expanduser("~/Downloads/Buy_Now_Pay_Later_Scam_Mandarin_Matilda.mp3")

def parse_time(time_str):
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = float(parts[2])
    return h * 3600 + m * 60 + s

def clean_text(text):
    # Remove tags inside {...}
    text = re.sub(r'\{[^}]*\}', '', text)
    # Replace \N with space or empty
    text = text.replace(r'\N', ' ')
    # Clean multiple spaces
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
            
            # Filter first 2 minutes (120 seconds)
            if start_time >= 120.0:
                continue
                
            # Extract Chinese part (before {\fs50)
            if r"{\fs50" in text_raw:
                zh_part = text_raw.split(r"{\fs50")[0]
            elif r"\N{\fs50" in text_raw:
                zh_part = text_raw.split(r"\N{\fs50")[0]
            else:
                zh_part = text_raw
                
            zh_cleaned = clean_text(zh_part)
            
            # Skip empty entries or entries without alphanumeric/Chinese characters
            if not zh_cleaned or not any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in zh_cleaned):
                continue
                
            segments.append({
                "start": start_time,
                "end": end_time,
                "text": zh_cleaned,
                "start_str": start_str,
                "end_str": end_str
            })
            
    print(f"Found {len(segments)} segments under 120s.")
    return segments

def generate_voiceover(dry_run=False):
    segments = parse_subtitles()
    if not segments:
        print("No segments found.")
        return
        
    print("\n--- Dialogue Segments to Synthesize ---")
    for idx, seg in enumerate(segments):
        print(f"#{idx+1} [{seg['start_str']} -> {seg['end_str']}] ({seg['start']}s): {seg['text']}")
        
    if dry_run:
        print("\nDry run completed. No API calls made.")
        return
        
    # 2. Call ElevenLabs TTS API
    print(f"\nCreating temp directory: {TEMP_DIR}")
    os.makedirs(TEMP_DIR, exist_ok=True)
    
    headers = {
        "xi-api-key": API_KEY,
        "Content-Type": "application/json"
    }
    
    input_files = []
    filter_complex_parts = []
    amix_inputs = []
    
    for idx, seg in enumerate(segments):
        seg_file = os.path.join(TEMP_DIR, f"seg_{idx}.mp3")
        input_files.append(seg_file)
        
        # Call API if file doesn't exist
        if not os.path.exists(seg_file):
            print(f"[{idx+1}/{len(segments)}] Synthesizing: {seg['text']}")
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
            data = {
                "text": seg['text'],
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75
                }
            }
            try:
                response = requests.post(url, headers=headers, json=data)
                if response.status_code == 200:
                    with open(seg_file, "wb") as f:
                        f.write(response.content)
                else:
                    print(f"Error synthesizing segment {idx}: {response.text}")
                    return
            except Exception as e:
                print(f"Exception during synthesis of segment {idx}: {e}")
                return
        else:
            print(f"[{idx+1}/{len(segments)}] Audio segment already exists, skipping API call.")
            
        # Compile FFmpeg filters
        delay_ms = int(seg['start'] * 1000)
        filter_complex_parts.append(f"[{idx}:a]adelay={delay_ms}|{delay_ms}[a{idx}]")
        amix_inputs.append(f"[a{idx}]")

    # 3. Combine using FFmpeg
    print(f"\nStitching audio segments with FFmpeg complex filters...")
    filter_complex_str = "; ".join(filter_complex_parts)
    amix_str = f"{''.join(amix_inputs)}amix=inputs={len(segments)}:normalize=0[out]"
    full_filter_complex = f"{filter_complex_str}; {amix_str}"
    
    ffmpeg_cmd = ["ffmpeg", "-y"]
    for f in input_files:
        ffmpeg_cmd.extend(["-i", f])
    ffmpeg_cmd.extend(["-filter_complex", full_filter_complex, "-map", "[out]", OUTPUT_FILE])
    
    print("Running FFmpeg mixing command...")
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        print(f"\nMandarin voiceover successfully generated!")
        print(f"Output saved to: {OUTPUT_FILE}")
        print(f"File size: {os.path.getsize(OUTPUT_FILE)} bytes")
        
        # Verify duration
        verify_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration", 
            "-of", "default=noprint_wrappers=1:nokey=1", OUTPUT_FILE
        ]
        duration_res = subprocess.check_output(verify_cmd).decode('utf-8').strip()
        print(f"Verified Duration: {duration_res} seconds")
        
    except Exception as e:
        print(f"Error during FFmpeg mixing: {e}")

if __name__ == "__main__":
    # First do a quick dry-run check or run directly
    generate_voiceover(dry_run=False)
