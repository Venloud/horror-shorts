import React from "react";
import {Composition, registerRoot} from "remotion";
import {NightFilesPolish} from "./polish.jsx";

// Night Files keeps one Remotion composition for the approved host / existing
// story renderer's final editorial pass. The unused legacy joiner was retired.
export const RemotionRoot = () => (
  <Composition
    id="NightFilesPolish"
    component={NightFilesPolish}
    width={1080}
    height={1920}
    fps={24}
    durationInFrames={1}
    defaultProps={{video: "", words: [], shots: [], totalFrames: 1, fps: 24}}
    calculateMetadata={({props}) => ({
      durationInFrames: Math.max(1, props.totalFrames || 1),
      fps: props.fps || 24,
    })}
  />
);

registerRoot(RemotionRoot);
