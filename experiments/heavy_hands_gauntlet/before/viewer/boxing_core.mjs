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
// Returns the sweep parameter of closest approach, or -1 without contact.
export function segmentSphereContact(a, b, c, r) {
  const d = b.map((x, i) => x - a[i]),
    l = d.reduce((s, x) => s + x * x, 0);
  const t = l
    ? clamp(d.reduce((s, x, i) => s + x * (c[i] - a[i]), 0) / l, 0, 1)
    : 0;
  return Math.hypot(...a.map((x, i) => x + d[i] * t - c[i])) <= r ? t : -1;
}
export function segmentSphere(a, b, c, r) {
  return segmentSphereContact(a, b, c, r) >= 0;
}
export function segmentCapsule(a, b, c, d, r) {
  return segmentCapsuleContact(a, b, c, d, r) >= 0;
}
export function segmentCapsuleContact(a, b, c, d, r) {
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
  if (uu <= eps && vv <= eps) return Math.hypot(...w) <= r ? 0 : -1;
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
  return Math.hypot(...w.map((x, i) => x + s * u[i] - t * v[i])) <= r ? s : -1;
}
// Tuning shared by host simulation and tests. Speeds are wrist m/s from mocap.
export const COMBAT = {
  headRadius: 0.24,
  chinRadius: 0.075,
  bodyRadius: 0.3,
  forearmRadius: 0.1,
  minSpeed: 1.1,
  fullPowerSpeed: 4.2,
  maxDamage: 18,
  chinPower: 0.45,
  dizzySeconds: 2.2,
  dizzyImmunity: 4,
  recoilSeconds: 0.45,
  // Closest pelvis-to-pelvis distance: at 0.95 m a fully extended rendered jab fell ~17 cm short.
  minDistance: 0.72,
};
export const punchPower = (speed) =>
  clamp((speed - COMBAT.minSpeed) / (COMBAT.fullPowerSpeed - COMBAT.minSpeed), 0, 1);
