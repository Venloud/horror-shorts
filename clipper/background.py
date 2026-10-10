"""Build a muted bottom-half montage switching footage every ten seconds."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

RELEASE="https://github.com/Venloud/horror-shorts/releases/download/clipper-assets-v1/"
ASSETS=["Spicy.Sauce_JlPEb6WNuDI.mp4"]+[
    f"asmraiworks_{i}.mp4" for i in (
        "7516045075013438750","7516993127152930078",
        "7517745929076657438","7518977293922946334",
        "7513729190873566494","7514392818035559710",
        "7514577060442983710","7514771161729764638",
        "7515588571940539678")]

def run(args):
    subprocess.run([str(x) for x in args],check=True)

def build(asset_dir,output,duration,segment_seconds=10,offset=0):
    paths=[Path(asset_dir)/name for name in ASSETS]
    missing=[p.name for p in paths if not p.is_file()]
    if missing:raise FileNotFoundError(f"Missing background assets: {missing}")
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        d=Path(td)
        chunks=[]
        remaining=duration
        index=offset%len(paths)
        while remaining>0.001:
            seconds=min(segment_seconds,remaining)
            src=paths[index%len(paths)]
            chunk=d/f"part_{len(chunks):03d}.ts"
            # Stream-loop short ASMR videos; discard their audio.
            run(["ffmpeg","-hide_banner","-loglevel","error","-y","-stream_loop","-1",
                 "-i",src,"-t",f"{seconds:.3f}","-an","-vf",
                 "fps=30,scale=540:480:force_original_aspect_ratio=increase,crop=540:480,setsar=1",
                 "-c:v","libx264","-preset","ultrafast","-crf","27",
                 "-pix_fmt","yuv420p","-f","mpegts",chunk])
            chunks.append(chunk)
            remaining-=seconds
            index+=1
        listing=d/"concat.txt"
        listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in chunks))
        run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","concat",
             "-safe","0","-i",listing,"-an","-c","copy","-bsf:a","aac_adtstoasc",
             "-movflags","+faststart",output])
    print(json.dumps({"background":str(output),"segment_seconds":segment_seconds,
                      "segments":len(chunks),"source_order":[paths[(offset+i)%len(paths)].name for i in range(len(chunks))]}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--assets-dir",required=True)
    p.add_argument("--output",default="/tmp/clipper_background.mp4")
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--offset",type=int,default=0)
    a=p.parse_args()
    if not 1<=a.duration<=59:p.error("Duration must be 1-59 seconds")
    build(a.assets_dir,a.output,a.duration,offset=a.offset)

if __name__=="__main__":main()
