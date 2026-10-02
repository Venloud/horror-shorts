import React from "react";
import {Composition, AbsoluteFill, Sequence, OffthreadVideo, interpolate, useCurrentFrame, staticFile} from "remotion";

const Clip = ({clip}) => {
  const frame = useCurrentFrame();
  const opacityIn = clip.fadeInFrames > 0
    ? interpolate(frame, [0, clip.fadeInFrames], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})
    : 1;
  const opacityOut = clip.fadeOutFrames > 0
    ? interpolate(frame, [Math.max(0, clip.durationFrames - clip.fadeOutFrames), clip.durationFrames], [1, 0], {extrapolateLeft: "clamp", extrapolateRight: "clamp"})
    : 1;
  return (
    <Sequence from={clip.startFrame} durationInFrames={clip.durationFrames} layout="none">
      <AbsoluteFill style={{opacity: Math.min(opacityIn, opacityOut)}}>
        <OffthreadVideo
          src={staticFile(clip.file)}
          muted
          style={{width: "100%", height: "100%", objectFit: "cover"}}
        />
      </AbsoluteFill>
    </Sequence>
  );
};

export const NightFilesJoin = ({clips = []}) => (
  <AbsoluteFill style={{backgroundColor: "black"}}>
    {clips.map((clip, i) => <Clip key={clip.file + "-" + i} clip={clip} />)}
  </AbsoluteFill>
);

export const RemotionRoot = () => (
  <Composition
    id="NightFilesJoin"
    component={NightFilesJoin}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={1}
    defaultProps={{clips: [], totalFrames: 1}}
    calculateMetadata={({props}) => ({
      durationInFrames: Math.max(1, props.totalFrames || 1),
      fps: props.fps || 30,
    })}
  />
);
