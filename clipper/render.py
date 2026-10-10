"""Render a sub-60-second split-screen TikTok from local or YouTube source media."""
import argparse
import json
import subprocess
from pathlib import Path

def run(*args):
    subprocess.run(list(map(str,args)), check=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",default="https://youtu.be/plN7JMbadRg")
    p.add_argument("--background",required=True,help="Local MP4 of footage you can reuse")
    p.add_argument("--start",type=float,default=0)
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--output",default="clipper/output/tiktok.mp4")
    p.add_argument("--subtitles",default="",help="Optional SRT file for burned captions")
    a=p.parse_args()
    if not 0 <= a.start or not 1 <= a.duration <= 59:
        p.error("Start must be nonnegative and duration must be 1-59 seconds")
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    src=Path(a.source)
    if not src.is_file():
        src=out.parent/"source.mp4"
        run("yt-dlp","--no-playlist","-f","bv*+ba/b","--merge-output-format","mp4","-o",str(src),a.source)
    bg=Path(a.background)
    if not bg.is_file():p.error(f"Background not found: {bg}")
    # Crop each source to a 1080x960 panel, preserving aspect ratio.
    filters=("[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[top];"
             "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[bottom];"
             "[top][bottom]vstack=inputs=2,format=yuv420p[video]")
    cmd=["ffmpeg","-y","-ss",str(a.start),"-t",str(a.duration),"-i",str(src),
         "-stream_loop","-1","-t",str(a.duration),"-i",str(bg),
         "-filter_complex",filters,"-map","[video]","-map","0:a:0?",
         "-c:v","libx264","-preset","veryfast","-crf","23","-r","30",
         "-c:a","aac","-b:a","128k","-movflags","+faststart","-shortest",str(out)]
    if a.subtitles:
        s=Path(a.subtitles).resolve()
        if not s.is_file():p.error(f"Subtitles not found: {s}")
        # Burn subtitles in a second pass to keep optional subtitle handling simple.
        tmp=out.with_name("pre_captions.mp4")
        cmd[-1]=str(tmp)
        run(*cmd)
        run("ffmpeg","-y","-i",str(tmp),"-vf",f"subtitles={s.as_posix()}:force_style='FontSize=20,Alignment=5,Outline=2'",
            "-c:v","libx264","-preset","veryfast","-crf","23","-c:a","copy",str(out))
        tmp.unlink()
    else:run(*cmd)
    print(json.dumps({"output":str(out),"duration_requested":a.duration,"source":a.source}))

if __name__=="__main__":main()
