import * as THREE from "three";

const states = new WeakMap();
const X = new THREE.Vector3(1, 0, 0);
const Y = new THREE.Vector3(0, 1, 0);
const rad = THREE.MathUtils.degToRad;
const finite = v => v?.isVector3 && [v.x, v.y, v.z].every(Number.isFinite);

// The skull joint is a pivot, not the gaze direction. Two nonparallel facial
// vectors recover all three DOFs even when neck/head positions do not move.
function facialFrame(aux) {
  if (!finite(aux?.left_eye) || !finite(aux?.right_eye)) return null;
  const center = aux.left_eye.clone().add(aux.right_eye).multiplyScalar(0.5);
  const across = aux.left_eye.clone().sub(aux.right_eye);
  const span = across.length();
  if (span < 0.02 || span > 0.14) return null;
  across.divideScalar(span);
  const pivot = finite(aux.head) ? aux.head
    : finite(aux.left_ear) && finite(aux.right_ear)
      ? aux.left_ear.clone().add(aux.right_ear).multiplyScalar(0.5) : null;
  if (!pivot) return null;
  const forward = center.clone().sub(pivot);
  if (forward.length() < 0.015 || forward.length() > 0.20) return null;
  forward.addScaledVector(across, -forward.dot(across));
  if (forward.length() < 0.015) return null;
  // Jaw is another anatomical consistency check, not an assumed chin/up axis:
  // SMPL-X jaw is a rotation pivot and can be almost coincident with the skull.
  if (finite(aux.jaw) && center.distanceTo(aux.jaw) > 0.22) return null;
  forward.normalize();
  const up = new THREE.Vector3().crossVectors(forward, across).normalize();
  return {
    forward, up, span,
    rotation: new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(across, up, forward)),
  };
}

function limited(q, yaw, pitch, roll) {
  const e = new THREE.Euler().setFromQuaternion(q, "YXZ");
  e.set(THREE.MathUtils.clamp(e.x, -rad(pitch[0]), rad(pitch[1])),
    THREE.MathUtils.clamp(e.y, -rad(yaw), rad(yaw)),
    THREE.MathUtils.clamp(e.z, -rad(roll), rad(roll)), "YXZ");
  return new THREE.Quaternion().setFromEuler(e);
}

export function resetHeadCalibration(rig) { states.delete(rig); }
export function getHeadRetargetDiagnostics(rig) {
  const s = states.get(rig);
  return s ? { status: s.status, pitchOffsetDegrees: THREE.MathUtils.radToDeg(s.pitchOffset || 0),
    accepted: s.accepted, rejected: s.rejected, faceRelative: s.relative?.toArray() || null } : null;
}

export function headFacingFromAux(aux) {
  return facialFrame(aux)?.forward || null;
}

export function resolveHeadPose(rig, aux, { torso, cervicalUp, time, sampleTime, motion, calibrationKey }) {
  let s = states.get(rig);
  if (!s || s.motion !== motion || s.epoch !== motion.headCalibrationEpoch || s.calibrationKey !== calibrationKey) {
    s = { motion, calibrationKey, epoch: motion.headCalibrationEpoch, pitchOffset: null,
      relative: new THREE.Quaternion(), face: null, goodTime: null,
      sampleTime: null, pending: null, recovering: null, output: null,
      accepted: 0, rejected: 0, status: "body" };
    states.set(rig, s);
  }
  const measurement = facialFrame(aux);
  let candidate = measurement?.rotation.clone() || null;
  if (measurement && s.pitchOffset == null) {
    const up = finite(cervicalUp) ? cervicalUp.clone().normalize() : Y.clone().applyQuaternion(torso);
    // Remove only the anatomical eye-to-pivot pitch offset. Preserve measured
    // yaw/roll; calibration must not force every first face to torso-forward.
    s.pitchOffset = THREE.MathUtils.clamp(Math.atan2(measurement.forward.dot(up), measurement.up.dot(up)), -rad(45), rad(45));
  }
  if (candidate) candidate.multiply(new THREE.Quaternion().setFromAxisAngle(X, s.pitchOffset));
  const newSample = sampleTime == null || s.sampleTime == null || sampleTime > s.sampleTime;
  let accepted = !!candidate;
  // Repainting an old pose must not keep refreshing facial confidence.
  if (!newSample && sampleTime != null && time - sampleTime > 300) {
    accepted = false;
    s.status = "held";
  }
  if (candidate && newSample && s.face && sampleTime != null && s.sampleTime != null) {
    const dt = Math.max(0, (sampleTime - s.sampleTime) / 1000);
    const maxChange = rad(15) + 18 * Math.min(dt, 0.15);
    if (s.face.angleTo(candidate) > maxChange) {
      // A single flip is not a head turn. A coherent next observation may be a
      // real fast move/recovery and is allowed through with a short transition.
      accepted = !!s.pending && s.pending.angleTo(candidate) < rad(8);
      if (!accepted) s.pending = candidate.clone();
    } else s.pending = null;
  }
  if (newSample) {
    if (accepted) {
      if (s.output && s.status !== "tracked") s.recovering = { from: s.output.clone(), start: time };
      s.face = candidate;
      s.relative = torso.clone().invert().multiply(candidate);
      s.goodTime = time;
      s.accepted++;
      s.status = "tracked";
      s.pending = null;
    } else {
      s.rejected++;
      s.status = "held";
    }
    s.sampleTime = sampleTime;
  }
  let face;
  if (accepted && s.face) face = s.face.clone();
  else {
    const age = s.goodTime == null ? Infinity : Math.max(0, (time - s.goodTime) / 1000);
    const retention = age <= 0.22 ? 1 : Math.exp(-(age - 0.22) / 0.45);
    face = torso.clone().multiply(new THREE.Quaternion().slerp(s.relative, retention));
    if (retention < 0.01) s.status = "body";
  }
  if (s.recovering && accepted) {
    const t = THREE.MathUtils.clamp((time - s.recovering.start) / 120, 0, 1);
    face = s.recovering.from.clone().slerp(face, t * t * (3 - 2 * t));
    if (t === 1) s.recovering = null;
  }
  face = torso.clone().multiply(limited(torso.clone().invert().multiply(face), 85, [55, 65], 45));
  // Continue from the FINAL thoracic pose. Cervical position contributes bend;
  // independent facial rotation is then shared without attenuating final gaze.
  const torsoUp = Y.clone().applyQuaternion(torso);
  const swing = finite(cervicalUp) && cervicalUp.lengthSq() > 1e-6
    ? new THREE.Quaternion().setFromUnitVectors(torsoUp, cervicalUp.clone().normalize()) : new THREE.Quaternion();
  const base = new THREE.Quaternion().slerp(swing, 0.45).multiply(torso);
  let neck = base.clone().multiply(new THREE.Quaternion().slerp(base.clone().invert().multiply(face), 0.4));
  neck = torso.clone().multiply(limited(torso.clone().invert().multiply(neck), 40, [30, 35], 22));
  face = neck.clone().multiply(limited(neck.clone().invert().multiply(face), 65, [45, 45], 35));
  s.output = face.clone();
  return { neck, head: face };
}
