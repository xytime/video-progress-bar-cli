#!/bin/bash
cd /Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing/output

echo "Waiting for any existing ffmpeg process to finish..."
while pgrep -x "ffmpeg" > /dev/null || pgrep -f "python -m cli.main auto-caption" > /dev/null; do
    sleep 5
done

echo "Downloading Video 3: Eric Schmidt (Retry with Safari)..."
yt-dlp --no-check-certificate --cookies-from-browser safari -f "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best" "https://youtu.be/tNH43a1EI7s" -o "Schmidt_Speech.%(ext)s"

cd ..
EXT=$(ls output/Schmidt_Speech.* | head -n 1 | awk -F. '{print $NF}')
echo "Processing Video 3: Eric Schmidt..."
python -m cli.main auto-caption output/Schmidt_Speech.$EXT --vertical --style tech_blue --bilingual --title "谷歌前CEO埃里克·施密特毕业演讲大谈AI惨遭嘘声" > output/schmidt_process.log 2>&1

echo "Render complete for Schmidt."
