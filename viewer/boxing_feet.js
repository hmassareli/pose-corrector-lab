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
// Length-preserving two-bone IK used exclusively for glove/arm corrections.
function solveTwoBone(hip,knee,foot,target,forward=new THREE.Vector3(0,0,1)) {
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
export { solveTwoBone };
// Must run in the standing neutral pose: the sole is chosen as the lowest shoe vertices.
export function prepareFeet(actor) {
  for (const n of ['leftFoot', 'rightFoot']) {
    const foot = actor.rig.bones.get(n)?.bone;
    if (foot) clearanceOf(actor, foot);
  }
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
// Ground the root only. Leg bone rotations remain exactly the retarget result.
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
