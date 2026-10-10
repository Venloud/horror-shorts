"""Offline smoke test for split-screen rendering and highlight selection."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from highlights import pick, stamp

def call(*args):
    subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

def test():
    assert stamp(61.234)=="00:01:01,234"
    segments=[{"start":0,"end":3,"text":"intro"},{"start":4,"end":8,"text":"how to win a million challenge"}]
    assert pick(segments,3.5)==4.0
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp)
        for name,color in [("top","red"),("bottom","blue")]:
            call("ffmpeg","-y","-f","lavfi","-i",f"color=c={color}:s=320x240:r=12:d=2",
                 "-c:v","mpeg4",str(d/f"{name}.mp4"))
        srt=d/"test.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,500\nTEST CAPTION\n")
        out=d/"test.mp4"
        call(sys.executable,str(Path(__file__).with_name("render.py")),
             "--source",str(d/"top.mp4"),"--background",str(d/"bottom.mp4"),
             "--duration","1.5","--subtitles",str(srt),"--output",str(out))
        info=json.loads(subprocess.check_output(["ffprobe","-v","error","-show_entries",
            "stream=width,height:format=duration","-of","json",str(out)]))
        video=next(x for x in info["streams"] if "width" in x)
        assert (video["width"],video["height"])==(1080,1920)
        assert 1<=float(info["format"]["duration"])<2
        print("Smoke test passed",info["format"]["duration"])
if __name__=="__main__":test()
