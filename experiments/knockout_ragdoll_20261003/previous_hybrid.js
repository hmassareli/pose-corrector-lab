// Presentation-only, damped joint relaxation over a bounded root fall.
// No impact velocity is inherited and no physics impulse reaches either fighter.
import * as THREE from 'three';
import { knockoutMotion, clamp } from '/static/boxing_core.mjs';

const UP = new THREE.Vector3(0, 1, 0);
const FLOOR = .026;
const JOINT_LIMITS = [
  ['spine', .10], ['spine1', .10], ['spine2', .10],
  ['neck', .22], ['head', .18],
  ['leftArm', 1.35], ['leftForeArm', .75],
  ['rightArm', 1.25], ['rightForeArm', .70],
  ['leftUpLeg', .22], ['leftLeg', .35], ['leftFoot', .20],
  ['rightUpLeg', .18], ['rightLeg', .30], ['rightFoot', .18],
];

// Load-time support samples: extrema in 26 directions for each dominant skin
// bone. Unlike a full per-frame mesh scan this has a bounded, small runtime cost.
export function prepareKnockout(actor) {
  const limbBones=new Set();
  for(const name of ['leftArm','rightArm','leftUpLeg','rightUpLeg'])
    actor.rig.bones.get(name)?.bone.traverse(b=>limbBones.add(b));
  const directions=[];
  for(let x=-1;x<=1;x++)for(let y=-1;y<=1;y++)for(let z=-1;z<=1;z++)
    if(x||y||z)directions.push(new THREE.Vector3(x,y,z).normalize());
  actor.knockoutSurface=[];
  actor.root.traverse(mesh=>{
    if(!mesh.isSkinnedMesh)return;
    const {position,skinIndex,skinWeight}=mesh.geometry.attributes;
    if(!skinIndex||!skinWeight)return;
    const groups=new Map(),p=new THREE.Vector3();
    for(let i=0;i<position.count;i++){
      let dominant=0;
      for(let k=1;k<4;k++)if(skinWeight.getComponent(i,k)>skinWeight.getComponent(i,dominant))dominant=k;
      const id=skinIndex.getComponent(i,dominant);
      let group=groups.get(id);
      if(!group){group=directions.map(()=>({value:-Infinity,index:0}));groups.set(id,group);}
      p.fromBufferAttribute(position,i);
      for(let k=0;k<directions.length;k++){
        const value=p.dot(directions[k]);
        if(value>group[k].value){group[k].value=value;group[k].index=i;}
      }
    }
    const byBone=[...groups].map(([id,g])=>({bone:mesh.skeleton.bones[id],indices:[...new Set(g.map(p=>p.index))]}));
    const indices=[...new Set(byBone.flatMap(g=>g.indices))];
    const coreIndices=byBone.filter(g=>!limbBones.has(g.bone)).flatMap(g=>g.indices);
    actor.knockoutSurface.push({mesh,indices,coreIndices,byBone});
  });
}

