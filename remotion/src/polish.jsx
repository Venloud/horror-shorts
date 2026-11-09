import React, {useMemo} from "react";
import {AbsoluteFill, OffthreadVideo, interpolate, staticFile,
        useCurrentFrame, useVideoConfig} from "remotion";

// Edit existing Night Files output, do not replace its Python/Pillow render engine.
// Original character PNGs, palette, background illustration and audio are untouched.
// All movements below are deterministic and synchronized to the storyboard.
const PALETTE = {paper: "#FFFFFF", ink: "#11151B", cyan: "#5ED6F2", muted: "#B9C0C9"};
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

const CaptionTrack=({words=[],shots=[]})=>{
  const frame=useCurrentFrame();
  // Captions sit at y 1120-1291: above the platforms' own caption / username / button UI at the bottom (owner).
  // During a host reaction the bust fills the lower frame: captions move to the top safe area (never over a face).
  const high=shots.some(x=>x.kind==="host" && frame>=x.startFrame && frame<x.endFrame);
  const {fps}=useVideoConfig();
  const t=frame/fps;
  const groups=useMemo(()=>groupSpokenWords(words),[words]);
  const g=groups.find(group=>t>=group.start-0.055 && t<group.end+0.12);
  if(!g) return null;
  // A short fade in and out; no scale, slide or bounce (owner: readable, not distracting).
  const enter=interpolate(t,[g.start-0.055,g.start+0.06],[0,1],clamp);
  const exit=interpolate(t,[g.end-0.08,g.end+0.14],[1,0],clamp);
  return <div style={{
    position:"absolute",left:73,right:185,top:high?250:1120,height:171,
    display:"flex",alignItems:"center",justifyContent:"center",
    opacity:Math.min(1,Math.max(0,Math.min(enter,exit))),
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
        return <span key={i} style={{
          display:"inline-block",margin:"0 5px",
          // Cyan ONLY on the payoff words the editor chose (explainer.caption_accents), never every word.
          color:hit?(w.accent?PALETTE.cyan:PALETTE.paper):PALETTE.muted,
          opacity:hit?1:0.60,
          textShadow:hit?"0 1px 8px rgba(255,255,255,0.12)":"none",
          transition:"none"
        }}>{w.word}</span>;
      })}
    </div>
  </div>;
};

const GrainAndSafeArea=()=>{
  const frame=useCurrentFrame();
  // Deterministic subtle grain avoids random per-frame flicker and faces remain legible.
  const shift=frame%3;
  // Always on (owner): subtle grain + a soft vignette, never strong enough to hide a face or a caption.
  return <>
    <AbsoluteFill style={{pointerEvents:"none",opacity:0.045,
      backgroundImage:`repeating-linear-gradient(${90+shift}deg, transparent 0px,rgba(210,226,234,.27) 1px,transparent 3px,transparent 14px)`}}/>
    <AbsoluteFill style={{pointerEvents:"none",
      background:"radial-gradient(ellipse 78% 62% at 50% 46%, rgba(0,0,0,0) 62%, rgba(0,0,0,0.38) 100%)"}}/>
  </>;
};

// No persistent progress rail, decorative cut sweep or corner label: only subtle grain and captions.
export const NightFilesPolish=({video="",words=[],shots=[],totalFrames=1})=>{
  // Audio is muxed AFTER Remotion, preserving the already composed production mix.
  return <AbsoluteFill style={{backgroundColor:PALETTE.ink}}>
    {video?<OffthreadVideo src={staticFile(video)} muted
      style={{height:"100%",width:"100%",objectFit:"cover"}}/>:null}
    <GrainAndSafeArea/>
    <CaptionTrack words={words} shots={shots}/>
  </AbsoluteFill>;
};
