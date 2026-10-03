import * as THREE from 'three';
// Per-bone twist about its own rest axis, relative to the parent (degrees).
// Beyond ~110 deg on one bone, linear-blend skinning collapses the limb ("candy wrap").
export const TWIST_LIMIT_DEG = 110;
const LIMBS = ['leftArm', 'leftForeArm', 'leftHand', 'rightArm', 'rightForeArm', 'rightHand',
  'leftUpLeg', 'leftLeg', 'leftFoot', 'rightUpLeg', 'rightLeg', 'rightFoot'];
const delta = new THREE.Quaternion(), axis = new THREE.Vector3(), twist = new THREE.Quaternion();
// Signed twist in (-180, 180] degrees about the bone's own rest axis.
export function signedTwist(rest) {
  delta.copy(rest.restLocalQuaternion).invert().multiply(rest.bone.quaternion);
  axis.copy(rest.restLocalDirection);
  const p = axis.x * delta.x + axis.y * delta.y + axis.z * delta.z;
  let deg = THREE.MathUtils.radToDeg(2 * Math.atan2(p, delta.w));
  if (deg > 180) deg -= 360; else if (deg <= -180) deg += 360;
  return deg;
}
export function twistDegrees(rest) {
  return Math.abs(signedTwist(rest));
}
export function twistReport(rig) {
  const out = {};
  for (const name of LIMBS) {
    const rest = rig.bones.get(name);
    if (rest?.restLocalDirection) out[name] = twistDegrees(rest);
  }
  return out;
}