export class KnockoutRelaxation {
  constructor(actor, fighter, away) {
    this.actor=actor;
    this.origin=new THREE.Vector3(fighter.x, FLOOR, fighter.z);
    this.yaw=fighter.yaw;
    this.power=clamp(fighter.reaction?.power ?? .5,0,1);
    this.direction=new THREE.Vector3(...(fighter.reaction?.dir || away));
    this.direction.y=0;
    if(!Number.isFinite(this.direction.lengthSq())||this.direction.lengthSq()<1e-8)this.direction.set(0,0,1);
    this.direction.normalize();
    // A boxer loses support mostly away from the opponent. Retain a lateral
    // component of the strike, but avoid a pure sideways cartwheel from an
    // unusually lateral glove normal (or stale network impact direction).
    const retreat=new THREE.Vector3(...away);retreat.y=0;
    if(Number.isFinite(retreat.lengthSq())&&retreat.lengthSq()>1e-8)
      this.direction.multiplyScalar(.25).addScaledVector(retreat.normalize(),.75).normalize();
    this.axis=new THREE.Vector3().crossVectors(UP,this.direction).normalize();
    this.pose=[];
    actor.root.traverse(b=>{if(b.isBone)this.pose.push({bone:b,position:b.position.clone(),quaternion:b.quaternion.clone()});});
    this.rootPosition=actor.root.position.clone();
    this.rootQuaternion=actor.root.quaternion.clone();
    this.joints=JOINT_LIMITS.flatMap(([name,limit])=>{
      const rest=actor.rig.bones.get(name);
      if(!rest?.child)return [];
      const contact=['leftArm','rightArm','leftUpLeg','rightUpLeg'].includes(name);
      const descendants=new Set();rest.bone.traverse(b=>descendants.add(b));
      const surface=contact?(actor.knockoutSurface||[]).map(s=>({mesh:s.mesh,indices:s.byBone.filter(g=>descendants.has(g.bone)).flatMap(g=>g.indices)})):null;
      return [{name,bone:rest.bone,child:rest.child,relaxLimit:limit,limit:contact?Math.PI:limit,surface,base:rest.bone.quaternion.clone(),
        rotation:new THREE.Vector3(),velocity:new THREE.Vector3()}];
    });
    this.time=0;
    this.point=new THREE.Vector3();
  }
  restore() {
    const a=this.actor;
    a.root.position.copy(this.rootPosition);a.root.quaternion.copy(this.rootQuaternion);
    for(const p of this.pose){p.bone.position.copy(p.position);p.bone.quaternion.copy(p.quaternion);}
  }
  bottom(surface, core=false) {
    const p=this.point;
    let low=Infinity;
    for(const entry of surface){
      const {mesh}=entry;mesh.skeleton.update();
      for(const i of core?entry.coreIndices:entry.indices){p.fromBufferAttribute(mesh.geometry.attributes.position,i);mesh.applyBoneTransform(i,p);mesh.localToWorld(p);low=Math.min(low,p.y);}
    }
    return low;
  }
  ground(core=false) {
    const a=this.actor,p=this.point;
    a.group.updateMatrixWorld(true);
    let low=this.bottom(a.knockoutSurface || [],core);
    // Exact existing face samples are retained for the final floor constraint.
    const head=a.rig.bones.get('head')?.bone;
    if(head)for(const sample of a.headSurface?.points || [])low=Math.min(low,p.copy(sample).applyMatrix4(head.matrixWorld).y);
    if(Number.isFinite(low))a.group.position.y+=FLOOR-low;
    a.group.updateMatrixWorld(true);
  }
  floorLimbs(dt) {
    // Unilateral contact: a limb touching the mat loses downward motion instead
    // of lifting the entire torso. Rotate a whole chain to preserve its elbow /
    // knee bend; only the shoulder/hip receives this contact correction.
    const a=this.actor;
    for(const j of this.joints){
      if(!j.surface?.length)continue;
      const q=j.bone.quaternion.clone(),parent=j.bone.parent.getWorldQuaternion(new THREE.Quaternion());
      j.contactQuaternion ??= q.clone();
      const origin=j.bone.getWorldPosition(new THREE.Vector3());
      const direction=j.child.getWorldPosition(new THREE.Vector3()).sub(origin).normalize();
      const full=new THREE.Quaternion().setFromUnitVectors(direction,UP);
      const apply=t=>{
        const delta=new THREE.Quaternion().slerp(full,t);
        delta.premultiply(parent.clone().invert()).multiply(parent);
        j.bone.quaternion.copy(q).premultiply(delta);a.group.updateMatrixWorld(true);
        return this.bottom(j.surface);
      };
      let lower=0,upper=0,best=0,bestLow=this.bottom(j.surface);
      if(bestLow<FLOOR+.004){
        // Find the first feasible arc interval. The minimum can be inside the
        // arc (a thick shoulder can intersect even with the limb pointing up).
        for(let k=1;k<=12;k++){
          const t=k/12,low=apply(t);
          if(low>bestLow){bestLow=low;best=t;}
          if(low>=FLOOR+.004){lower=(k-1)/12;upper=t;break;}
        }
        if(upper){
          for(let k=0;k<8;k++){const mid=(lower+upper)/2;if(apply(mid)<FLOOR+.004)lower=mid;else upper=mid;}
          apply(upper);
        }else apply(best);
      }
      // Bound contact correction speed as well as the free spring; changing
      // which skin point supports the body must not create a sudden launch.
      j.contactQuaternion.rotateTowards(j.bone.quaternion,2.8*dt);
      j.bone.quaternion.copy(j.contactQuaternion);a.group.updateMatrixWorld(true);
    }
  }
  update(seconds, dt) {
    if(this.settled){
      this.actor.group.position.copy(this.settled.position);
      this.actor.group.quaternion.copy(this.settled.quaternion);
      for(const p of this.settled.bones)p.bone.quaternion.copy(p.quaternion);
      this.actor.group.updateMatrixWorld(true);return;
    }
    this.restore();
    const a=this.actor,motion=knockoutMotion(Math.max(0,seconds-.12),this.power);
    a.group.quaternion.setFromAxisAngle(this.axis,motion.angle)
      .multiply(new THREE.Quaternion().setFromAxisAngle(UP,this.yaw));
    a.group.position.copy(this.origin).addScaledVector(this.direction,motion.distance);
    // Keep the bounded visual root inside the ring, including corner KOs.
    a.group.position.x=clamp(a.group.position.x,-2.55,2.55);
    a.group.position.z=clamp(a.group.position.z,-2.55,2.55);
    this.ground();
    const release=THREE.MathUtils.smoothstep(seconds,.10,.48);
    const step=Math.min(Math.max(Number.isFinite(dt)?dt:0,0),.05);
    for(const joint of this.joints){
      const {bone,child,base,relaxLimit:limit}=joint;
      a.group.updateMatrixWorld(true);
      const origin=bone.getWorldPosition(new THREE.Vector3());
      const direction=child.getWorldPosition(new THREE.Vector3()).sub(origin).normalize();
      // A residual restoring torque keeps the body articulated, not limp jelly.
      const gravity=new THREE.Vector3(0,-1,0);
      const target=direction.clone().lerp(gravity,.80).normalize();
      const parent=bone.parent.getWorldQuaternion(new THREE.Quaternion());
      const delta=new THREE.Quaternion().setFromUnitVectors(direction,target);
      delta.premultiply(parent.clone().invert()).multiply(parent).normalize();
      if(delta.w<0)delta.set(-delta.x,-delta.y,-delta.z,-delta.w);
      const angle=2*Math.acos(clamp(delta.w,-1,1));
      const goal=new THREE.Vector3(delta.x,delta.y,delta.z);
      if(goal.lengthSq()>1e-12)goal.normalize().multiplyScalar(Math.min(angle,limit)*release);
      // Critically damped angular spring, substepped at <= 1/120s. Speeds and
      // offsets are capped even after a long frame or a very powerful punch.
      const count=Math.max(1,Math.ceil(step*120)),h=step/count;
      for(let k=0;k<count;k++){
        joint.velocity.addScaledVector(goal.clone().sub(joint.rotation),55*h).multiplyScalar(Math.exp(-15*h));
        if(joint.velocity.length()>2.2)joint.velocity.setLength(2.2);
        joint.rotation.addScaledVector(joint.velocity,h);
        if(joint.rotation.length()>limit){joint.rotation.setLength(limit);joint.velocity.set(0,0,0);}
      }
      const amount=joint.rotation.length();
      bone.quaternion.copy(base);
      if(amount>1e-8)bone.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(joint.rotation.clone().divideScalar(amount),amount));
    }
    // Shift support gradually from shoes to torso during the collapse. The
    // early whole-body support preserves the impact pose without a root jump.
    const wholeY=a.group.position.y;
    this.ground(true);
    const torsoY=a.group.position.y;
    a.group.position.y=THREE.MathUtils.lerp(wholeY,torsoY,THREE.MathUtils.smoothstep(seconds,.40,1.25));
    a.group.updateMatrixWorld(true);
    this.floorLimbs(step);
    // Small residual skin contact (e.g. the shoulder seam) is corrected last.
    this.ground();
    this.time=seconds;
    if(seconds>=3 && this.joints.every(j=>j.velocity.lengthSq()<.0001)){
      this.settled={position:a.group.position.clone(),quaternion:a.group.quaternion.clone(),
        bones:this.pose.map(p=>({bone:p.bone,quaternion:p.bone.quaternion.clone()}))};
    }
  }
  reset() { this.restore(); }
}
