"""Create 40% screen ADHD footage: ASMR first, Minecraft at 10 seconds."""
import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path

RELEASE="https://github.com/Venloud/horror-shorts/releases/download/clipper-assets-v1/"
MINECRAFT="Spicy.Sauce_JlPEb6WNuDI.mp4"
ASMR=[f"asmraiworks_{x}.mp4" for x in (
    "7516045075013438750","7516993127152930078","7517745929076657438",
    "7518977293922946334","7513729190873566494","7514392818035559710",
    "7514577060442983710","7514771161729764638","7515588571940539678")]
ASSETS=[MINECRAFT]+ASMR

def plan(duration,offset=0):
    # First TikTok for 10s; subsequent Minecraft blocks 15s, TikTok blocks 20s.
    t=0.0
    block=0
    while t<duration-0.001:
        minecraft=block%2==1
        length=15 if minecraft else (10 if block==0 else 20)
        length=min(length,duration-t)
        name=MINECRAFT if minecraft else ASMR[(offset+block//2)%len(ASMR)]
        yield name,length,t
        t+=length
        block+=1

def build(asset_dir,output,duration,offset=0):
    root=Path(asset_dir)
    missing=[n for n in ASSETS if not (root/n).is_file()]
    if missing:raise FileNotFoundError(f"Missing: {missing}")
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    schedule=list(plan(duration,offset))
    with tempfile.TemporaryDirectory() as temp:
        d=Path(temp)
        parts=[]
        for i,(name,seconds,start) in enumerate(schedule):
            part=d/f"part_{i:03d}.ts"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                "-stream_loop","-1","-i",str(root/name),"-t",f"{seconds:.3f}",
                "-an","-vf","fps=30,scale=540:480:force_original_aspect_ratio=increase,crop=540:480,setsar=1",
                "-c:v","libx264","-preset","ultrafast","-crf","27","-pix_fmt","yuv420p",
                "-f","mpegts",str(part)],check=True)
            parts.append(part)
        listing=d/"concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat",
            "-safe","0","-i",str(listing),"-an","-c","copy","-movflags","+faststart",str(output)],check=True)
    print(json.dumps({"output":str(output),"schedule":[{"file":n,"start":t,"duration":s} for n,s,t in schedule]}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--assets-dir",required=True)
    p.add_argument("--output",default="/tmp/clipper_background.mp4")
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--offset",type=int,default=0)
    a=p.parse_args()
    if not 1<=a.duration<=60:p.error("Duration must be 1-60")
    build(a.assets_dir,a.output,a.duration,a.offset)

if __name__=="__main__":main()
