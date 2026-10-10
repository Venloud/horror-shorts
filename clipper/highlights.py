"""Find an engaging short excerpt using word-timed transcription; write synced SRT."""
import argparse
import json
import re
from pathlib import Path

def stamp(seconds):
    ms=max(0,round(seconds*1000))
    h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def pick(segments,duration):
    if not segments: return 0.0
    best=(-1e9,0.0)
    for i,segment in enumerate(segments):
        start=float(segment["start"])
        if start+duration>float(segments[-1]["end"]):continue
        window=[x for x in segments[i:] if float(x["start"])<start+duration]
        speech=sum(min(float(x["end"]),start+duration)-max(float(x["start"]),start) for x in window)
        words=" ".join(x["text"] for x in window).lower()
        hooks=len(re.findall(r"\b(why|how|what|never|secret|million|challenge|win|lose|crazy|impossible|last|first)\b",words))
        # Prefer a full, high-energy passage, not a mostly silent intro.
        score=speech/max(duration,1)*8+hooks*0.6+min(len(words.split())/100,2)
        if score>best[0]:best=(score,start)
    return best[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--output",default="clipper/output")
    p.add_argument("--model",default="tiny.en")
    p.add_argument("--start",type=float,default=-1,help="Manual start, -1 for auto")
    a=p.parse_args()
    from faster_whisper import WhisperModel
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    model=WhisperModel(a.model,device="cpu",compute_type="int8")
    segments,_=model.transcribe(a.source,word_timestamps=True,vad_filter=True)
    segments=list(segments)
    items=[{"start":x.start,"end":x.end,"text":x.text.strip()} for x in segments]
    start=a.start if a.start>=0 else pick(items,a.duration)
    end=start+a.duration
    words=[w for s in segments for w in (s.words or []) if w.end>start and w.start<end]
    groups=[words[i:i+4] for i in range(0,len(words),4)]
    lines=[]
    for i,g in enumerate(groups,1):
        begin=max(0,g[0].start-start);finish=min(a.duration,g[-1].end-start)
        if finish<=begin:continue
        label=" ".join(w.word.strip() for w in g).upper()
        lines.append(f"{i}\n{stamp(begin)} --> {stamp(finish)}\n{label}\n")
    (out/"captions.srt").write_text("\n".join(lines),encoding="utf-8")
    (out/"selection.json").write_text(json.dumps({"start":start,"duration":a.duration,"transcript_segments":len(items),"caption_groups":len(lines)},indent=2))
    print(f"Selected {start:.2f}s, {len(lines)} caption groups")
if __name__=="__main__":main()