// Jaw sits below the head joint, in front of the neck (local +z faces the opponent).
export function chinPoint(p) {
  const n = p[14], h = p[15];
  return [n[0] + (h[0] - n[0]) * 0.45, n[1] + (h[1] - n[1]) * 0.45, n[2] + (h[2] - n[2]) * 0.45 + 0.085];
}
// Sweeps the punching wrist through the defender: forearms intercept before the
// target, so a punch that meets the guard stops there instead of passing through.
export function resolvePunch(previous, current, pose, toWorld, opts) {
  return resolvePunchBox(previous, current, poseHitBox(pose, toWorld), opts);
}
// Hit volumes from mocap joints (fallback when no rendered avatar is available).
export function poseHitBox(pose, toWorld) {
  return {
    head: { c: toWorld(pose[15]), r: COMBAT.headRadius },
    chin: { c: toWorld(chinPoint(pose)), r: COMBAT.chinRadius },
    body: { a: toWorld(pose[0]), b: toWorld([0, (pose[8][1] + pose[9][1]) / 2, 0]), r: COMBAT.bodyRadius },
    arms: [0, 1].map((h) => {
      const e = pose[10 + h], w = pose[12 + h];
      return { a: toWorld(e), b: toWorld(w.map((v, i) => v + (v - e[i]) * 0.3)), r: COMBAT.forearmRadius };
    }),
  };
}
// Same rules on explicit world-space volumes (e.g. built from the rendered mesh).
export function resolvePunchBox(previous, current, box, { arms = true } = {}) {
  const headS = segmentSphereContact(previous, current, box.head.c, box.head.r);
  const chinS = segmentSphereContact(previous, current, box.chin.c, box.chin.r);
  const bodyS = segmentCapsuleContact(previous, current, box.body.a, box.body.b, box.body.r);
  let target = null,
    s = Infinity,
    arm = -1;
  // The torso capsule reaches face height, so the head (chin included) keeps priority.
  if (headS >= 0 || chinS >= 0) (target = "head"), (s = headS >= 0 ? headS : chinS);
  else if (bodyS >= 0) (target = "body"), (s = bodyS);
  if (arms)
    box.arms.forEach((f, h) => {
      const as = segmentCapsuleContact(previous, current, f.a, f.b, f.r);
      if (as >= 0 && as <= s) (arm = h), (s = as);
    });
  if (!target && arm < 0) return null;
  const chin = arm < 0 && target === "head" && chinS >= 0;
  const point = previous.map((v, i) => v + (current[i] - v) * s);
  return { target: arm >= 0 ? "arm" : target, arm, chin, point };
}
export function punchDamage({ speed = 2, target = "head", chin = false, guard = false, dizzy = false, counter = false, weakened = false }) {
  if (target === "arm") return 1;
  if (guard) return 2;
  const power = punchPower(speed);
  let damage = target === "head" ? 7 + power * 7 : 5 + power * 5;
  if (chin && power >= COMBAT.chinPower) damage *= 1.35;
  if (dizzy) damage *= 1.3;
  if (counter) damage *= 1.2;
  if (weakened) damage *= 0.7;
  return Math.round(clamp(damage, 1, COMBAT.maxDamage));
}
// Procedural sparring partner: guard 1 = tight high guard, 0 = hands low.
const GUARD_HIGH = { wrist: [0.13, 1.6, 0.24], elbow: [0.21, 1.24, 0.12] };
const GUARD_LOW = { wrist: [0.3, 1.2, 0.25], elbow: [0.27, 1.02, 0.08] };
export function sparringPose(t, { guard = 1, hand = -1, attack = 0, body = false, dizzy = 0 } = {}) {
  const p = neutralPose();
  for (const v of p) v[1] += Math.sin(t * 3) * 0.012;
  for (let h = 0; h < 2; h++) {
    const side = Math.sign(p[12 + h][0]);
    for (const [joint, key] of [[12 + h, "wrist"], [10 + h, "elbow"]]) {
      const hi = GUARD_HIGH[key], lo = GUARD_LOW[key];
      p[joint] = [0, 1, 2].map((i) => {
        const v = lo[i] + (hi[i] - lo[i]) * guard;
        return (i === 0 ? v * side : v) + (i === 1 ? Math.sin(t * 3) * 0.012 : 0);
      });
    }
  }
  if (hand >= 0) {
    const w = p[12 + hand], e = p[10 + hand];
    const reachY = body ? 1.12 : 1.58;
    w[2] += 0.62 * attack;
    w[1] += (reachY - w[1]) * Math.max(0, attack);
    w[0] *= 1 - 0.55 * Math.max(0, attack);
    e[2] += 0.26 * attack;
    e[1] += (reachY - 0.12 - e[1]) * 0.5 * Math.max(0, attack);
  }
  if (dizzy > 0) {
    const sway = Math.sin(t * 4.2) * 0.07 * dizzy, bob = Math.sin(t * 8.4) * 0.02 * dizzy;
    for (let j = 7; j < 16; j++) (p[j][0] += sway * (p[j][1] - 0.9)), (p[j][1] -= bob);
  }
  return p;
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
  const next=clamp(r-distance,COMBAT.minDistance,4.8);
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
    this.speed = [0, 0];
  }
  update(p, time) {
    if (!validPose(p)) return [];
    const dt = (time - this.time) / 1000,
      out = [];
    this.speed = [0, 0];
    if (this.last && dt > 0.008 && dt < 0.25) {
      for (let h = 0; h < 2; h++) {
        const wrist = p[12 + h],
          shoulder = p[8 + h],
          reach = Math.hypot(...wrist.map((x, i) => x - shoulder[i]));
        if (reach < 0.39) this.armed[h] = true;
        const speed =
          Math.hypot(...wrist.map((x, i) => x - this.last[12 + h][i])) / dt;
        this.speed[h] = Math.min(speed, 8);
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
