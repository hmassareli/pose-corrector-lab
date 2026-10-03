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
export function segmentSphereContact(a,b,c,r){
 const d=b.map((v,i)=>v-a[i]),w=a.map((v,i)=>v-c[i]);
 const A=d.reduce((n,v)=>n+v*v,0),B=w.reduce((n,v,i)=>n+v*d[i],0),C=w.reduce((n,v)=>n+v*v,0)-r*r;
 if(C<=0)return 0;if(A<1e-12)return -1;
 const discriminant=B*B-A*C;if(discriminant<0)return -1;
 const t=(-B-Math.sqrt(discriminant))/A;return t>=0&&t<=1?t:-1;
}
export function segmentSphere(a, b, c, r) {
  return segmentSphereContact(a, b, c, r) >= 0;
}
export function segmentCapsule(a, b, c, d, r) {
  return segmentCapsuleContact(a, b, c, d, r) >= 0;
}
export function segmentCapsuleContact(a,b,c,d,r){
 const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
 const u=sub(b,a),v=sub(d,c),w=sub(a,c),vv=dot(v,v);
 if(vv<1e-12)return segmentSphereContact(a,b,c,r);
 const projection=clamp(dot(w,v)/vv,0,1);
 if(Math.hypot(...w.map((n,i)=>n-v[i]*projection))<=r)return 0;
 let best=Infinity;
 for(const end of [c,d]){const t=segmentSphereContact(a,b,end,r);if(t>=0)best=Math.min(best,t);}
 const uv=dot(u,v),wv=dot(w,v),A=vv*dot(u,u)-uv*uv,B=vv*dot(u,w)-uv*wv,C=vv*dot(w,w)-wv*wv-r*r*vv;
 const disc=B*B-A*C;
 if(A>1e-12&&disc>=0){
  const t=(-B-Math.sqrt(disc))/A,y=wv+t*uv;
  if(t>=0&&t<=1&&y>=0&&y<=vv)best=Math.min(best,t);
 }
 return Number.isFinite(best)?best:-1;
}
export function capsulePenetration(first,second){
  const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
  const u=sub(first.b,first.a),v=sub(second.b,second.a),w=sub(first.a,second.a);
  const A=dot(u,u),B=dot(u,v),C=dot(v,v),D=dot(u,w),E=dot(v,w),den=A*C-B*B;
  let s=A>1e-9?(den>1e-9?clamp((B*E-C*D)/den,0,1):0):0;
  let t=C>1e-9?(B*s+E)/C:0;
  if(t<0){t=0;s=A>1e-9?clamp(-D/A,0,1):0;}
  else if(t>1){t=1;s=A>1e-9?clamp((B-D)/A,0,1):0;}
  const a=first.a.map((n,i)=>n+s*u[i]),b=second.a.map((n,i)=>n+t*v[i]);
  const delta=sub(b,a),distance=Math.hypot(...delta);
  return {a,b,distance,depth:first.r+second.r-distance,normal:distance>1e-8?delta.map(n=>n/distance):[0,0,1]};
}
// Tuning shared by host simulation and tests. Speeds are wrist m/s from mocap.
export const COMBAT = {
  headRadius: 0.24,
  chinRadius: 0.075,
  bodyRadius: 0.3,
  forearmRadius: 0.1,
  minSpeed: 1.1,
  fullPowerSpeed: 4.2,
  maxDamage: 30,
  chinPower: 0.45,
  dizzySeconds: 2.2,
  dizzyImmunity: 4,
  recoilSeconds: 0.45,
  // Closest pelvis-to-pelvis distance: at 0.95 m a fully extended rendered jab fell ~17 cm short.
  minDistance: 0.72,
};
// Feedback calibration is independent of the physical safety ceiling and damage.
export const PUNCH = {
  tierScaleN: 1200, maxN: 2500, minN: 80,
  bodyKg: 80, trunkCoupling: 0.18, contactSeconds: 0.015, windowMs: 150,
  damagePerN: { head: 1 / 85, body: 1 / 120 },
  tiers: [
    { at: 0, id: 'toque', label: '' }, { at: .13, id: 'leve', label: '' },
    { at: .33, id: 'solido', label: '' }, { at: .54, id: 'forte', label: 'LANDED' },
    { at: .75, id: 'pesado', label: 'CRUSHING' }, { at: .96, id: 'devastador', label: 'DEVASTATING' },
  ],
};
export const safeForce = (n) => clamp(Number.isFinite(n) ? n : 0, 0, PUNCH.maxN);
export const punchPower = (forceN) => clamp(safeForce(forceN) / PUNCH.tierScaleN, 0, 1);
export function punchTier(forceN) {
  const ratio = safeForce(forceN) / PUNCH.tierScaleN;
  return PUNCH.tiers.findLast(t => ratio >= t.at) || PUNCH.tiers[0];
}
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
      if (as >= 0 && as <= s) (arm = f.hand ?? h), (s = as);
    });
  if (!target && arm < 0) return null;
  const chin = arm < 0 && target === "head" && chinS >= 0;
  const point = previous.map((v, i) => v + (current[i] - v) * s);
  return { target: arm >= 0 ? "arm" : target, arm, chin, point };
}
export function punchDamage({ forceN = 0, target = "head", chin = false, guard = false, dizzy = false, counter = false, weakened = false }) {
  const force = safeForce(forceN);
  if (force < PUNCH.minN || target === "arm" || guard) return 0;
  let damage = force * (PUNCH.damagePerN[target] || PUNCH.damagePerN.head);
  if (chin) damage *= 1.35;
  if (dizzy) damage *= 1.3;
  if (counter) damage *= 1.2;
  if (weakened) damage *= 0.7;
  return clamp(damage, 0, COMBAT.maxDamage);
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
  reset() { this.reference = null; this.previous = null; this.stable = []; this.floor = null; }
  update(points, time, cameraInfo = null) {
    if (!validPose(points) || !Number.isFinite(time)) return null;
    const root = points[0], floor = Math.min(points[5][1], points[6][1]);
    const height = points[15][1] - floor;
    const old = this.stable.at(-1);
    const jitter = old ? Math.hypot(...root.map((v,i)=>v-old.root[i])) : 0;
    if (!this.reference) {
      if (height < 1.3 || height > 2.1 || jitter > .04 || (old && time-old.time > 250)) this.stable = [];
      else this.stable.push({ time, root: root.slice(), height, floor });
      this.stable = this.stable.filter(f => time-f.time <= 650);
      const heights = this.stable.map(f=>f.height);
      if (this.stable.length < 8 || time-this.stable[0].time < 500 || Math.max(...heights)-Math.min(...heights) > .06)
        return { calibrating: true, framed: true, pose: null, lateral: 0, radial: 0 };
      const median = a => a.slice().sort((x,y)=>x-y)[Math.floor(a.length/2)];
      this.reference = { root: root.slice(), floor: median(this.stable.map(f=>f.floor)), scale: 1.72/median(heights) };
      this.floor = floor;
    }
    const r = this.reference, scale = r.scale;
    const dt = this.previous ? (time-this.previous.time)/1000 : 0;
    if (this.previous && (dt > .5 || Math.hypot(...root.map((v,i)=>v-this.previous.root[i]))*scale > .35)) {
      r.root[0] += root[0]-this.previous.root[0]; r.root[2] += root[2]-this.previous.root[2];
    }
    this.floor += (floor-this.floor)*(1-Math.exp(-Math.max(.033,dt)*12));
    const pose = points.map(v=>[(v[0]-root[0])*scale,(v[1]-this.floor)*scale,(v[2]-root[2])*scale]);
    let framed = true;
    if (cameraInfo?.size?.length === 2) {
      const [w,h] = cameraInfo.size, focal = Math.max(w,h)/(2*Math.tan((cameraInfo.fov || 55)*Math.PI/360));
      framed = [0,7,8,9].every(i=>{
        const p=points[i], depth=-p[2], x=w/2+focal*p[0]/depth, y=h/2-focal*p[1]/depth;
        return depth>.2 && x>.015*w && x<.985*w && y>.015*h && y<.985*h;
      });
    }
    const result = { pose, calibrating: false, lateral:(root[0]-r.root[0])*scale, radial:(root[2]-r.root[2])*scale, framed };
    if (!framed && this.previous) {
      r.root[0]+=(result.lateral-this.previous.lateral)/scale; r.root[2]+=(result.radial-this.previous.radial)/scale;
      result.lateral=this.previous.lateral; result.radial=this.previous.radial;
    }
    this.previous = { root:root.slice(), time, lateral:result.lateral, radial:result.radial };
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
// Least-squares velocity in metres/second. A 150 ms window suppresses
// single-frame velocity spikes without scaling human measurements to the avatar.
export function regression(frames, pick) {
  if (frames.length < 3) return null;
  const meanT = frames.reduce((n,f)=>n+f.time,0)/frames.length;
  const values = frames.map(f=>pick(f.pose));
  const vector = Array.isArray(values[0]), out = vector ? [0,0,0] : [0];
  let denominator = 0;
  frames.forEach((f,j)=>{
    const t=(f.time-meanT)/1000; denominator+=t*t;
    out.forEach((_,i)=>out[i]+=t*(vector ? values[j][i] : values[j]));
  });
  if (denominator < 1e-9) return null;
  return vector ? out.map(n=>n/denominator) : out[0]/denominator;
}
const vecSub=(a,b)=>a.map((v,i)=>v-b[i]);
const vecMid=(a,b)=>a.map((v,i)=>(v+b[i])/2);
const vecDot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
export function measurePunch(frames, hand, bodyKg = PUNCH.bodyKg, targetDirection = null) {
  const S=8+hand,E=10+hand,W=12+hand;
  const velocity = pick=>regression(frames,pick);
  const vHand=velocity(p=>p[W]);
  if (!vHand) return null;
  const extension=velocity(p=>Math.hypot(...vecSub(p[W],p[S])));
  const speed=Math.hypot(...vHand);
  const target=targetDirection || vHand, length=Math.hypot(...target);
  const direction=target.map(v=>v/Math.max(1e-6,length));
  const relative=velocity(p=>vecSub(p[W],p[S]));
  const along=v=>Math.max(0,vecDot(v,direction));
  // A carried guard cannot borrow the trunk's momentum.
  const coupled = extension >= 1 && along(relative) >= .5;
  const mass=clamp(Number.isFinite(bodyKg)?bodyKg:80,40,180);
  const momentum=mass*(.006*along(vHand)+.016*along(velocity(p=>vecMid(p[E],p[W])))+
    .027*along(velocity(p=>vecMid(p[S],p[E])))+(coupled?PUNCH.trunkCoupling*(
      .43*along(velocity(p=>vecMid(p[0],vecMid(p[8],p[9]))))+.07*along(velocity(p=>p[15]))):0));
  return { extension, speed, forceN:safeForce(momentum/PUNCH.contactSeconds), direction, momentum };
}
export class PunchDetector {
  constructor(bodyKg = PUNCH.bodyKg) {
    this.bodyKg=bodyKg; this.frames=[]; this.armed=[true,true]; this.cooldown=[0,0];
    this.speed=[0,0]; this.strokes=[null,null]; this.sequence=0;
  }
  update(pose, time, targetDirection = null) {
    if (!validPose(pose) || !Number.isFinite(time)) return [];
    const previous=this.frames.at(-1);
    if(previous && time<=previous.time) return [];
    if(previous && time-previous.time>250) {
      this.frames=[]; this.strokes=[null,null]; this.armed=[true,true];
    }
    this.frames.push({time,pose:pose.map(v=>v.slice())});
    this.frames=this.frames.filter(f=>time-f.time<=PUNCH.windowMs+.001);
    const out=[]; this.speed=[0,0];
    for(let hand=0;hand<2;hand++) {
      const reach=Math.hypot(...vecSub(pose[12+hand],pose[8+hand]));
      const velocity=regression(this.frames,p=>p[12+hand]);
      const extension=regression(this.frames,p=>Math.hypot(...vecSub(p[12+hand],p[8+hand])));
      if(!velocity||extension===null)continue;
      this.speed[hand]=Math.min(Math.hypot(...velocity),12);
      if(extension<-.25 || reach<.36) this.armed[hand]=true;
      const stroke=this.strokes[hand];
      if(stroke && time-stroke.time<300 && extension>stroke.extension) {
        const m=measurePunch(this.frames,hand,this.bodyKg,targetDirection);
        Object.assign(stroke,m);stroke.peakTime=time;
      }
      // 0.1 mm is below camera precision and avoids a rounded 40.0 cm reach
      // failing on floating reconstruction noise. Retraction is still required.
      if(this.armed[hand] && reach>=.4-.0001 && extension>=1 && time>=this.cooldown[hand]) {
        const m=measurePunch(this.frames,hand,this.bodyKg,targetDirection);
        const hit={hand,time,id:++this.sequence,...m,previous:previous?.pose[12+hand].slice()};
        // Rapid real jabs can complete a retract/extend cycle in ~200 ms.
        this.strokes[hand]=hit; out.push(hit); this.armed[hand]=false; this.cooldown[hand]=time+270;
      }
    }
    return out;
  }
}
// Session journal: detector counts attempts, collision resolves each attempt once.
export class FightJournal {
  constructor() { this.entries=[]; this.comboForce=0; this.maxComboForce=0; this.damageReceived=0; this.receivedPeak=0; }
  attempt({hand,forceN=0,speed=0},t) {
    const row={t:Math.max(0,t),hand,forceN:safeForce(forceN),speed:Number.isFinite(speed)?speed:0,target:null,
      tier:punchTier(forceN).id,landed:false,blocked:false,combo:0};
    this.entries.push(row); return this.entries.length-1;
  }
  land(index,{forceN,target,combo=0,blocked=false,speed=0}) {
    const row=this.entries[index]; if(!row || row.resolved) return;
    Object.assign(row,{forceN:safeForce(forceN),target,combo,blocked,landed:!blocked&&safeForce(forceN)>=PUNCH.minN,resolved:true,speed,
      tier:punchTier(forceN).id});
    if(row.landed) { this.comboForce=combo>1?this.comboForce+row.forceN:row.forceN; this.maxComboForce=Math.max(this.maxComboForce,this.comboForce); }
    else this.comboForce=0;
  }
  summary(seconds=0) {
    const hits=this.entries.filter(e=>e.landed), sum=hits.reduce((n,e)=>n+e.forceN,0);
    const peak=hits.length?Math.max(...hits.map(e=>e.forceN)):null;
    const byTarget=target=>hits.some(e=>e.target===target)?Math.max(...hits.filter(e=>e.target===target).map(e=>e.forceN)):null;
    return {peak,total:hits.length?sum:null,average:hits.length?sum/hits.length:null,hits:hits.length,attempts:this.entries.length,
      accuracy:this.entries.length?hits.length/this.entries.length:null,headPeak:byTarget('head'),bodyPeak:byTarget('body'),
      tiers:Object.fromEntries(PUNCH.tiers.map(t=>[t.id,hits.filter(e=>e.tier===t.id).length])),
      fastest:hits.length?Math.max(...hits.map(e=>e.speed)):null,maxCombo:Math.max(0,...hits.map(e=>e.combo)),
      maxComboForce:this.maxComboForce,blocked:this.entries.filter(e=>e.blocked).length,
      perMinute:seconds>0?this.entries.length*60/seconds:0,damageReceived:this.damageReceived,receivedPeak:this.receivedPeak};
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

