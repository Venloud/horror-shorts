"""Create varied, rotating 40% screen ADHD footage for TikTok clips."""
import argparse
import hashlib
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

def plan(duration, offset=0):
    """Alternate ASMR and Minecraft, changing the first type every run."""
    t=0.0
    block=0
    minecraft_first=(offset % 2 == 1)
    while t < duration-0.001:
        minecraft=(block % 2 == 0) if minecraft_first else (block % 2 == 1)
        length=10 if block==0 else (15 if minecraft else 20)
        length=min(length,duration-t)
        name=MINECRAFT if minecraft else ASMR[(offset//2+block//2)%len(ASMR)]
        yield name,length,t
        t+=length
        block+=1


def _source_duration(path):
    raw=subprocess.check_output(["ffprobe","-v","error","-show_entries",
        "format=duration","-of","default=noprint_wrappers=1:nokey=1",str(path)],
        text=True).strip()
    seconds=float(raw)
    if not math.isfinite(seconds) or seconds<=0:
        raise RuntimeError(f"Invalid background duration: {path}")
    return seconds


def _seek_for(offset, block, filename, video_duration, block_duration):
    """Reproducible seek position, independent for each run and segment."""
    available=max(0.0,video_duration-block_duration-0.5)
    if available<=0:
        return 0.0
    digest=hashlib.blake2b(f"{offset}:{block}:{filename}".encode(),
        digest_size=8).digest()
    fraction=int.from_bytes(digest,"big")/(2**64-1)
    return round(available*fraction,3)


def build(asset_dir,output,duration,offset=0):
    root=Path(asset_dir)
    missing=[n for n in ASSETS if not (root/n).is_file()]
    if missing:raise FileNotFoundError(f"Missing: {missing}")
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    schedule=list(plan(duration,offset))
    lengths={name:_source_duration(root/name) for name,_,_ in schedule}
    details=[]
    with tempfile.TemporaryDirectory() as temp:
        d=Path(temp)
        parts=[]
        for i,(name,seconds,start) in enumerate(schedule):
            seek=_seek_for(offset,i,name,lengths[name],seconds)
            part=d/f"part_{i:03d}.ts"
            subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y",
                "-stream_loop","-1","-ss",f"{seek:.3f}","-i",str(root/name),
                "-t",f"{seconds:.3f}",
                "-an","-vf","fps=30,scale=540:480:force_original_aspect_ratio=increase,crop=540:480,setsar=1",
                "-c:v","libx264","-preset","ultrafast","-crf","27","-pix_fmt","yuv420p",
                "-f","mpegts",str(part)],check=True)
            parts.append(part)
            details.append({"file":name,"start":start,"duration":seconds,"source_offset":seek})
        listing=d/"concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        subprocess.run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat",
            "-safe","0","-i",str(listing),"-an","-c","copy","-movflags","+faststart",str(output)],check=True)
    print(json.dumps({"output":str(output),"rotation":offset,"schedule":details}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--assets-dir",required=True)
    p.add_argument("--output",default="/tmp/clipper_background.mp4")
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--offset",type=int,default=0)
    a=p.parse_args()
    if not 1<=a.duration<=120:p.error("Duration must be 1-120")
    build(a.assets_dir,a.output,a.duration,a.offset)

if __name__=="__main__":main()
