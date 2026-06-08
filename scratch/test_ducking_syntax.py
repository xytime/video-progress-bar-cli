import subprocess
import imageio_ffmpeg

ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

# We will run a simple dry run of ffmpeg using faked inputs or just validating the filter complex syntax with -f null
# cmd: ffmpeg -f lavfi -i anullsrc -filter_complex "[0:a]volume='if(between(t,1,2)+between(t,4,5),0.1,1.0)':eval=frame[out]" -map "[out]" -f null -t 10 -
cmd = [
    ffmpeg_exe, "-y",
    "-f", "lavfi",
    "-i", "anullsrc=r=44100:cl=stereo",
    "-filter_complex", "[0:a]volume='if(between(t,1,2)+between(t,4,5),0.1,1.0)':eval=frame[out]",
    "-map", "[out]",
    "-f", "null",
    "-t", "10",
    "-"
]

res = subprocess.run(cmd, capture_output=True)
print("Exit code:", res.returncode)
if res.returncode != 0:
    print("Stderr:", res.stderr.decode())
else:
    print("Filter syntax is valid!")
