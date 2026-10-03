import * as THREE from 'three';
import { signedTwist } from '/static/avatar_twist_audit.js';
const at=b=>b.getWorldPosition(new THREE.Vector3());
// Build the native hand basis from finger bones once. No world orientation is
// carried across an IK edit, so the wrist cannot counter-bend with a moved elbow.
export function prepareHands(actor) {
  actor.handBasis=['left','right'].map(side=>{
    const hand=actor.rig.bones.get(side+'Hand')?.bone;
    if(!hand) return null;
    const find=part=>{let result;hand.traverse(b=>{if(b.isBone&&new RegExp(part+'1$','i').test(b.name))result=b;});return result;};
    const middle=find('Middle'),index=find('Index'),pinky=find('Pinky');
    const local=b=>hand.worldToLocal(at(b));
    const axis=middle?local(middle).normalize():new THREE.Vector3(0,1,0);
    // Mixamo hand frames mirror across local X, so the fallback must mirror too.
    let across=index&&pinky?local(index).sub(local(pinky)).normalize():new THREE.Vector3(side==='right'?1:-1,0,0);
    let palm=axis.clone().cross(across).normalize();
    // Both Mixamo hands use the finger fan, with mirrored palm handedness.
    if(side==='right')palm.negate();
    const x=axis.clone().cross(palm).normalize();palm=x.clone().cross(axis).normalize();
    const basis=new THREE.Matrix4().makeBasis(x,axis,palm);
    return {hand,axis,palm,inverse:new THREE.Quaternion().setFromRotationMatrix(basis).invert()};
  });
}
export function alignWrist(actor,h) {
  const basis=actor.handBasis?.[h],side=h?'right':'left';
  const fore=actor.rig.bones.get(side+'ForeArm')?.bone;
  if(!basis||!fore)return;
  const axis=at(basis.hand).sub(at(fore)).normalize();
  const head=actor.rig.bones.get('head')?.bone;
  const inward=actor.group.getWorldDirection(new THREE.Vector3()).negate();
  const towardOther=new THREE.Vector3(h?1:-1,0,0).applyQuaternion(actor.group.getWorldQuaternion(new THREE.Quaternion()));
  // Forty-five degrees inward/backward in the fighter frame; project onto the
  // forearm's normal plane so raising an elbow rolls the whole glove naturally.
  // A ray parallel to the forearm (straight jab) has no usable projection: fade
  // its weight out instead of normalizing noise, which flipped the palm.
  const usable=v=>{v.addScaledVector(axis,-v.dot(axis));const len=v.length();return len<1e-6?v.set(0,0,0):v.multiplyScalar(Math.min(1,len/.35)/len);};
  let palm=usable(inward).add(usable(towardOther));
  if(palm.lengthSq()<1e-5)palm=at(head||fore).sub(at(basis.hand)).addScaledVector(axis,-at(head||fore).sub(at(basis.hand)).dot(axis));
  if(palm.lengthSq()<1e-5)palm=new THREE.Vector3(0,1,0).cross(axis);
  palm.normalize();const x=axis.clone().cross(palm).normalize();palm=x.clone().cross(axis).normalize();
  const desired=new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,axis,palm)).multiply(basis.inverse);
  basis.hand.quaternion.copy(basis.hand.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(desired));
  basis.hand.updateWorldMatrix(false,true);
  shareForearmTwist(actor,side);
}
// Rolling the forearm about its own axis leaves the wrist in place; split the
// roll evenly with the hand (a software twist bone) so neither wraps the mesh.
function shareForearmTwist(actor,side) {
  const fore=actor.rig.bones.get(side+'ForeArm'),hand=actor.rig.bones.get(side+'Hand');
  if(!fore?.restLocalDirection||!hand?.restLocalDirection)return;
  const wrap=d=>((d+540)%360)-180;
  // Twist is periodic: share the shortest equivalent total roll, not the raw sum.
  const fore0=signedTwist(fore),theta=wrap(wrap(fore0+signedTwist(hand))/2-fore0);
  if(Math.abs(theta)<1)return;
  const world=hand.bone.getWorldQuaternion(new THREE.Quaternion());
  fore.bone.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(fore.restLocalDirection,THREE.MathUtils.degToRad(theta)));
  fore.bone.updateWorldMatrix(false,true);
  hand.bone.quaternion.copy(hand.bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(world));
  hand.bone.updateWorldMatrix(false,true);
}
export function alignWrists(actor){for(let h=0;h<2;h++)alignWrist(actor,h);}
