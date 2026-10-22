import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";

// Existing Night Files Remotion package: a selective EDITORIAL post-pass, not another pipeline.
// Called only by Python's established renderer / offline manual preview. All original
// illustrations are baked into the source, preserving their identity and crimson glow.
const here=path.dirname(fileURLToPath(import.meta.url));
const input=process.argv[2];
if(!input) throw new Error("Usage: node render_polish.mjs <manifest.json>");
const spec=JSON.parse(fs.readFileSync(path.resolve(input),"utf8"));
if(!spec.source || !spec.output || !Array.isArray(spec.shots) || !Array.isArray(spec.words))
  throw new Error("Expected source, output, shots[], and words[] in manifest");
const source=path.resolve(spec.source),target=path.resolve(spec.output);
const frames=Number(spec.totalFrames),fps=Number(spec.fps);
if(!fs.existsSync(source) || !(frames>0&&frames<=36000) || !(fps>=12&&fps<=60))
  throw new Error("Invalid input video or frames/fps");
if(source===target) throw new Error("Output must differ from input");
const remotionBin=path.join(here,"node_modules",".bin",process.platform==="win32"?"remotion.cmd":"remotion");
if(!fs.existsSync(remotionBin)) throw new Error("Install local Remotion with npm install in remotion/");
const publicDir=path.join(here,"public");
fs.mkdirSync(publicDir,{recursive:true});
const temp=fs.mkdtempSync(path.join(publicDir,"nightfiles-polish-"));
const tempName=path.basename(temp);
const propsPath=path.join(temp,"props.json");
const cleanVideo=path.join(os.tmpdir(),`nf-polish-${process.pid}-${Date.now()}.mp4`);
try {
  fs.copyFileSync(source,path.join(temp,"input.mp4"));
  const props={
    video:tempName+"/input.mp4",shots:spec.shots,words:spec.words,
    totalFrames:Math.round(frames),fps,
  };
  fs.writeFileSync(propsPath,JSON.stringify(props));
  execFileSync(remotionBin,[
    "render","src/index.jsx","NightFilesPolish",cleanVideo,
    "--props="+propsPath,"--codec=h264","--pixel-format=yuv420p",
    "--concurrency=2","--log=error"
  ],{cwd:here,stdio:"inherit",timeout:30*60*1000});
  if(!fs.existsSync(cleanVideo) || fs.statSync(cleanVideo).size<10000)
    throw new Error("Remotion produced no valid MP4");
  // Remotion renders the visual pass; FFmpeg remuxes EXACT original audio.
  // Silence/lack of audio is a test failure, never silently discard narration.
  fs.mkdirSync(path.dirname(target),{recursive:true});
  execFileSync("ffmpeg",[
    "-y","-v","error","-i",cleanVideo,"-i",source,
    "-map","0:v:0","-map","1:a:0",
    "-c:v","copy","-c:a","copy","-shortest",
    "-movflags","+faststart",target
  ],{stdio:"inherit",timeout:300000});
  if(fs.statSync(target).size<10000) throw new Error("Polish MP4 missing after audio remux");
  process.stdout.write("REMOTION_POLISH_OK "+target+"\n");
}finally {
  fs.rmSync(temp,{recursive:true,force:true});
  fs.rmSync(cleanVideo,{force:true});
}
