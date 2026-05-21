#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

# Wait for any existing ffmpeg to finish to avoid high CPU usage
while pgrep -x "ffmpeg" > /dev/null; do
    echo "Waiting for existing ffmpeg process to finish..."
    sleep 5
done

FFMPEG_EXE="/Users/ryusei/.pyenv/versions/3.12.4/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"

echo "Starting render for Huang_Speech..."
$FFMPEG_EXE -y -i Huang_Speech.mp4 -filter_complex "[0:v]scale=1080:607[fg];[fg]pad=1080:1920:0:350:black[merged];[merged]drawtext=text='黄仁勋 CMU 2026 毕业演讲：奔跑吧...':fontcolor=#FFFF00:fontsize=60:x=(w-text_w)/2:y=150:fontfile='/Library/Fonts/Arial Unicode.ttf':box=1:boxcolor=#000032@0.71:boxborderw=20[titled];[titled]ass='Huang_Speech.ass'[out]" -map "[out]" -map 0:a -c:v libx264 -c:a aac Huang_Speech_vertical.mp4

echo "Render complete."
