import assert from 'node:assert/strict';
import fs from 'node:fs';
import { validateLibrary, playStrike, sampleClip } from '../viewer/boxing_mocap.mjs';
import { validPose } from '../viewer/boxing_core.mjs';
const lib = validateLibrary(JSON.parse(fs.readFileSync(new URL('../viewer/sparring_mocap.json', import.meta.url))));
assert.equal(lib.clips.length, 4);
assert.deepEqual(new Set(lib.clips.map(c => c.hand)), new Set([0, 1]));
for (const c of lib.clips) {
  assert(c.fps > 29 && c.fps < 31, `${c.id}: capture rate`);
  assert(Math.abs(c.duration - (c.frames.length - 1) / c.fps) < .001);
  assert.deepEqual(playStrike(c, 0, lib.guard).pose, lib.guard.pose);
  assert.deepEqual(playStrike(c, c.duration, lib.guard).pose, lib.guard.pose);
  let travel = 0, last = sampleClip(c, 0).pose[12 + c.hand];
  for (let t = 0; t <= c.duration; t += 1/60) {
    const f = playStrike(c, t, lib.guard);
    assert(validPose(f.pose));
    assert.deepEqual(f.aux[c.hand ? 'right_wrist' : 'left_wrist'], f.pose[12+c.hand]);
    travel += Math.hypot(...f.pose[12+c.hand].map((v, i) => v-last[i]));
    last = f.pose[12+c.hand];
  }
  assert(travel > .25, `${c.id}: moving wrist`);
}
assert.throws(() => validateLibrary({version: 1, guard: lib.guard, clips: [{...lib.clips[0], speed: NaN}]}));
console.log('PASS: four real 30 Hz clips, bilateral strikes, continuous 60 Hz playback, matched wrist auxiliaries, guard transitions, malformed-library rejection');
