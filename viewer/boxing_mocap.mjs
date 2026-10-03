import { validPose, clamp } from './boxing_core.mjs';

export function validateLibrary(data) {
  const validFrame = f => validPose(f?.pose) && f.aux && Object.values(f.aux).every(v => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite));
  if (data?.version !== 1 || !validFrame(data.guard) || !Array.isArray(data.clips) || !data.clips.length)
    throw new Error('Invalid sparring motion library');
  for (const clip of data.clips) {
    if (!clip.frames?.every(validFrame) || clip.frames.length < 4 || !(clip.fps > 0) || ![0, 1].includes(clip.hand)
        || !(clip.launch >= 0 && clip.launch < clip.duration) || !(clip.duration > 0) || !(clip.speed > 0))
      throw new Error('Invalid sparring clip: ' + clip.id);
  }
  return data;
}

export function mixFrames(a, b, weight) {
  const u = clamp(weight, 0, 1);
  const mix = (p, q) => p.map((v, i) => v + (q[i] - v) * u);
  const aux = {};
  for (const key of Object.keys(b.aux)) aux[key] = mix(a.aux[key] || b.aux[key], b.aux[key]);
  return { pose: a.pose.map((p, i) => mix(p, b.pose[i])), aux };
}

export function sampleClip(clip, seconds) {
  const f = clamp(seconds * clip.fps, 0, clip.frames.length - 1);
  const i = Math.floor(f);
  return mixFrames(clip.frames[i], clip.frames[Math.min(i + 1, clip.frames.length - 1)], f - i);
}

export function playStrike(clip, seconds, guard) {
  const fade = Math.min(clamp(seconds / .12, 0, 1), clamp((clip.duration - seconds) / .15, 0, 1));
  return mixFrames(guard, sampleClip(clip, seconds), fade * fade * (3 - 2 * fade));
}
