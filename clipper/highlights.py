"""Select an excerpt and generate one-word ASS captions for animated top-panel text."""
import argparse
import json
import re
from pathlib import Path

def stamp(seconds):
    ms=max(0,round(seconds*1000))
    h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def ass_time(seconds):
    cs=max(0,round(seconds*100))
    h,cs=divmod(cs,360000);m,cs=divmod(cs,6000);s,cs=divmod(cs,100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"

def pick(segments,duration):
    if not segments:return 0.0
    best=(-1e9,0.0)
    for i,segment in enumerate(segments):
        start=float(segment["start"])
        if start+duration>float(segments[-1]["end"]):continue
        window=[x for x in segments[i:] if float(x["start"])<start+duration]
        speech=sum(max(0,min(float(x["end"]),start+duration)-max(float(x["start"]),start)) for x in window)
        words=" ".join(x["text"] for x in window).lower()
        hooks=len(re.findall(r"\b(why|how|what|never|secret|million|challenge|win|lose|crazy|impossible|last|first)\b",words))
        score=speech/max(duration,1)*8+hooks*0.6+min(len(words.split())/100,2)
        if score>best[0]:best=(score,start)
    return best[1]

def make_ass(words,start,duration,path,part_number=None):
    # PlayResY=1920, caption band occupies y=1056..1152. Captions centered at y=1104.
    header="""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,Arial,78,&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,30,30,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events=[]
    if part_number is not None:
        events.append(f"Dialogue: 1,0:00:00.00,{ass_time(duration)},Word,,0,0,0,,{{\\an8\\pos(540,125)\\fs74\\bord6}}PART {part_number}\n")
    for w in words:
        begin=max(0,float(w.start)-start)
        end=min(duration,float(w.end)-start)
        if end<=begin:continue
        label=re.sub(r"[{}\\]","",w.word.strip().upper()).replace("\n"," ")
        if not label:continue
        # Animated pop-in: scale from 65% to 110%, settling at 100%.
        effect=r"{\an5\pos(540,1104)\fscx65\fscy65\t(0,110,\fscx110\fscy110)\t(110,190,\fscx100\fscy100)}"
        events.append(f"Dialogue: 0,{ass_time(begin)},{ass_time(end)},Word,,0,0,0,,{effect}{label}\n")
    Path(path).write_text(header+"".join(events),encoding="utf-8")
    return len(events)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",required=True)
    p.add_argument("--duration",type=float,default=45)
    p.add_argument("--output",default="clipper/output")
    p.add_argument("--model",default="tiny.en")
    p.add_argument("--start",type=float,default=-1)
    p.add_argument("--rotation",type=int,default=0,help="Advance to another high-scoring highlight")
    p.add_argument("--part-number",type=int,default=0,help="One-based original video part number")
    a=p.parse_args()
    from faster_whisper import WhisperModel
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    model=WhisperModel(a.model,device="cpu",compute_type="int8")
    segments,_=model.transcribe(a.source,word_timestamps=True,vad_filter=True)
    segments=list(segments)
    items=[{"start":x.start,"end":x.end,"text":x.text.strip()} for x in segments]
    if a.part_number>0:
        start=(a.part_number-1)*a.duration
    elif a.start>=0:
        start=a.start
    else:
        # Rank candidate windows, then rotate through the best 12 to avoid
        # publishing the same passage every scheduled run.
        candidates=[]
        for segment in items:
            t=float(segment["start"])
            if t+a.duration>float(items[-1]["end"]):continue
            window=[x for x in items if t<=x["start"]<t+a.duration]
            spoken=" ".join(x["text"] for x in window).lower()
            speech=sum(max(0,min(x["end"],t+a.duration)-max(x["start"],t)) for x in window)
            hooks=sum(spoken.count(w) for w in ("why","how","what","never","secret","million","challenge","win","lose","crazy","impossible"))
            score=speech/a.duration*8+hooks*.6+min(len(spoken.split())/100,2)
            candidates.append((score,t))
        ranked=sorted(candidates,reverse=True)
        distinct=[]
        for score,t in ranked:
            if all(abs(t-other)>=a.duration for other in distinct):
                distinct.append(t)
            if len(distinct)>=12:break
        start=distinct[a.rotation%len(distinct)] if distinct else pick(items,a.duration)
    # Heuristic only, not a forecast of views.
    selected=[x for x in items if start<=x["start"]<start+a.duration]
    transcript=" ".join(x["text"] for x in selected).lower()
    hook_hits=sum(transcript.count(w) for w in ("why","how","what","never","secret","million","challenge","win","lose","crazy","impossible"))
    speech_seconds=sum(max(0,min(x["end"],start+a.duration)-max(x["start"],start)) for x in selected)
    density=min(1.0,speech_seconds/a.duration)
    words_per_second=len(transcript.split())/a.duration
    viral_score=round(100*(0.45*min(hook_hits/6,1)+0.35*density+0.20*min(words_per_second/3.5,1)),1)
    words=[w for s in segments for w in (s.words or []) if w.end>start and w.start<start+a.duration]
    count=make_ass(words,start,a.duration,out/"captions.ass",a.part_number or None)
    (out/"selection.json").write_text(json.dumps({"start":start,"duration":a.duration,
        "transcript_segments":len(items),"caption_words":count,"part_number":a.part_number,"viral_potential_score":viral_score,"viral_score_note":"Transcript-based heuristic only, not a forecast of views"},indent=2))
    print(f"Selected {start:.2f}s, {count} animated caption words")

if __name__=="__main__":main()
