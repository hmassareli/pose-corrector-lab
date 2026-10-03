// Pure, deterministic gameplay helpers. Render smoothing never changes damage.
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const JOINTS = Object.fromEntries(
  [
    "pelvis",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
    "spine",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "neck",
    "head",
  ].map((n, i) => [n, i]),
);
export function validPose(p) {
  return (
    Array.isArray(p) &&
    p.length === 16 &&
    p.every(
      (v) =>
        Array.isArray(v) &&
        v.length === 3 &&
        v.every((x) => Number.isFinite(x) && Math.abs(x) < 10),
    )
  );
}
// A short presentation buffer bridges inference frames. Collision continues
// reading the latest unbuffered pose; 0% smoothing bypasses this buffer.
export class PoseRenderBuffer {
  constructor() {
    this.reset();
  }
  reset() {
    this.frames = [];
    this.interval = 33;
  }
  push(pose, aux, time) {
    const previous = this.frames.at(-1);
    if (previous && time <= previous.time) return;
    if (previous && time - previous.time > 250) this.reset();
    else if (previous)
      this.interval += (time - previous.time - this.interval) * 0.25;
    const points = { kind: aux?.kind };
    for (const [key, v] of Object.entries(aux || {})) {
      if (key === "kind" || !v) continue;
      const p = [v.x ?? v[0], v.y ?? v[1], v.z ?? v[2]];
      if (p.every(Number.isFinite)) points[key] = p;
    }
    this.frames.push({ time, pose: pose.map((v) => v.slice()), aux: points });
    if (this.frames.length > 8) this.frames.shift();
  }
  sample(time, smoothing) {
    const latest = this.frames.at(-1);
    if (!latest) return null;
    if (smoothing === 0 || this.frames.length === 1) return latest;
    const target =
      time - clamp(this.interval, 20, 80) * Math.min(1, smoothing / 50);
    let left = this.frames[0],
      right = latest;
    for (const frame of this.frames) {
      if (frame.time <= target) left = frame;
      else {
        right = frame;
        break;
      }
    }
    const alpha =
      right.time === left.time
        ? 1
        : clamp((target - left.time) / (right.time - left.time), 0, 1);
    const mix = (a, b) => a.map((v, i) => v + (b[i] - v) * alpha);
    const aux = { kind: right.aux.kind };
    for (const [key, v] of Object.entries(right.aux))
      if (key !== "kind")
        aux[key] = left.aux[key] ? mix(left.aux[key], v) : v.slice();
    return { pose: left.pose.map((v, i) => mix(v, right.pose[i])), aux };
  }
}
export function neutralPose() {
  return [
    [0, 0.92, 0],
    [-0.13, 0.9, 0],
    [0.13, 0.9, 0],
    [-0.15, 0.5, 0.06],
    [0.15, 0.5, 0.06],
    [-0.19, 0.05, 0.08],
    [0.19, 0.05, -0.07],
    [0, 1.2, 0],
    [-0.24, 1.43, 0],
    [0.24, 1.43, 0],
    [-0.29, 1.17, 0.16],
    [0.29, 1.17, 0.16],
    [-0.33, 1.5, 0.3],
    [0.33, 1.5, 0.3],
    [0, 1.55, 0],
    [0, 1.72, 0],
  ].map((v) => [-v[0], v[1], v[2]]);
}
export function demoPose(t, hand = -1, attack = 0) {
  const p = neutralPose();
  p.forEach((v) => {
    v[1] += Math.sin(t * 3) * 0.012;
  });
  if (hand >= 0) {
    const w = 12 + hand,
      e = 10 + hand;
    p[w][2] += 0.64 * attack;
    p[w][1] -= 0.06 * attack;
    p[e][2] += 0.25 * attack;
  }
  return p;
}
export function segmentSphere(a, b, c, r) {
  const d = b.map((x, i) => x - a[i]),
    l = d.reduce((s, x) => s + x * x, 0);
  const t = l
    ? clamp(d.reduce((s, x, i) => s + x * (c[i] - a[i]), 0) / l, 0, 1)
    : 0;
  return Math.hypot(...a.map((x, i) => x + d[i] * t - c[i])) <= r;
}
export function segmentCapsule(a, b, c, d, r) {
  const sub = (x, y) => x.map((v, i) => v - y[i]),
    dot = (x, y) => x.reduce((s, v, i) => s + v * y[i], 0);
  const u = sub(b, a),
    v = sub(d, c),
    w = sub(a, c),
    uu = dot(u, u),
    vv = dot(v, v),
    uv = dot(u, v),
    uw = dot(u, w),
    vw = dot(v, w);
  let s = 0,
    t = 0;
  const eps = 1e-9;
  if (uu <= eps && vv <= eps) return Math.hypot(...w) <= r;
  if (uu <= eps) t = clamp(vw / vv, 0, 1);
  else if (vv <= eps) s = clamp(-uw / uu, 0, 1);
  else {
    const den = uu * vv - uv * uv;
    s = den > eps ? clamp((uv * vw - uw * vv) / den, 0, 1) : 0;
    t = (uv * s + vw) / vv;
    if (t < 0) {
      t = 0;
      s = clamp(-uw / uu, 0, 1);
    } else if (t > 1) {
      t = 1;
      s = clamp((uv - uw) / uu, 0, 1);
    }
  }
  return Math.hypot(...w.map((x, i) => x + s * u[i] - t * v[i])) <= r;
}
export function orbitalStep(a, b, lateral, radial, dt, range = {min:1.05,max:2.5}) {
  const dx = b.x - a.x,
    dz = b.z - a.z,
    d = Math.hypot(dx, dz) || 1;
  const f = [dx / d, dz / d],
    s = [f[1], -f[0]];
  const speed = 1.15;
  a.x +=
    s[0] * clamp(lateral, -1, 1) * speed * dt +
    f[0] * clamp(radial + clamp((d - 1.1) * 2, 0, 0.65), -1, 1) * 0.45 * dt;
  a.z +=
    s[1] * clamp(lateral, -1, 1) * speed * dt +
    f[1] * clamp(radial + clamp((d - 1.1) * 2, 0, 0.65), -1, 1) * 0.45 * dt;
  const nd = Math.hypot(b.x - a.x, b.z - a.z) || 1,
    target = clamp(nd, range.min, range.max);
  a.x = b.x + ((a.x - b.x) * target) / nd;
  a.z = b.z + ((a.z - b.z) * target) / nd;
  a.x = clamp(a.x, -2.55, 2.55);
  a.z = clamp(a.z, -2.55, 2.55);
  a.yaw = Math.atan2(b.x - a.x, b.z - a.z);
}
// Position input from the webcam moves a matching arc once, rather than
// continuing to orbit for as long as the player stands off-center.
export function orbitalShift(a, b, distance) {
  const x = a.x - b.x,
    z = a.z - b.z,
    radius = Math.hypot(x, z);
  if (radius < 0.001 || !Number.isFinite(distance)) return;
  const angle = -distance / radius,
    c = Math.cos(angle),
    s = Math.sin(angle);
  a.x = clamp(b.x + x * c + z * s, -2.55, 2.55);
  a.z = clamp(b.z - x * s + z * c, -2.55, 2.55);
  a.yaw = Math.atan2(b.x - a.x, b.z - a.z);
}
// Camera-space translation, not lean interpreted as a velocity command.
// NLF absolute reconstruction already uses apparent body size to infer depth.
export class WebcamFootwork {
  constructor() { this.reset(); }
  reset() { this.reference = null; this.previous = null; this.contacts = [true, true]; this.footAnchors=[null,null]; this.quiet=[0,0]; this.visibility=[true,true]; }
  update(points, time, cameraInfo = null) {
    if (!validPose(points)) return null;
    const root = points[0], floor = Math.min(points[5][1], points[6][1]);
    if (!this.reference) {
      this.reference = { root: root.slice(), floor, scale: 1.72 / Math.max(.7, points[15][1] - floor) };
    }
    const r = this.reference, scale = r.scale;
    const dt = this.previous ? (time - this.previous.time) / 1000 : 0;
    // Reacquisition must not spend a missing-frame displacement in one tick.
    if (this.previous && (dt > .5 || Math.hypot(...root.map((x,i)=>x-this.previous.root[i])) * scale > .35)) {
      r.root[0] += root[0] - this.previous.root[0];
      r.root[2] += root[2] - this.previous.root[2];
    }
    const pose = points.map(v => [(v[0]-root[0])*scale, (v[1]-r.floor)*scale, (v[2]-root[2])*scale]);
    const sourceFeet = [5,6].map(i=>points[i].map(x=>x*scale));
    for (let h=0;h<2;h++) {
      const height = (points[5+h][1]-r.floor)*scale;
      const previous = this.previous?.feet[h];
      const speed = previous && dt > 0 ? Math.hypot(sourceFeet[h][0]-previous[0],sourceFeet[h][2]-previous[2])/dt : 0;
      this.footAnchors[h] ??= sourceFeet[h].slice();
      const anchor=this.footAnchors[h];
      const drift=Math.hypot(sourceFeet[h][0]-anchor[0],sourceFeet[h][2]-anchor[2]);
      this.quiet[h] = speed < .18 ? this.quiet[h]+Math.max(0,dt) : 0;
      if (height > .085 || speed > .65 || (this.contacts[h] && drift>.04)) {
        this.contacts[h] = false; this.quiet[h]=0;
      }
      else if (height < .045 && this.quiet[h]>=.09) {
        if(!this.contacts[h]) this.footAnchors[h]=sourceFeet[h].slice();
        this.contacts[h] = true;
      }
    }
    let framed = true, footVisible = [true,true];
    if (cameraInfo?.size?.length === 2) {
      const [w,h] = cameraInfo.size;
      const focal = Math.max(w,h)/(2*Math.tan((cameraInfo.fov || 55)*Math.PI/360));
      const inFrame = (i,margin=.015)=>{
        const p=points[i], depth=-p[2];
        if(depth<=.2) return false;
        const x=w/2+focal*p[0]/depth, y=h/2-focal*p[1]/depth;
        return x>margin*w && x<(1-margin)*w && y>margin*h && y<(1-margin)*h;
      };
      framed = [0,7,8,9].every(i=>inFrame(i));
      footVisible = [5,6].map((i,h)=>inFrame(i,this.visibility[h] ? .005 : .03));
      this.visibility=footVisible.slice();
    }
    const result = { pose, lateral:(root[0]-r.root[0])*scale, radial:(root[2]-r.root[2])*scale,
      contacts:this.contacts.slice(), framed, footVisible };
    // Cropped feet use inferred stepping; only loss of the upper body suspends
    // translation. Update the reference to avoid a reacquisition teleport.
    if (!framed && this.previous) {
      r.root[0] += (result.lateral-this.previous.lateral)/scale;
      r.root[2] += (result.radial-this.previous.radial)/scale;
      result.lateral=this.previous.lateral; result.radial=this.previous.radial;
      result.contacts=[false,false];
    }
    this.previous = { root:root.slice(), feet:sourceFeet, time, lateral:result.lateral, radial:result.radial };
    return result;
  }
}
export function radialShift(a,b,distance) {
  const x=a.x-b.x,z=a.z-b.z,r=Math.hypot(x,z);
  if(r<.001 || !Number.isFinite(distance)) return;
  const next=clamp(r-distance,.95,4.8);
  a.x=clamp(b.x+x*next/r,-2.55,2.55);
  a.z=clamp(b.z+z*next/r,-2.55,2.55);
  a.yaw=Math.atan2(b.x-a.x,b.z-a.z);
}
export class PunchDetector {
  constructor() {
    this.last = null;
    this.time = 0;
    this.armed = [true, true];
    this.cooldown = [0, 0];
  }
  update(p, time) {
    if (!validPose(p)) return [];
    const dt = (time - this.time) / 1000,
      out = [];
    if (this.last && dt > 0.008 && dt < 0.25) {
      for (let h = 0; h < 2; h++) {
        const wrist = p[12 + h],
          shoulder = p[8 + h],
          reach = Math.hypot(...wrist.map((x, i) => x - shoulder[i]));
        if (reach < 0.39) this.armed[h] = true;
        const speed =
          Math.hypot(...wrist.map((x, i) => x - this.last[12 + h][i])) / dt;
        if (
          this.armed[h] &&
          reach > 0.47 &&
          speed > 1.1 &&
          time > this.cooldown[h]
        ) {
          out.push({
            hand: h,
            speed: clamp(speed, 1.1, 6),
            previous: this.last[12 + h].slice(),
          });
          this.armed[h] = false;
          this.cooldown[h] = time + 300;
        }
      }
    }
    this.last = p.map((v) => v.slice());
    this.time = time;
    return out;
  }
}
export function guarded(p) {
  return (
    validPose(p) &&
    [12, 13].every(
      (i) => Math.hypot(p[i][0] - p[15][0], p[i][1] - p[15][1]) < 0.38,
    )
  );
}
