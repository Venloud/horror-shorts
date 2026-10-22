import React, {useMemo} from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, spring, staticFile,
        useCurrentFrame, useVideoConfig} from "remotion";

// Edit existing Night Files output, do not replace its Python/Pillow render engine.
// Original character PNGs, palette, background illustration and audio are untouched.
// All movements below are deterministic and synchronized to the storyboard.
const PALETTE = {paper: "#F1EEE8", ink: "#11151B", red: "#F01767", muted: "#B9C0C9"};
const clamp = {extrapolateLeft: "clamp", extrapolateRight: "clamp"};
const cap = (v, n=64) => String(v ?? "").replace(/[\r\n]+/g," ").slice(0,n);

export const groupSpokenWords = (words=[]) => {
  if (!Array.isArray(words)) return [];
  const sorted = [...words].filter(w => Number.isFinite(Number(w.start)) &&
    Number.isFinite(Number(w.end)) && Number(w.end) > Number(w.start) &&
    String(w.word || "").trim()).sort((a,b)=>Number(a.start)-Number(b.start));
  const groups = [];
  let current = [];
  for (let i=0;i<sorted.length;i++) {
    const w=sorted[i];
    const prev=current[current.length-1];
    if (current.length && (current.length >= 3 ||
        Number(w.start)-Number(prev.end) > 0.45 ||
        current.some(p=>/[.!?]$/.test(p.word)))) {
      groups.push(current);
      current=[];
    }
    current.push({...w, word: cap(w.word, 32)});
  }
  if(current.length) groups.push(current);
  return groups.map(items=>({start:Number(items[0].start),
    end:Number(items[items.length-1].end),words:items}));
};

const CaptionTrack=({words=[]})=>{
  const frame=useCurrentFrame();
  const {fps}=useVideoConfig();
  const t=frame/fps;
  const groups=useMemo(()=>groupSpokenWords(words),[words]);
  const g=groups.find(group=>t>=group.start-0.055 && t<group.end+0.12);
  if(!g) return null;
  const local=Math.max(0,frame-Math.round(g.start*fps));
  const reveal=spring({fps,frame:local,config:{damping:200,mass:0.65,stiffness:260}});
  const exit=interpolate(t,[g.end-0.08,g.end+0.14],[1,0],clamp);
  const total=1-Math.pow(1-reveal,2);
  return <div style={{
    position:"absolute",left:73,right:185,top:1370,height:171,
    display:"flex",alignItems:"center",justifyContent:"center",
    opacity:Math.min(1,Math.max(0,exit)),
    transform:`translateY(${(1-total)*26}px) scale(${0.95+0.05*total})`,
    pointerEvents:"none"
  }}>
    <div style={{
      maxWidth:"100%",minWidth:"64%",padding:"21px 26px 23px",
      boxSizing:"border-box",textAlign:"center",borderRadius:15,
      backgroundColor:"rgba(9,13,19,0.87)",
      boxShadow:"0 12px 45px rgba(0,0,0,0.42)",
      border:"1px solid rgba(235,240,245,0.11)",
      fontFamily:"Arial, sans-serif",fontSize:49,fontWeight:900,
      letterSpacing:"-1.1px",lineHeight:1.17,color:PALETTE.paper,
      overflowWrap:"break-word"
    }}>
      {g.words.map((w,i)=>{
        const hit=t>=Number(w.start)-0.045;
        const p=interpolate(t,[Number(w.start)-0.09,Number(w.start)+0.11],[0,1],clamp);
        return <span key={i} style={{
          display:"inline-block",margin:"0 5px",
          color:hit?PALETTE.paper:PALETTE.muted,
          opacity:hit?1:0.60,
          transform:`translateY(${hit?(1-p)*7:0}px)`,
          textShadow:hit?"0 1px 8px rgba(255,255,255,0.12)":"none",
          borderBottom:hit&&t<=Number(w.end)+0.06?`4px solid ${PALETTE.red}`:"4px solid transparent",
          transition:"none"
        }}>{w.word}</span>;
      })}
    </div>
  </div>;
};

