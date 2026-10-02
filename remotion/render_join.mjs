import fs from "node:fs";
import path from "node:path";
import {execFileSync} from "node:child_process";

const manifestPath = process.argv[2];
if (!manifestPath) throw new Error("Usage: npm run render:join -- <manifest.json>");

const manifest = JSON.parse(fs.readFileSync(path.resolve(manifestPath), "utf8"));
const root = process.cwd();
const publicDir = path.join(root, "public");
const jobDir = path.join(publicDir, "night-files-join");
fs.rmSync(jobDir, {recursive: true, force: true});
fs.mkdirSync(jobDir, {recursive: true});

for (const clip of manifest.clips) {
  fs.copyFileSync(path.resolve(clip.source), path.join(jobDir, clip.file));
}

const props = {
  clips: manifest.clips.map(({file, startFrame, durationFrames, fadeInFrames, fadeOutFrames}) => ({
    file: "night-files-join/" + file,
    startFrame,
    durationFrames,
    fadeInFrames,
    fadeOutFrames,
  })),
  totalFrames: manifest.totalFrames,
};

const propsPath = path.join(jobDir, "props.json");
fs.writeFileSync(propsPath, JSON.stringify(props));

try {
  execFileSync(
    process.platform === "win32" ? "npx.cmd" : "npx",
    [
      "remotion",
      "render",
      "src/index.jsx",
      "NightFilesJoin",
      path.resolve(manifest.output),
      "--props=" + propsPath,
      "--codec=h264",
      "--pixel-format=yuv420p",
      "--concurrency=2",
      "--log=error",
    ],
    {stdio: "inherit", cwd: root}
  );
} finally {
  fs.rmSync(jobDir, {recursive: true, force: true});
}
