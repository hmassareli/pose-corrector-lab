import * as THREE from 'three';

const position = bone => bone.getWorldPosition(new THREE.Vector3());
function clearanceOf(actor,foot) {
  actor.nativeSoles ??= new Map();
  if(!actor.nativeSoles.has(foot)) {
    const points=[];
    actor.root.traverse(mesh=>{
      if(!mesh.isSkinnedMesh || !mesh.geometry.attributes.skinWeight) return;
      mesh.skeleton.update();
      const ids=new Set();
      foot.traverse(bone=>{const id=mesh.skeleton.bones.indexOf(bone);if(id>=0)ids.add(id);});
      const {position:vertices,skinIndex,skinWeight}=mesh.geometry.attributes;
      for(let i=0;i<vertices.count;i++) {
        let weight=0;
        for(let c=0;c<4;c++) if(ids.has(skinIndex.getComponent(i,c))) weight+=skinWeight.getComponent(i,c);
        if(weight<.4) continue;
        const point=new THREE.Vector3().fromBufferAttribute(vertices,i);
        mesh.applyBoneTransform(i,point);mesh.localToWorld(point);
        if(point.distanceTo(position(foot))<.4) {
          point.skinMesh=mesh;point.vertexIndex=i;points.push(point);
        }
      }
    });
    const bottom=Math.min(...points.map(p=>p.y));
    // Dense meshes put thousands of vertices on a sole; ~64 evenly spread ones
    // keep per-frame skinning checks cheap without losing heel or toe.
    const all=points.filter(p=>p.y<bottom+.025);
    const sole=all.filter((_,k)=>k%Math.max(1,Math.floor(all.length/64))===0);
    actor.nativeSoleVertices ??= new Map();
    actor.nativeSoleVertices.set(foot,sole.map(p=>({mesh:p.skinMesh,index:p.vertexIndex})));
    actor.nativeSoles.set(foot,sole.map(p=>foot.worldToLocal(p)));
  }
  const samples=actor.nativeSoles.get(foot), origin=position(foot);
  const bottom=samples.length ? Math.min(...samples.map(p=>p.clone().applyMatrix4(foot.matrixWorld).y))
    : Math.min(origin.y,...foot.children.map(n=>position(n).y));
  return Math.max(.025,origin.y-bottom);
}
function aim(bone, child, target) {
  const origin=position(bone), current=position(child).sub(origin).normalize();
  const desired=target.clone().sub(origin).normalize();
  const delta=new THREE.Quaternion().setFromUnitVectors(current,desired);
  const parent=bone.parent.getWorldQuaternion(new THREE.Quaternion());
  bone.quaternion.premultiply(parent.clone().invert().multiply(delta).multiply(parent));
  bone.updateWorldMatrix(false,true);
}
// Solve only the legs after retargeting: arms continue to receive the latest
// pose without a locomotion animation or additional smoothing stage.
function solveLeg(hip,knee,foot,target,forward=new THREE.Vector3(0,0,1)) {
  const h=position(hip), k=position(knee), f=position(foot);
  const upper=h.distanceTo(k), lower=k.distanceTo(f);
  const direction=target.clone().sub(h), requested=direction.length();
  if(upper<.01 || lower<.01 || requested<.01) return false;
  const distance=THREE.MathUtils.clamp(requested,Math.abs(upper-lower)+.001,upper+lower-.001);
  direction.normalize();
  const along=(upper*upper-lower*lower+distance*distance)/(2*distance);
  const bend=Math.sqrt(Math.max(0,upper*upper-along*along));
  let pole=k.clone().sub(h).addScaledVector(direction,-k.clone().sub(h).dot(direction));
  if(pole.lengthSq()<1e-6) pole=forward.clone().addScaledVector(direction,-forward.dot(direction));
  pole.normalize();
  const kneeTarget=h.clone().addScaledVector(direction,along).addScaledVector(pole,bend);
  aim(hip,knee,kneeTarget);
  aim(knee,foot,h.clone().addScaledVector(direction,distance));
  return requested<=upper+lower+.015;
}
export { solveLeg as solveTwoBone };
// Must run in the standing neutral pose: the sole is chosen as the lowest shoe vertices.
export function prepareFeet(actor) {
  for (const n of ['leftFoot', 'rightFoot']) {
    const foot = actor.rig.bones.get(n)?.bone;
    if (foot) clearanceOf(actor, foot);
  }
}
// Pitches each foot until the shoe's heel and toe undersides are level, and
// returns that orientation in the fighter's frame (actor.group must be identity).
export function levelFeet(actor) {
  return ['leftFoot', 'rightFoot'].map((n) => {
    const foot = actor.rig.bones.get(n)?.bone;
    if (!foot) return null;
    const verts = [];
    actor.root.traverse((mesh) => {
      if (!mesh.isSkinnedMesh || mesh.userData.cornerOutline || !mesh.geometry.attributes.skinWeight) return;
      const ids = new Set();
      foot.traverse((b) => { const i = mesh.skeleton.bones.indexOf(b); if (i >= 0) ids.add(i); });
      const { position: pos, skinIndex, skinWeight } = mesh.geometry.attributes;
      const step = Math.max(1, Math.floor(pos.count / 200000));
      for (let i = 0; i < pos.count; i += step) {
        let w = 0;
        for (let c = 0; c < 4; c++) if (ids.has(skinIndex.getComponent(i, c))) w += skinWeight.getComponent(i, c);
        if (w >= .5) verts.push({ mesh, index: i });
      }
    });
    const sample = () => {
      const pts = [], updated = new Set();
      for (const { mesh, index } of verts) {
        if (!updated.has(mesh)) { mesh.skeleton.update(); updated.add(mesh); }
        const p = new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, index);
        mesh.applyBoneTransform(index, p); mesh.localToWorld(p); pts.push(p);
      }
      return pts;
    };
    for (let pass = 0; pass < 4 && verts.length; pass++) {
      const pts = sample(), zs = pts.map((p) => p.z), z0 = Math.min(...zs), z1 = Math.max(...zs), span = z1 - z0;
      if (span < .05) break;
      const low = (a, b) => Math.min(...pts.filter((p) => p.z >= z0 + span * a && p.z <= z0 + span * b).map((p) => p.y));
      const pitch = Math.atan2(low(0, .25) - low(.75, 1), span * .75);
      if (Math.abs(pitch) < .005) break;
      setWorldRotation(foot, new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -pitch).multiply(foot.getWorldQuaternion(new THREE.Quaternion())));
    }
    return foot.getWorldQuaternion(new THREE.Quaternion());
  });
}
const FLOOR = .026;
function setWorldRotation(bone, q) {
  bone.quaternion.copy(bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(q));
  bone.updateWorldMatrix(false, true);
}
// Lowest skinned sole point: the shoe, not the ankle bone, touches the canvas.
export function soleBottom(actor, foot) {
  clearanceOf(actor, foot);
  const samples = actor.nativeSoleVertices?.get(foot) || [];
  const updated = new Set();
  let bottom = Infinity;
  for (let k = 0; k < samples.length; k++) {
    const { mesh, index } = samples[k];
    if (!updated.has(mesh)) { mesh.skeleton.update(); updated.add(mesh); }
    const p = new THREE.Vector3().fromBufferAttribute(mesh.geometry.attributes.position, index);
    mesh.applyBoneTransform(index, p); mesh.localToWorld(p);
    bottom = Math.min(bottom, p.y);
  }
  return bottom;
}
export class FootPlanting {
  constructor() { this.reset(); }
  reset() { this.anchors=[null,null]; this.inferred=null; this.hipLift=0; this.mapping=[null,null]; }
  apply(actor,fighter,now=performance.now()) {
    actor.group.updateWorldMatrix(true,true);
    const legs=['left','right'].map(side=>({
      hip:actor.rig.bones.get(side+'UpLeg')?.bone,
      knee:actor.rig.bones.get(side+'Leg')?.bone,
      foot:actor.rig.bones.get(side+'Foot')?.bone,
    }));
    if(legs.some(l=>!l.hip || !l.knee || !l.foot)) return;
    if(fighter.proceduralFeet || fighter.footVisible?.some(v=>!v)) {
      this.applyInferred(actor,legs,now);
      return;
    }
    // No tracking data (menu, paused bot): leave the retargeted legs alone.
    if(!fighter.footContacts) { this.reset(); return; }
    if(this.inferred) { this.inferred=null; this.anchors=[null,null]; this.mapping=[null,null]; }
    this.hipLift=0;
    // Visible feet follow NLF. A foot NLF reports as supported keeps its spot
    // (no skating) with the real skinned sole resting on the canvas; a lifted
    // foot is untouched unless its sole would go through the canvas.
    legs.forEach((leg,h)=>{
      const rotation=leg.foot.getWorldQuaternion(new THREE.Quaternion());
      const forward=actor.group.getWorldDirection(new THREE.Vector3());
      // NLF hip->foot offset mapped onto the avatar; fixed from the first frame,
      // when the foot stands on the canvas.
      if(!this.mapping[h] && fighter.pose?.[5+h]) {
        const pose=fighter.pose, orientation=actor.group.getWorldQuaternion(new THREE.Quaternion());
        const sHip=new THREE.Vector3(...pose[1+h]), sKnee=new THREE.Vector3(...pose[3+h]), sFoot=new THREE.Vector3(...pose[5+h]);
        const foot=position(leg.foot).setY(FLOOR+clearanceOf(actor,leg.foot));
        const scale=(position(leg.hip).distanceTo(position(leg.knee))+position(leg.knee).distanceTo(position(leg.foot)))/
          Math.max(.1,sHip.distanceTo(sKnee)+sKnee.distanceTo(sFoot));
        const expected=sFoot.sub(sHip).multiplyScalar(scale).applyQuaternion(orientation).add(position(leg.hip));
        this.mapping[h]={scale,offset:foot.sub(expected).applyQuaternion(orientation.invert())};
      }
      if(fighter.footContacts?.[h]) {
        const p=position(leg.foot);
        this.anchors[h]??={point:p.clone(),rotation:rotation.clone()};
        const target=new THREE.Vector3(this.anchors[h].point.x,p.y,this.anchors[h].point.z);
        for(let pass=0;pass<3;pass++) {
          if(!solveLeg(leg.hip,leg.knee,leg.foot,target,forward)) { this.anchors[h]=null; break; }
          setWorldRotation(leg.foot,this.anchors[h].rotation);
          const error=FLOOR-soleBottom(actor,leg.foot);
          if(Math.abs(error)<.003) break;
          target.y+=error;
        }
        return;
      }
      this.anchors[h]=null;
      // A lifted foot goes where NLF puts it (direction-only retargeting keeps
      // a raised foot almost on the floor), scaled to the avatar's legs.
      const pose=fighter.pose, orientation=actor.group.getWorldQuaternion(new THREE.Quaternion());
      if(pose?.[5+h] && this.mapping[h]) {
        const sourceHip=new THREE.Vector3(...pose[1+h]), sourceFoot=new THREE.Vector3(...pose[5+h]);
        const {scale,offset}=this.mapping[h];
        const target=sourceFoot.sub(sourceHip).multiplyScalar(scale).add(offset).applyQuaternion(orientation).add(position(leg.hip));
        solveLeg(leg.hip,leg.knee,leg.foot,target,forward);
        setWorldRotation(leg.foot,rotation);
      }
      const depth=FLOOR-soleBottom(actor,leg.foot);
      if(!(depth>.002)) return;
      solveLeg(leg.hip,leg.knee,leg.foot,position(leg.foot).add(new THREE.Vector3(0,depth,0)),forward);
      setWorldRotation(leg.foot,rotation);
    });
  }
  // Feet out of the camera: flat feet under the body, near-straight legs and
  // small, low steps that keep the stance as the fighter moves.
  applyInferred(actor,legs,now) {
    const group=actor.group.getWorldQuaternion(new THREE.Quaternion());
    const flat=h=>actor.flatFeet?.[h] ? group.clone().multiply(actor.flatFeet[h]) : legs[h].foot.getWorldQuaternion(new THREE.Quaternion());
    legs.forEach((leg,h)=>setWorldRotation(leg.foot,flat(h)));
    if(!this.inferred) {
      this.inferred={swing:null,offsets:[]};
      legs.forEach((leg,h)=>{
        const p=position(leg.foot).setY(FLOOR+clearanceOf(actor,leg.foot));
        this.anchors[h]={point:p};
        this.inferred.offsets[h]=actor.group.worldToLocal(p.clone());
      });
    }
    const gait=this.inferred;
    const home=h=>actor.group.localToWorld(gait.offsets[h].clone()).setY(this.anchors[h].point.y);
    if(!gait.swing) {
      const error=[0,1].map(h=>home(h).sub(this.anchors[h].point).setY(0).length());
      const h=error[0]>=error[1]?0:1;
      if(error[h]>.14) gait.swing={h,start:now,from:this.anchors[h].point.clone()};
    }
    const targets=this.anchors.map(a=>a.point.clone());
    if(gait.swing) {
      const {h,from,start}=gait.swing, u=THREE.MathUtils.clamp((now-start)/300,0,1), s=u*u*(3-2*u);
      targets[h].lerpVectors(from,home(h),s);
      targets[h].y+=Math.sin(u*Math.PI)*.035;
      if(u===1) { this.anchors[h].point.copy(home(h)); gait.swing=null; }
    }
    // Pelvis height: never above leg reach (no floating); a shallow bend is
    // straightened, a deliberate duck (deep bend) is kept.
    let slack=Infinity;
    legs.forEach((leg,h)=>{
      const hip=position(leg.hip), reach=(hip.distanceTo(position(leg.knee))+position(leg.knee).distanceTo(position(leg.foot)))*.97;
      const flatDistance=Math.hypot(hip.x-targets[h].x,hip.z-targets[h].z);
      // A foot out of horizontal reach cannot be fixed by sinking the pelvis.
      if(flatDistance>=reach) return;
      slack=Math.min(slack,targets[h].y+Math.sqrt(reach*reach-flatDistance*flatDistance)-hip.y);
    });
    if(!Number.isFinite(slack)) slack=0;
    const lift=THREE.MathUtils.clamp(slack<0 ? slack : slack*.8*THREE.MathUtils.clamp(1-(slack-.1)/.15,0,1),-.12,.12);
    this.hipLift+=(lift-this.hipLift)*(lift<this.hipLift ? 1 : .2);
    actor.root.position.y+=this.hipLift/actor.group.getWorldScale(new THREE.Vector3()).y;
    actor.group.updateWorldMatrix(true,true);
    legs.forEach((leg,h)=>{
      solveLeg(leg.hip,leg.knee,leg.foot,targets[h],actor.group.getWorldDirection(new THREE.Vector3()));
      setWorldRotation(leg.foot,flat(h));
    });
    // The shoe is partly skinned to the calf, so the real sole moves with the
    // ankle angle: measure it and correct this frame only (no anchor drift).
    for(let pass=0;pass<2;pass++) legs.forEach((leg,h)=>{
      const error=FLOOR-soleBottom(actor,leg.foot);
      if(Math.abs(error)<.003 || (gait.swing?.h===h && error<0)) return;
      targets[h].y+=error;
      solveLeg(leg.hip,leg.knee,leg.foot,targets[h],actor.group.getWorldDirection(new THREE.Vector3()));
      setWorldRotation(leg.foot,flat(h));
    });
  }
}
