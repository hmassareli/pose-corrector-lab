"""One-time, narrowly scoped migration; backups are in heavy_hands_gauntlet/before."""
from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = root / 'viewer/boxing_core.mjs'
s = p.read_text(encoding='utf-8')
start = s.index('export class WebcamFootwork')
end = s.index('export function radialShift', start)
s = s[:start] + '''export class WebcamFootwork {
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
''' + s[end:]
start = s.index('export class PunchDetector')
end = s.index('export function guarded', start)
s = s[:start] + '''// Least-squares velocity in metres/second. A 150 ms window suppresses
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
export function measurePunch(frames, hand, bodyKg = PUNCH.bodyKg) {
  const S=8+hand,E=10+hand,W=12+hand;
  const velocity = pick=>regression(frames,pick);
  const vHand=velocity(p=>p[W]);
  if (!vHand) return null;
  const extension=velocity(p=>Math.hypot(...vecSub(p[W],p[S])));
  const speed=Math.hypot(...vHand), direction=vHand.map(v=>v/Math.max(1e-6,speed));
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
  update(pose, time) {
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
      const m=measurePunch(this.frames,hand,this.bodyKg);
      if(!m) continue;
      this.speed[hand]=Math.min(m.speed,12);
      if(m.extension<-.25 || reach<.36) this.armed[hand]=true;
      const stroke=this.strokes[hand];
      if(stroke && time-stroke.time<300 && m.extension>=1 && m.forceN>stroke.forceN) Object.assign(stroke,m);
      if(this.armed[hand] && reach>=.4 && m.extension>=1 && time>=this.cooldown[hand]) {
        const hit={hand,time,id:++this.sequence,...m,previous:previous?.pose[12+hand].slice()};
        this.strokes[hand]=hit; out.push(hit); this.armed[hand]=false; this.cooldown[hand]=time+230;
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
    Object.assign(row,{forceN:safeForce(forceN),target,combo,blocked,landed:!blocked,resolved:true,speed,
      tier:punchTier(forceN).id});
    if(!blocked) { this.comboForce=combo>1?this.comboForce+row.forceN:row.forceN; this.maxComboForce=Math.max(this.maxComboForce,this.comboForce); }
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
''' + s[end:]
p.write_text(s, encoding='utf-8')

# Delete the heavy avatar hull machinery; retain static arena outlines.
p = root/'viewer/boxing_fx.js'; s=p.read_text(encoding='utf-8')
a=s.index('// Split normals'); b=s.index('function canvasTexture',a)
s=s[:a]+s[b:]; p.write_text(s,encoding='utf-8')

# Retain the arm IK and sole sampler, remove ALL secondary leg corrections.
p=root/'viewer/boxing_feet.js'; s=p.read_text(encoding='utf-8')
a=s.index('export class FootPlanting'); s=s[:a]
s+='''// Ground the root only. Leg bone rotations remain exactly the retarget result.
export function groundSoles(actor, dt = 1/60, canvasY = .026) {
  actor.group.updateMatrixWorld(true);
  const soles=['leftFoot','rightFoot'].map(n=>actor.rig.bones.get(n)?.bone).filter(Boolean).map(f=>soleBottom(actor,f));
  const bottom=Math.min(...soles);
  if(!Number.isFinite(bottom)) return null;
  const wanted=canvasY-bottom;
  actor.groundOffset ??= wanted;
  actor.groundOffset+=(wanted-actor.groundOffset)*(1-Math.exp(-Math.max(dt,.001)*16));
  // Low-pass small floor noise; bound lag to 8 mm, no accumulated drift.
  const offset=THREE.MathUtils.clamp(actor.groundOffset,wanted-.008,wanted+.008);
  actor.group.position.y+=offset;
  actor.group.updateMatrixWorld(true);
  return bottom+offset;
}
'''
s=s.replace(' || mesh.userData.cornerOutline','')
p.write_text(s,encoding='utf-8')

# Firm face contact without ears and without a precontact soft zone.
p=root/'viewer/avatar_self_contact.js'; s=p.read_text(encoding='utf-8')
s=s.replace('const SOFT_BAND = .02;', 'const SOFT_BAND = 0;')
s=s.replace(' || mesh.userData.cornerOutline','')
a=s.index('// C1 soft contact'); b=s.index('export class NativeGuardContact',a)
s=s[:a]+'''// Identity outside the skin: no attraction or precontact repulsion.
export function softContactGap(gap) { return Math.max(SKIN, gap); }

function facePoints(points) {
  if (points.length<20) return points;
  const sorted=points.map(p=>Math.abs(p.x)).sort((a,b)=>a-b);
  const cheek=sorted[Math.floor(sorted.length*.88)];
  // Clip lateral ear tips to cheek width rather than enclosing them in the face.
  return points.map(p=>new THREE.Vector3(THREE.MathUtils.clamp(p.x,-cheek,cheek),p.y,p.z));
}

''' + s[b:]
s=s.replace('this.headPoints = this.headBone ? sampleBoneSurface(actor, this.headBone) : [];','this.headPoints = this.headBone ? facePoints(sampleBoneSurface(actor, this.headBone)) : [];')
p.write_text(s,encoding='utf-8')
print('Core, avatar hull removal, root grounding and firm self-contact migrated.')
