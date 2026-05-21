#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg or python process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 7: Nvidia CEO on China..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://youtu.be/5cIINWjQ0Pg" -o "Huang_China.%(ext)s"

cd ..
EXT=$(ls output/Huang_China.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 7: Nvidia CEO on China..."
python -m cli.main auto-caption output/Huang_China.$EXT --vertical --style tech_blue --bilingual --title "黄仁勋谈中国市场：建议投资者降低预期" > output/huang_china_process.log 2>&1

echo "Render complete for Huang_China."