const CutTreatment=({shots=[]})=>{
  const frame=useCurrentFrame();const {fps}=useVideoConfig();
  const s=shots.find((x,i)=>i>0 && frame>=x.startFrame &&
    frame<x.startFrame+Math.min(10,Math.round(.4*fps)));
  if(!s) return null;
  const progress=frame-s.startFrame;
  const fade=interpolate(progress,[0,2,8],[0.40,0.15,0],clamp);
  const sweep=interpolate(progress,[0,8],[-350,1700],clamp);
  return <AbsoluteFill style={{pointerEvents:"none"}}>
    <div style={{position:"absolute",inset:0,background:`rgba(10,16,26,${fade})`}}/>
    <div style={{
      position:"absolute",height:"130%",width:185,top:"-15%",
      left:sweep,transform:"rotate(12deg)",
      background:"linear-gradient(90deg,transparent,rgba(241,23,103,0.25),transparent)",
      filter:"blur(28px)",opacity:Math.max(0,fade*2)}}/>
  </AbsoluteFill>;
};

const ContextMark=({shots=[]})=>{
  const frame=useCurrentFrame();const {fps}=useVideoConfig();
  const shot=shots.find(s=>frame>=s.startFrame&&frame<s.endFrame);
  if(!shot) return null;
  const local=frame-shot.startFrame;
  const title=shot.kind==="scene"?"NIGHT FILES" : shot.kind==="graphic" ?
    cap(shot.template,20).replace(/_/g," ") : "CASE FILE";
  const rise=spring({fps,frame:local,config:{damping:180,stiffness:190}});
  const hide=interpolate(frame,[shot.endFrame-7,shot.endFrame-1],[1,0],clamp);
  return <div style={{
      position:"absolute",left:72,top:130,
      transform:`translateY(${(1-rise)*-19}px)`,
      opacity:Math.min(1,rise)*hide,
      display:"flex",alignItems:"center",gap:13,
      pointerEvents:"none",
    }}>
      <div style={{width:6,height:42,background:PALETTE.red,borderRadius:4}}/>
      <div style={{fontSize:23,fontWeight:850,letterSpacing:"3.8px",
                   color:PALETTE.paper,fontFamily:"Arial, sans-serif",
                   textShadow:"0 2px 14px rgba(0,0,0,0.85)"}}>{title.toUpperCase()}</div>
  </div>;
};

const TimelineRail=({shots=[],durationFrames=1})=>{
  const frame=useCurrentFrame();
  const progress=Math.min(1,Math.max(0,frame/Math.max(1,durationFrames-1)));
  return <div style={{position:"absolute",left:70,right:174,top:93,height:3,
                      background:"rgba(230,233,238,0.13)",pointerEvents:"none"}}>
    <div style={{width:`${progress*100}%`,height:"100%",
                 background:PALETTE.red,boxShadow:"0 0 11px rgba(240,23,103,.6)"}}/>
    {shots.filter(s=>s.startFrame>0).map((shot,i)=><div key={i} style={{
      position:"absolute",left:`${(shot.startFrame/durationFrames)*100}%`,
      top:-2,height:7,width:2,background:"rgba(235,238,242,.42)"}}/>)}
  </div>;
};

const GrainAndSafeArea=()=>{
  const frame=useCurrentFrame();
  // Deterministic subtle grain avoids random per-frame flicker and faces remain legible.
  const shift=frame%3;
  return <AbsoluteFill style={{pointerEvents:"none",opacity:0.045,
      backgroundImage:`repeating-linear-gradient(${90+shift}deg, transparent 0px,rgba(210,226,234,.27) 1px,transparent 3px,transparent 14px)`}}/>;
};

export const NightFilesPolish=({video="",words=[],shots=[],totalFrames=1})=>{
  // Audio is muxed AFTER Remotion, preserving the already composed production mix.
  return <AbsoluteFill style={{backgroundColor:PALETTE.ink}}>
    {video?<OffthreadVideo src={staticFile(video)} muted
      style={{height:"100%",width:"100%",objectFit:"cover"}}/>:null}
    <GrainAndSafeArea/>
    <CutTreatment shots={shots}/>
    <TimelineRail shots={shots} durationFrames={totalFrames}/>
    <ContextMark shots={shots}/>
    <CaptionTrack words={words}/>
  </AbsoluteFill>;
};
