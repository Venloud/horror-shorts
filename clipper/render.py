"""Render a vertical split-screen video, preserving only source audio."""
import argparse
import json
import subprocess
from pathlib import Path

def run(*args):
    subprocess.run(list(map(str,args)),check=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--background",required=True)
    p.add_argument("--start",type=float,default=0)
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--output",default="clipper/output/tiktok.mp4")
    p.add_argument("--subtitles",default="",help="Optional ASS or SRT caption file")
    a=p.parse_args()
    if a.start<0 or not 1<=a.duration<=59:p.error("Invalid start or duration")
    src=Path(a.source)
    bg=Path(a.background)
    if not src.is_file() or not bg.is_file():p.error("Source and background must be local files")
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    filters=("[0:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[top];"
             "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[bottom];"
             "[top][bottom]vstack=inputs=2,format=yuv420p[video]")
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",str(a.start),"-t",str(a.duration),"-i",str(src),
         "-i",str(bg),"-filter_complex",filters,"-map","[video]","-map","0:a:0?",
         "-c:v","libx264","-preset","veryfast","-crf","23","-r","30",
         "-c:a","aac","-b:a","128k","-movflags","+faststart","-t",str(a.duration)]
    if a.subtitles:
        s=Path(a.subtitles).resolve()
        if not s.is_file():p.error(f"Missing captions: {s}")
        tmp=out.with_name("pre_captions.mp4")
        run(*(cmd+[str(tmp)]))
        # ASS specifies exact positioning and word-by-word animation.
        escaped=s.as_posix().replace(":","\\:").replace("'","\\'")
        run("ffmpeg","-hide_banner","-loglevel","error","-y","-i",str(tmp),
            "-vf",f"subtitles='{escaped}'","-c:v","libx264","-preset","veryfast",
            "-crf","23","-c:a","copy","-movflags","+faststart",str(out))
        tmp.unlink()
    else:run(*(cmd+[str(out)]))
    print(json.dumps({"output":str(out),"duration_requested":a.duration,"source":str(src)}))

if __name__=="__main__":main()
