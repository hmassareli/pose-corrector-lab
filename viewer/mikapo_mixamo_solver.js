/**
 * MiKaPo-style FK retarget for Mixamo FBX (Three.js).
 *
 * Port of AmyangXYZ/MiKaPo solver ideas:
 * - rest-pose calibration (parent→child directions)
 * - direction solve via FromUnitVectors in root/parent space
 * - roll witness (forearm/shin pins upper-arm/thigh roll)
 * - trunk Gram-Schmidt basis (hips / spine)
 * - feet: yaw-from-dir (twist about up only) + plant soles on ground
 * - head: ears/eyes Gram-Schmidt basis (Pose-33)
 * - hands: palm aim from wrist/index/pinky (Pose-33; no finger curl)
 * - One-Euro on bone local quaternions
 *
 * Not a line-for-line copy: MMD / fingers / face morphs omitted.
 */

import * as THREE from "three";

const MIN_DIR = 1e-6;
const WITNESS_FADE_LO = 0.15;
const WITNESS_FADE_HI = 0.35;

/** MediaPipe Pose-33 indices used for head / palm aux (viewer-space after YZ flip). */
export const MP_AUX = {
  nose: 0,
  left_eye: 2,
  right_eye: 5,
  left_ear: 7,
  right_ear: 8,
  left_wrist: 15,
  right_wrist: 16,
  left_pinky: 17,
  right_pinky: 18,
  left_index: 19,
  right_index: 20,
  left_thumb: 21,
  right_thumb: 22,
};

/** Flip OpenCV-ish MediaPipe world → lab viewer (Y-up, Z flip). */
export function flipMpPointToViewer(p) {
  return new THREE.Vector3(p.x ?? p[0], -(p.y ?? p[1]), -(p.z ?? p[2]));
}

// ---------------------------------------------------------------------------
// One-Euro
// ---------------------------------------------------------------------------

class OneEuroFilter {
  constructor(minCutoff = 1.5, beta = 1.5, dCutoff = 1.0) {
    this.minCutoff = minCutoff;
    this.beta = beta;
    this.dCutoff = dCutoff;
    this.prev = null;
    this.prevDeriv = 0;
    this.prevTs = null;
  }

  filter(value, ts) {
    if (this.prev === null || this.prevTs === null) {
      this.prev = value;
      this.prevTs = ts;
      return value;
    }
    const dt = (ts - this.prevTs) / 1000;
    if (dt <= 0 || dt > 1.0) {
      this.prev = value;
      this.prevDeriv = 0;
      this.prevTs = ts;
      return value;
    }
    const rawDeriv = (value - this.prev) / dt;
    const aD = OneEuroFilter.smoothing(this.dCutoff, dt);
    const filteredDeriv = aD * rawDeriv + (1 - aD) * this.prevDeriv;
    const cutoff = this.minCutoff + this.beta * Math.abs(filteredDeriv);
    const a = OneEuroFilter.smoothing(cutoff, dt);
    const filtered = a * value + (1 - a) * this.prev;
    this.prev = filtered;
    this.prevDeriv = filteredDeriv;
    this.prevTs = ts;
    return filtered;
  }

  reset() {
    this.prev = null;
    this.prevDeriv = 0;
    this.prevTs = null;
  }

  static smoothing(cutoff, dt) {
    const tau = 1 / (2 * Math.PI * cutoff);
    return 1 / (1 + tau / dt);
  }
}

class QuaternionOneEuroFilter {
  constructor(minCutoff = 1.5, beta = 1.5, dCutoff = 1.0) {
    this.fx = new OneEuroFilter(minCutoff, beta, dCutoff);
    this.fy = new OneEuroFilter(minCutoff, beta, dCutoff);
    this.fz = new OneEuroFilter(minCutoff, beta, dCutoff);
    this.fw = new OneEuroFilter(minCutoff, beta, dCutoff);
    this.prev = new THREE.Quaternion();
    this.hasPrev = false;
  }

  filter(q, ts) {
    let { x, y, z, w } = q;
    if (this.hasPrev && this.prev.dot(q) < 0) {
      x = -x;
      y = -y;
      z = -z;
      w = -w;
    }
    const out = new THREE.Quaternion(
      this.fx.filter(x, ts),
      this.fy.filter(y, ts),
      this.fz.filter(z, ts),
      this.fw.filter(w, ts),
    ).normalize();
    this.prev.copy(out);
    this.hasPrev = true;
    return out;
  }

  reset() {
    this.fx.reset();
    this.fy.reset();
    this.fz.reset();
    this.fw.reset();
    this.hasPrev = false;
  }
}

// ---------------------------------------------------------------------------
// Rig helpers
// ---------------------------------------------------------------------------

function normalizedBoneName(name) {
  return (name || "").toLowerCase().replace(/[^a-z]/g, "");
}

function findAvatarBone(bones, aliases) {
  const matching = bones.filter((bone) =>
    aliases.some((alias) => normalizedBoneName(bone.name).endsWith(alias)),
  );
  return (
    matching.find((bone) =>
      bone.children.some((child) => child.isBone || child.type === "Bone"),
    ) ||
    matching[0] ||
    null
  );
}

/** Build Mixamo rig map with rest caches + MiKaPo-style witness rest vectors. */
export function buildAvatarRig(model) {
  const allBones = [];
  model.traverse((node) => {
    if (node.isBone || node.type === "Bone") allBones.push(node);
  });
  const specs = [
    ["hips", ["hips"], ["spine"]],
    ["spine", ["spine"]],
    ["spine1", ["spine1"]],
    ["spine2", ["spine2"]],
    ["neck", ["neck"]],
    ["head", ["head"]],
    ["leftArm", ["leftarm"]],
    ["leftForeArm", ["leftforearm"]],
    ["rightArm", ["rightarm"]],
    ["rightForeArm", ["rightforearm"]],
    ["leftShoulder", ["leftshoulder"], ["leftarm"]],
    ["rightShoulder", ["rightshoulder"], ["rightarm"]],
    ["leftHand", ["lefthand"], ["lefthandmiddle1", "lefthandindex1"]],
    ["rightHand", ["righthand"], ["righthandmiddle1", "righthandindex1"]],
    ["leftUpLeg", ["leftupleg", "leftthigh"]],
    ["leftLeg", ["leftleg", "leftcalf"]],
    ["rightUpLeg", ["rightupleg", "rightthigh"]],
    ["rightLeg", ["rightleg", "rightcalf"]],
    ["leftFoot", ["leftfoot"], ["lefttoebase", "lefttoe"]],
    ["rightFoot", ["rightfoot"], ["righttoebase", "righttoe"]],
  ];
  model.updateWorldMatrix(true, true);
  const inverseRoot = model.getWorldQuaternion(new THREE.Quaternion()).invert();
  const bones = new Map();
  for (const [key, aliases, childAliases] of specs) {
    const bone = findAvatarBone(allBones, aliases);
    const children = bone?.children.filter((node) => {
      if (!node.isBone && node.type !== "Bone") return false;
      return (
        node.getWorldPosition(new THREE.Vector3()).distanceTo(
          bone.getWorldPosition(new THREE.Vector3()),
        ) > 1e-5
      );
    });
    const child =
      children?.find((node) =>
        childAliases?.some((alias) => normalizedBoneName(node.name).endsWith(alias)),
      ) || children?.[0];
    if (!bone || !child || !bone.parent) continue;
    const restDirection = child
      .getWorldPosition(new THREE.Vector3())
      .sub(bone.getWorldPosition(new THREE.Vector3()))
      .normalize();
    if (restDirection.lengthSq() < MIN_DIR) continue;
    bones.set(key, {
      bone,
      child,
      restLocalQuaternion: bone.quaternion.clone(),
      restLocalPosition: bone.position.clone(),
      restLocalDirection: child.position.clone().normalize(),
      restQuaternionInRoot: inverseRoot
        .clone()
        .multiply(bone.getWorldQuaternion(new THREE.Quaternion())),
      restDirectionInRoot: restDirection.clone().applyQuaternion(inverseRoot),
    });
  }

  const hips = bones.get("hips");
  const leftUpLeg = bones.get("leftUpLeg");
  const rightUpLeg = bones.get("rightUpLeg");
  if (hips && leftUpLeg && rightUpLeg) {
    hips.restAcrossInRoot = rightUpLeg.bone
      .getWorldPosition(new THREE.Vector3())
      .sub(leftUpLeg.bone.getWorldPosition(new THREE.Vector3()))
      .normalize()
      .applyQuaternion(inverseRoot);
  }
  const leftArm = bones.get("leftArm");
  const rightArm = bones.get("rightArm");
  let shoulderAcross = null;
  if (leftArm && rightArm) {
    shoulderAcross = rightArm.bone
      .getWorldPosition(new THREE.Vector3())
      .sub(leftArm.bone.getWorldPosition(new THREE.Vector3()))
      .normalize()
      .applyQuaternion(inverseRoot);
    for (const name of ["spine", "spine1", "spine2", "head", "neck"]) {
      const spine = bones.get(name);
      if (spine) spine.restAcrossInRoot = shoulderAcross.clone();
    }
  }
  // Hands: rest palm-across ≈ boneDir × up (T-pose palms face down)
  for (const name of ["leftHand", "rightHand"]) {
    const hand = bones.get(name);
    if (!hand) continue;
    const across = new THREE.Vector3().crossVectors(
      hand.restDirectionInRoot,
      new THREE.Vector3(0, 1, 0),
    );
    if (across.lengthSq() > MIN_DIR) hand.restAcrossInRoot = across.normalize();
  }

  // Character forward in root at rest ≈ across × up for arms facing bend.
  // Mixamo T-pose: arms along ±X; elbows flex toward +Z (character forward).
  // Knees flex toward −Z (backward). Project onto plane ⊥ rest bone axis.
  const forward = new THREE.Vector3(0, 0, 1);
  const back = new THREE.Vector3(0, 0, -1);
  for (const [name, prefer] of [
    ["leftArm", forward],
    ["rightArm", forward],
    ["leftUpLeg", back],
    ["rightUpLeg", back],
  ]) {
    const rest = bones.get(name);
    if (!rest) continue;
    const axis = rest.restDirectionInRoot.clone().normalize();
    const wit = prefer.clone().addScaledVector(axis, -prefer.dot(axis));
    if (wit.lengthSq() > MIN_DIR) rest.restWitnessInRoot = wit.normalize();
  }

  return { bones };
}

export function createAvatarMotion() {
  return {
    referencePelvis: null,
    referenceShoulders: null,
    referenceHips: null,
    referenceHeadForward: null,
    basePosition: new THREE.Vector3(),
  };
}

/** @param {THREE.Object3D|null} model @param {ReturnType<typeof createAvatarMotion>} motion */
export function resetAvatarMotion(model, motion) {
  motion.referencePelvis = null;
  motion.referenceShoulders = null;
  motion.referenceHips = null;
  motion.referenceHeadForward = null;
  motion.basePosition.copy(model?.position || new THREE.Vector3());
}

// ---------------------------------------------------------------------------
// Solver state (filters + held locals)
// ---------------------------------------------------------------------------

const filterBank = new WeakMap();

function filtersFor(rig) {
  let bank = filterBank.get(rig);
  if (!bank) {
    bank = { byName: new Map(), smoothing: { minCutoff: 1.5, beta: 1.5, dCutoff: 1.0 } };
    filterBank.set(rig, bank);
  }
  return bank;
}

export function resetRetargetFilters(rig) {
  const bank = filterBank.get(rig);
  if (!bank) return;
  for (const f of bank.byName.values()) f.reset();
}

function filterBoneLocal(rig, name, q, timestampMs) {
  if (timestampMs == null) return q;
  const bank = filtersFor(rig);
  let f = bank.byName.get(name);
  if (!f) {
    const { minCutoff, beta, dCutoff } = bank.smoothing;
    f = new QuaternionOneEuroFilter(minCutoff, beta, dCutoff);
    bank.byName.set(name, f);
  }
  return f.filter(q, timestampMs);
}

export function setRetargetSmoothing(rig, minCutoff, beta) {
  const bank = filtersFor(rig);
  bank.smoothing = { minCutoff, beta, dCutoff: bank.smoothing.dCutoff };
  bank.byName.clear();
}

// ---------------------------------------------------------------------------
// Core rotation writers (MiKaPo direction + witness)
// ---------------------------------------------------------------------------

function applyWorldRotationToBone(model, rest, targetWorld, strength = 1, timestampMs, rig, name) {
  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);
  const blendedWorld = restWorld.clone().slerp(targetWorld, strength);
  const parentWorld = rest.bone.parent.getWorldQuaternion(new THREE.Quaternion());
  let local = parentWorld.clone().invert().multiply(blendedWorld);
  local = filterBoneLocal(rig, name, local, timestampMs);
  rest.bone.quaternion.copy(local);
  rest.bone.updateWorldMatrix(false, true);
}

/** Shortest-arc aim: rest child dir → live dir (both in root space). */
function rotateBoneToward(model, rig, name, directionInRoot, strength = 1, timestampMs = null) {
  const rest = rig?.bones.get(name);
  if (!rest || directionInRoot.lengthSq() < MIN_DIR) return false;
  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const restDirectionWorld = rest.restDirectionInRoot.clone().applyQuaternion(rootWorld).normalize();
  const targetDirectionWorld = directionInRoot.clone().normalize().applyQuaternion(rootWorld).normalize();
  if (restDirectionWorld.lengthSq() < MIN_DIR || targetDirectionWorld.lengthSq() < MIN_DIR) return false;
  const correction = new THREE.Quaternion().setFromUnitVectors(restDirectionWorld, targetDirectionWorld);
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);
  const targetWorld = correction.multiply(restWorld.clone());
  applyWorldRotationToBone(model, rest, targetWorld, strength, timestampMs, rig, name);
  return true;
}

/**
 * Aim + twist using an across vector (hips / spine), equivalent to MiKaPo basis-lite.
 */
function rotateBoneWithAcross(model, rig, name, directionInRoot, acrossInRoot, strength = 1, timestampMs = null) {
  const rest = rig?.bones.get(name);
  if (!rest?.restAcrossInRoot || directionInRoot.lengthSq() < MIN_DIR || acrossInRoot.lengthSq() < MIN_DIR) {
    return rotateBoneToward(model, rig, name, directionInRoot, strength, timestampMs);
  }
  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const restDirectionWorld = rest.restDirectionInRoot.clone().applyQuaternion(rootWorld).normalize();
  const targetDirectionWorld = directionInRoot.clone().normalize().applyQuaternion(rootWorld).normalize();
  const align = new THREE.Quaternion().setFromUnitVectors(restDirectionWorld, targetDirectionWorld);
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);
  let targetWorld = align.clone().multiply(restWorld);

  const alignedAcross = rest.restAcrossInRoot
    .clone()
    .applyQuaternion(rootWorld)
    .applyQuaternion(align)
    .addScaledVector(
      targetDirectionWorld,
      -rest.restAcrossInRoot
        .clone()
        .applyQuaternion(rootWorld)
        .applyQuaternion(align)
        .dot(targetDirectionWorld),
    );
  const desiredAcross = acrossInRoot
    .clone()
    .applyQuaternion(rootWorld)
    .addScaledVector(
      targetDirectionWorld,
      -acrossInRoot.clone().applyQuaternion(rootWorld).dot(targetDirectionWorld),
    );
  if (alignedAcross.lengthSq() > MIN_DIR && desiredAcross.lengthSq() > MIN_DIR) {
    targetWorld = new THREE.Quaternion()
      .setFromUnitVectors(alignedAcross.normalize(), desiredAcross.normalize())
      .multiply(targetWorld);
  }
  applyWorldRotationToBone(model, rest, targetWorld, strength, timestampMs, rig, name);
  return true;
}

/**
 * Roll witness: after shortest-arc, blend toward basis that maps
 * (restDir, restWitness⊥) → (liveDir, liveWitness⊥). Fade when limb is straight.
 */
function rotateBoneWithWitness(
  model,
  rig,
  name,
  directionInRoot,
  witnessDirInRoot,
  strength = 1,
  timestampMs = null,
) {
  const rest = rig?.bones.get(name);
  if (!rest || directionInRoot.lengthSq() < MIN_DIR) return false;

  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const restDirW = rest.restDirectionInRoot.clone().applyQuaternion(rootWorld).normalize();
  const liveDirW = directionInRoot.clone().normalize().applyQuaternion(rootWorld).normalize();
  const shortest = new THREE.Quaternion().setFromUnitVectors(restDirW, liveDirW);
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);
  let targetWorld = shortest.clone().multiply(restWorld.clone());

  const restWit = rest.restWitnessInRoot;
  if (restWit && witnessDirInRoot && witnessDirInRoot.lengthSq() > MIN_DIR) {
    const liveWitW = witnessDirInRoot.clone().normalize().applyQuaternion(rootWorld).normalize();
    const restWitW = restWit.clone().applyQuaternion(rootWorld).normalize();

    // Perp components (observability = |live perp|)
    const livePerp = liveWitW.clone().addScaledVector(liveDirW, -liveWitW.dot(liveDirW));
    const perpLen = livePerp.length();
    if (perpLen >= WITNESS_FADE_LO) {
      livePerp.normalize();
      const restPerp = restWitW.clone().addScaledVector(restDirW, -restWitW.dot(restDirW));
      if (restPerp.lengthSq() > 1e-3) {
        restPerp.normalize();
        // Orthonormal bases: X=dir? MiKaPo uses (ref, restWit⊥, ref×wit) as columns via quatFromBasis.
        // Here: map restDir→liveDir and restPerp→livePerp via two-step FromUnitVectors composition.
        const mapDir = new THREE.Quaternion().setFromUnitVectors(restDirW, liveDirW);
        const mappedRestPerp = restPerp.clone().applyQuaternion(mapDir);
        const mapRoll = new THREE.Quaternion().setFromUnitVectors(
          mappedRestPerp.normalize(),
          livePerp,
        );
        const witnessed = mapRoll.multiply(mapDir).multiply(restWorld.clone());

        let t = (perpLen - WITNESS_FADE_LO) / (WITNESS_FADE_HI - WITNESS_FADE_LO);
        t = Math.min(1, Math.max(0, t));
        t = t * t * (3 - 2 * t);
        if (targetWorld.dot(witnessed) < 0) {
          witnessed.x *= -1;
          witnessed.y *= -1;
          witnessed.z *= -1;
          witnessed.w *= -1;
        }
        targetWorld.slerp(witnessed, t);
      }
    }
  }

  applyWorldRotationToBone(model, rest, targetWorld, strength, timestampMs, rig, name);
  return true;
}

/**
 * Foot aim from ankle→toe.
 *
 * Default `yawFromDir`: take the same continuous direction signal that looked
 * good for L/R turning, but apply ONLY the twist around world-up onto the rest
 * foot — no pitch (droop) and no horizontal FromUnitVectors (that flipped 180°).
 */
function rotateFoot(
  model,
  rig,
  name,
  directionInRoot,
  { mode = "yawFromDir", strength = 0.9, timestampMs = null } = {},
) {
  const rest = rig?.bones.get(name);
  if (!rest || !directionInRoot || directionInRoot.lengthSq() < MIN_DIR) return false;
  if (mode === "rest") return false;

  if (mode === "direction") {
    return rotateBoneToward(model, rig, name, directionInRoot, strength, timestampMs);
  }

  // yawFromDir / flat / yaw — all resolve to twist-around-up from the live dir.
  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const upWorld = new THREE.Vector3(0, 1, 0).applyQuaternion(rootWorld).normalize();
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);

  // Rest toe horizontal bearing
  const restToe = rest.restLocalDirection.clone().applyQuaternion(restWorld);
  const restH = restToe.clone().addScaledVector(upWorld, -restToe.dot(upWorld));
  // Live toe horizontal bearing (from ankle→toe); do NOT negate — that caused flips
  const liveW = directionInRoot.clone().normalize().applyQuaternion(rootWorld);
  const liveH = liveW.clone().addScaledVector(upWorld, -liveW.dot(upWorld));
  if (restH.lengthSq() < MIN_DIR || liveH.lengthSq() < MIN_DIR) return false;
  restH.normalize();
  liveH.normalize();

  // Signed angle around up, shortest path in (-pi, pi] — continuous, no hemispheric flip
  const cross = new THREE.Vector3().crossVectors(restH, liveH);
  let yaw = Math.atan2(upWorld.dot(cross), THREE.MathUtils.clamp(restH.dot(liveH), -1, 1));
  // Soft clamp: wild MediaPipe frames shouldn't spin the shoe past ~120°
  yaw = THREE.MathUtils.clamp(yaw, -2.1, 2.1) * strength;

  const targetWorld = new THREE.Quaternion().setFromAxisAngle(upWorld, yaw).multiply(restWorld);
  applyWorldRotationToBone(model, rest, targetWorld, 1, timestampMs, rig, name);
  return true;
}

// ---------------------------------------------------------------------------
// Pose application
// ---------------------------------------------------------------------------

function posePoint(pose, nameToIndex, name, shoulderCenter, shoulderWidth) {
  const idx = nameToIndex[name];
  if (idx == null || !pose[idx]) return null;
  const point = pose[idx];
  return new THREE.Vector3(
    (point[0] - shoulderCenter.x) / shoulderWidth,
    (point[1] - shoulderCenter.y) / shoulderWidth,
    (point[2] - shoulderCenter.z) / shoulderWidth,
  );
}

function updateRootTranslation(model, rig, pose, nameToIndex, shoulderCenter, shoulderWidth, motion) {
  const pelvisIdx = nameToIndex.pelvis;
  if (pelvisIdx == null) return;
  const pelvis = new THREE.Vector3(...pose[pelvisIdx]);
  if (!motion.referencePelvis) {
    motion.referencePelvis = pelvis.clone();
    motion.basePosition.copy(model.position);
  }
  const leftArm = rig?.bones.get("leftArm");
  const rightArm = rig?.bones.get("rightArm");
  const avatarShoulderWidth = leftArm?.bone
    .getWorldPosition(new THREE.Vector3())
    .distanceTo(rightArm?.bone.getWorldPosition(new THREE.Vector3()));
  if (avatarShoulderWidth > 1e-4) {
    model.position
      .copy(motion.basePosition)
      .addScaledVector(pelvis.sub(motion.referencePelvis), avatarShoulderWidth / shoulderWidth);
  }
  model.updateWorldMatrix(true, true);
}

function updateJointTranslations(model, rig, pose, nameToIndex, shoulderWidth, motion, kind) {
  const leftName = kind === "shoulder" ? "left_shoulder" : "left_hip";
  const rightName = kind === "shoulder" ? "right_shoulder" : "right_hip";
  const leftBone = kind === "shoulder" ? "leftArm" : "leftUpLeg";
  const rightBone = kind === "shoulder" ? "rightArm" : "rightUpLeg";
  const refKey = kind === "shoulder" ? "referenceShoulders" : "referenceHips";
  const maxFrac = kind === "shoulder" ? 0.25 : 0.22;

  const li = nameToIndex[leftName];
  const ri = nameToIndex[rightName];
  if (li == null || ri == null) return;
  const leftSource = new THREE.Vector3(...pose[li]);
  const rightSource = new THREE.Vector3(...pose[ri]);
  if (!motion[refKey]) {
    motion[refKey] = { left: leftSource, right: rightSource, width: shoulderWidth };
    return;
  }
  const left = rig?.bones.get(leftBone);
  const right = rig?.bones.get(rightBone);
  const leftArm = rig?.bones.get("leftArm");
  const rightArm = rig?.bones.get("rightArm");
  if (!left || !right || !leftArm || !rightArm) return;
  const avatarWidth = leftArm.bone
    .getWorldPosition(new THREE.Vector3())
    .distanceTo(rightArm.bone.getWorldPosition(new THREE.Vector3()));
  const sourceScale = avatarWidth / Math.max(motion[refKey].width, 1e-4);
  const sourceCenter = leftSource.clone().add(rightSource).multiplyScalar(0.5);
  const referenceCenter = motion[refKey].left
    .clone()
    .add(motion[refKey].right)
    .multiplyScalar(0.5);
  for (const [side, source, restPos] of [
    ["left", leftSource, motion[refKey].left],
    ["right", rightSource, motion[refKey].right],
  ]) {
    const boneRest = side === "left" ? left : right;
    const offsetInRoot = source
      .clone()
      .sub(sourceCenter)
      .sub(restPos.clone().sub(referenceCenter))
      .multiplyScalar(sourceScale)
      .clampLength(0, avatarWidth * maxFrac);
    const parentWorld = boneRest.bone.parent.getWorldQuaternion(new THREE.Quaternion());
    const localOffset = offsetInRoot
      .applyQuaternion(model.getWorldQuaternion(new THREE.Quaternion()))
      .applyQuaternion(parentWorld.invert());
    boneRest.bone.position.copy(boneRest.restLocalPosition).add(localOffset);
    boneRest.bone.updateWorldMatrix(false, true);
  }
}

/**
 * Foot direction for Mixamo foot bone.
 * MiKaPo: ankle → foot_index (toe). footFrame: [left_heel, left_toe, right_heel, right_toe].
 * When `ankleWorld` is in the same space as footFrame, use ankle→toe; else heel→toe.
 * Optional bodyFrame remaps into avatar torso basis (shoulderAcross / torso).
 */
export function footDirectionInRoot({
  footFrame,
  bodyFrame,
  side,
  shoulderAcross,
  torso,
  ankleWorld = null,
}) {
  if (!footFrame) return null;
  const toe = new THREE.Vector3(...footFrame[side === "left" ? 1 : 3]);
  const heel = new THREE.Vector3(...footFrame[side === "left" ? 0 : 2]);
  const origin = ankleWorld ? ankleWorld.clone() : heel;
  const sourceDirection = toe.clone().sub(origin);
  if (sourceDirection.lengthSq() < MIN_DIR) return null;

  if (bodyFrame && shoulderAcross && torso) {
    const sourceAcross = new THREE.Vector3(...bodyFrame[1]).sub(new THREE.Vector3(...bodyFrame[0]));
    const sourceUp = new THREE.Vector3(...bodyFrame[0])
      .add(new THREE.Vector3(...bodyFrame[1]))
      .sub(new THREE.Vector3(...bodyFrame[2]).add(new THREE.Vector3(...bodyFrame[3])))
      .normalize();
    const targetUp = torso.clone().normalize();
    const sourceRight = sourceAcross
      .clone()
      .addScaledVector(sourceUp, -sourceAcross.dot(sourceUp))
      .normalize();
    const targetRight = shoulderAcross
      .clone()
      .addScaledVector(targetUp, -shoulderAcross.dot(targetUp))
      .normalize();
    const sourceForward = sourceRight.clone().cross(sourceUp).normalize();
    const targetForward = targetRight.clone().cross(targetUp).normalize();
    // Horizontal only — vertical component was feeding pitch hacks / flips.
    const target = targetRight
      .clone()
      .multiplyScalar(sourceDirection.dot(sourceRight))
      .addScaledVector(targetForward, sourceDirection.dot(sourceForward));
    return target.lengthSq() > MIN_DIR ? target.normalize() : null;
  }

  return sourceDirection.normalize();
}

/** Snap avatar so the lowest sole sits on groundY (grid = 0). */
export function plantAvatarOnGround(model, rig, groundY = 0) {
  if (!model || !rig) return;
  model.updateWorldMatrix(true, true);
  let minY = Infinity;
  for (const name of ["leftFoot", "rightFoot"]) {
    const rest = rig.bones.get(name);
    if (!rest) continue;
    minY = Math.min(minY, rest.bone.getWorldPosition(new THREE.Vector3()).y);
    if (rest.child) minY = Math.min(minY, rest.child.getWorldPosition(new THREE.Vector3()).y);
  }
  if (!Number.isFinite(minY)) return;
  model.position.y += groundY - minY;
  model.updateWorldMatrix(true, true);
}

/**
 * Build aux dict from a Pose-33 frame already in viewer space (arrays or Vector3).
 * @param {Array|Object} frame33  length-33 of [x,y,z] in viewer space, OR raw MP landmarks with flip
 * @param {boolean} [flip=false]  set true when frame is raw MediaPipe world
 */
export function auxFromPose33(frame33, flip = false) {
  if (!frame33 || frame33.length < 23) return null;
  const get = (i) => {
    const p = frame33[i];
    if (!p) return null;
    if (flip) return flipMpPointToViewer(p);
    if (p.isVector3) return p.clone();
    return new THREE.Vector3(p[0] ?? p.x, p[1] ?? p.y, p[2] ?? p.z);
  };
  const out = { kind: "pose33" };
  for (const [name, idx] of Object.entries(MP_AUX)) {
    const v = get(idx);
    if (!v) return null;
    out[name] = v;
  }
  return out;
}

/**
 * Build MiKaPo aux from NLF/SMPL24 avatar keypoints (viewer space).
 * Expects left/right foot, hand, ankle, wrist, elbow, shoulder, neck, head.
 */
export function auxFromSmpl(auxSmpl, flip = false) {
  if (!auxSmpl) return null;
  const need = [
    "left_ankle", "right_ankle", "left_foot", "right_foot",
    "left_wrist", "right_wrist", "left_hand", "right_hand",
    "left_elbow", "right_elbow",
    "left_shoulder", "right_shoulder", "neck", "head",
  ];
  const out = { kind: "smpl" };
  for (const name of need) {
    const p = auxSmpl[name];
    if (!p) return null;
    if (flip) out[name] = flipMpPointToViewer(p);
    else if (p.isVector3) out[name] = p.clone();
    else out[name] = new THREE.Vector3(p[0] ?? p.x, p[1] ?? p.y, p[2] ?? p.z);
  }
  return out;
}

/** Ankle→foot directions in viewer space for Mixamo foot yaw. */
export function footDirectionsFromSmplAux(aux) {
  if (!aux?.left_foot || !aux?.left_ankle || !aux?.right_foot || !aux?.right_ankle) return null;
  return {
    left: aux.left_foot.clone().sub(aux.left_ankle),
    right: aux.right_foot.clone().sub(aux.right_ankle),
  };
}

/**
 * Shoulder across matching Mixamo restAcross (right − left) and Pose-33 ear across polarity.
 * forward = across × (head−neck) → character +Z when upright.
 */
function smplHeadBasis(aux) {
  if (!aux?.left_shoulder || !aux?.right_shoulder || !aux?.neck || !aux?.head) return null;
  const across = aux.right_shoulder.clone().sub(aux.left_shoulder);
  const up = aux.head.clone().sub(aux.neck);
  if (across.lengthSq() < MIN_DIR || up.lengthSq() < MIN_DIR) return null;
  const forward = new THREE.Vector3().crossVectors(across, up);
  if (forward.lengthSq() < MIN_DIR) return null;
  return { across, up: up.normalize(), forward: forward.normalize() };
}

/** Horizontal head-forward from shoulders × neck→head. */
export function headForwardFromSmplAux(aux) {
  const basis = smplHeadBasis(aux);
  if (!basis) return null;
  const forward = basis.forward.clone();
  forward.y = 0;
  if (forward.lengthSq() < MIN_DIR) return null;
  return forward.normalize();
}

function applyHeadFromSmpl(model, rig, aux, timestampMs) {
  const basis = smplHeadBasis(aux);
  if (!basis) return;
  // Neck aims along skull up (same idea as nose−earMid soft aim).
  rotateBoneToward(model, rig, "neck", basis.up, 0.5, timestampMs);
  // Head bone: aim primary axis along up; twist with shoulder across (stable).
  // Using face-forward as primary flipped the skull 90–180° on Mixamo.
  rotateBoneWithAcross(model, rig, "head", basis.up, basis.across, 0.75, timestampMs);
  // Soft yaw from face forward (legacy path) so looking L/R still works.
  if (rig.bones.get("head")) {
    const headBone = rig.bones.get("head");
    const flat = basis.forward.clone().setY(0);
    if (flat.lengthSq() > MIN_DIR) {
      flat.normalize();
      const restFwd = new THREE.Vector3(0, 0, 1);
      const yaw = Math.atan2(
        new THREE.Vector3().crossVectors(restFwd, flat).y,
        THREE.MathUtils.clamp(restFwd.dot(flat), -1, 1),
      );
      const localYaw = THREE.MathUtils.clamp(yaw, -0.9, 0.9) * 0.65;
      let q = headBone.bone.quaternion.clone()
        .multiply(new THREE.Quaternion().setFromAxisAngle(headBone.restLocalDirection, localYaw));
      q = filterBoneLocal(rig, "head", q, timestampMs);
      headBone.bone.quaternion.copy(q);
      headBone.bone.updateWorldMatrix(false, true);
    }
  }
}

function applyHeadFromAux(model, rig, aux, timestampMs) {
  if (aux?.kind === "smpl" || (aux?.head && aux?.neck && !aux?.left_ear)) {
    applyHeadFromSmpl(model, rig, aux, timestampMs);
    return;
  }
  if (!aux?.left_ear || !aux?.right_ear || !aux?.left_eye || !aux?.right_eye || !aux?.nose) return;
  // Directions only from aux (ok if aux Y not planted — offsets cancel).
  const leftEar = aux.left_ear;
  const rightEar = aux.right_ear;
  const earMid = leftEar.clone().add(rightEar).multiplyScalar(0.5);
  const eyeMid = aux.left_eye.clone().add(aux.right_eye).multiplyScalar(0.5);
  const across = leftEar.clone().sub(rightEar);
  let forward = eyeMid.clone().sub(earMid);
  if (forward.lengthSq() < MIN_DIR) forward = aux.nose.clone().sub(earMid);
  if (forward.lengthSq() < MIN_DIR || across.lengthSq() < MIN_DIR) return;

  // Neck: aim along head-up roughly (ear mid → nose)
  const neckDir = aux.nose.clone().sub(earMid);
  if (neckDir.lengthSq() > MIN_DIR) {
    rotateBoneToward(model, rig, "neck", neckDir.normalize(), 0.5, timestampMs);
  }
  rotateBoneWithAcross(model, rig, "head", forward.normalize(), across, 0.85, timestampMs);
}

/** Live-tunable SMPL/Pose33 hand palm polarity (see Live → Calibrar mãos). */
export const handRetargetOpts = {
  palmEnabled: true,
  /** false = forearm×forward; true = forward×forearm */
  swapCrossOrder: true,
  negateAcrossLeft: true,
  negateAcrossRight: false,
  /** Skip across twist — only aim wrist→hand (isolates palm roll bugs). */
  aimOnly: false,
};

export function setHandRetargetOpts(partial = {}) {
  Object.assign(handRetargetOpts, partial);
  return { ...handRetargetOpts };
}

export function getHandRetargetOpts() {
  return { ...handRetargetOpts };
}

/**
 * Compute palm forward/across in viewer space (for retarget + debug arrows).
 * @returns {{ forward: THREE.Vector3, across: THREE.Vector3|null }|null}
 */
export function computeHandPalmAxes(aux, side) {
  if (!aux) return null;
  const wrist = aux[`${side}_wrist`];
  const index = aux[`${side}_index`];
  const pinky = aux[`${side}_pinky`];
  if (wrist && index && pinky) {
    const forward = index.clone().add(pinky).multiplyScalar(0.5).sub(wrist);
    if (forward.lengthSq() < MIN_DIR) return null;
    let across = pinky.clone().sub(index);
    if (handRetargetOpts.negateAcrossLeft && side === "left") across.negate();
    if (handRetargetOpts.negateAcrossRight && side === "right") across.negate();
    return { forward: forward.normalize(), across: across.normalize() };
  }
  const hand = aux[`${side}_hand`];
  const elbow = aux[`${side}_elbow`];
  if (!wrist || !hand) return null;
  const forward = hand.clone().sub(wrist);
  if (forward.lengthSq() < MIN_DIR) return null;
  let across = null;
  if (elbow) {
    const forearm = wrist.clone().sub(elbow);
    across = handRetargetOpts.swapCrossOrder
      ? new THREE.Vector3().crossVectors(forward, forearm)
      : new THREE.Vector3().crossVectors(forearm, forward);
  }
  if (!across || across.lengthSq() < MIN_DIR) {
    across = new THREE.Vector3().crossVectors(forward, new THREE.Vector3(0, 1, 0));
  }
  if (handRetargetOpts.negateAcrossLeft && side === "left") across.negate();
  if (handRetargetOpts.negateAcrossRight && side === "right") across.negate();
  if (across.lengthSq() < MIN_DIR) {
    return { forward: forward.normalize(), across: null };
  }
  return { forward: forward.normalize(), across: across.normalize() };
}

function applyHandPalmFromAux(model, rig, aux, side, timestampMs) {
  if (!handRetargetOpts.palmEnabled) return;
  const handName = side === "left" ? "leftHand" : "rightHand";
  if (!rig.bones.get(handName) || !aux) return;
  const axes = computeHandPalmAxes(aux, side);
  if (!axes) return;
  if (handRetargetOpts.aimOnly || !axes.across) {
    rotateBoneToward(model, rig, handName, axes.forward, 0.85, timestampMs);
    return;
  }
  rotateBoneWithAcross(model, rig, handName, axes.forward, axes.across, 0.85, timestampMs);
}

/**
 * Apply lab pose to Mixamo avatar (MiKaPo-style FK + witness).
 *
 * @param {object} opts
 * @param {object|null} [opts.aux]  pose-33 viewer-space points from auxFromPose33
 * @param {boolean} [opts.plantGround=true]
 * @param {number} [opts.groundY=0]
 * @param {'direction'|'yawFromDir'|'flat'|'yaw'|'rest'} [opts.footMode='yawFromDir']
 */
export function updateAvatarPose({
  model,
  rig,
  pose,
  nameToIndex,
  motion,
  footFrame = null,
  bodyFrame = null,
  allowFeet = false,
  footMode = "yawFromDir",
  timestampMs = null,
  headForward = null,
  footDirections = null,
  useWitness = true,
  aux = null,
  plantGround = true,
  groundY = 0,
}) {
  if (!model || !rig || !pose) return;

  for (const rest of rig.bones.values()) {
    rest.bone.quaternion.copy(rest.restLocalQuaternion);
    rest.bone.position.copy(rest.restLocalPosition);
  }
  model.updateWorldMatrix(true, true);

  const ls = nameToIndex.left_shoulder;
  const rs = nameToIndex.right_shoulder;
  if (ls == null || rs == null) return;
  const leftShoulder = new THREE.Vector3(...pose[ls]);
  const rightShoulder = new THREE.Vector3(...pose[rs]);
  const shoulderCenter = leftShoulder.clone().add(rightShoulder).multiplyScalar(0.5);
  const shoulderWidth = leftShoulder.distanceTo(rightShoulder);
  if (shoulderWidth < 0.02) return;

  const P = (name) => posePoint(pose, nameToIndex, name, shoulderCenter, shoulderWidth);

  updateJointTranslations(model, rig, pose, nameToIndex, shoulderWidth, motion, "shoulder");

  const leftHip = P("left_hip");
  const rightHip = P("right_hip");
  if (!leftHip || !rightHip) return;
  const hipCenter = leftHip.clone().add(rightHip).multiplyScalar(0.5);
  const torso = hipCenter.clone().negate();
  torso.x *= 1.5;
  torso.z *= 1.5;

  updateRootTranslation(model, rig, pose, nameToIndex, shoulderCenter, shoulderWidth, motion);
  rotateBoneWithAcross(model, rig, "hips", torso, rightHip.clone().sub(leftHip), 0.78, timestampMs);
  updateJointTranslations(model, rig, pose, nameToIndex, shoulderWidth, motion, "hip");

  const leftSh = P("left_shoulder");
  const rightSh = P("right_shoulder");
  if (!leftSh || !rightSh) return;
  const shoulderAcross = rightSh.clone().sub(leftSh);

  rotateBoneWithAcross(model, rig, "spine", torso, shoulderAcross, 0.28, timestampMs);
  rotateBoneWithAcross(model, rig, "spine1", torso, shoulderAcross, 0.48, timestampMs);
  rotateBoneWithAcross(model, rig, "spine2", torso, shoulderAcross, 0.7, timestampMs);

  // Head: prefer Pose-33 ears/eyes; fallback soft neck aim + legacy yaw
  if (aux) {
    applyHeadFromAux(model, rig, aux, timestampMs);
  } else {
    const head = P("head");
    if (head) rotateBoneToward(model, rig, "neck", head, 0.55, timestampMs);
    if (headForward && rig.bones.get("head")) {
      const headBone = rig.bones.get("head");
      const forward = headForward.clone().setY(0);
      if (forward.lengthSq() > MIN_DIR) {
        forward.normalize();
        if (!motion.referenceHeadForward) {
          motion.referenceHeadForward = forward.clone();
        } else {
          const reference = motion.referenceHeadForward;
          const yaw = Math.atan2(
            new THREE.Vector3().crossVectors(reference, forward).y,
            THREE.MathUtils.clamp(reference.dot(forward), -1, 1),
          );
          const localYaw = THREE.MathUtils.clamp(yaw, -0.8, 0.8) * 0.8;
          let q = headBone.restLocalQuaternion
            .clone()
            .multiply(new THREE.Quaternion().setFromAxisAngle(headBone.restLocalDirection, localYaw));
          q = filterBoneLocal(rig, "head", q, timestampMs);
          headBone.bone.quaternion.copy(q);
          headBone.bone.updateWorldMatrix(false, true);
        }
      }
    }
  }

  if (leftSh) rotateBoneToward(model, rig, "leftShoulder", leftSh, 0.8, timestampMs);
  if (rightSh) rotateBoneToward(model, rig, "rightShoulder", rightSh, 0.8, timestampMs);

  for (const side of ["left", "right"]) {
    const sh = P(`${side}_shoulder`);
    const el = P(`${side}_elbow`);
    const wr = P(`${side}_wrist`);
    const arm = side === "left" ? "leftArm" : "rightArm";
    const fore = side === "left" ? "leftForeArm" : "rightForeArm";
    if (!sh || !el || !wr) continue;
    const upperDir = el.clone().sub(sh);
    const foreDir = wr.clone().sub(el);
    if (useWitness) {
      rotateBoneWithWitness(model, rig, arm, upperDir, foreDir, 1, timestampMs);
    } else {
      rotateBoneToward(model, rig, arm, upperDir, 1, timestampMs);
    }
    rotateBoneToward(model, rig, fore, foreDir, 1, timestampMs);
  }

  // Palm orientation from Pose-33 (no finger curl)
  if (aux) {
    applyHandPalmFromAux(model, rig, aux, "left", timestampMs);
    applyHandPalmFromAux(model, rig, aux, "right", timestampMs);
  }

  for (const side of ["left", "right"]) {
    const hip = P(`${side}_hip`);
    const knee = P(`${side}_knee`);
    const ankle = P(`${side}_ankle`);
    const up = side === "left" ? "leftUpLeg" : "rightUpLeg";
    const leg = side === "left" ? "leftLeg" : "rightLeg";
    if (!hip || !knee || !ankle) continue;
    const thighDir = knee.clone().sub(hip);
    const shinDir = ankle.clone().sub(knee);
    if (useWitness) {
      rotateBoneWithWitness(model, rig, up, thighDir, shinDir, 1, timestampMs);
    } else {
      rotateBoneToward(model, rig, up, thighDir, 1, timestampMs);
    }
    rotateBoneToward(model, rig, leg, shinDir, 1, timestampMs);
  }

  if (allowFeet && footMode !== "rest") {
    const smplFeet = (!footDirections && aux?.kind === "smpl")
      ? footDirectionsFromSmplAux(aux)
      : null;
    for (const side of ["left", "right"]) {
      const footName = side === "left" ? "leftFoot" : "rightFoot";
      let dir = footDirections?.[side] || smplFeet?.[side] || null;
      if (!dir && footFrame) {
        // Heel→toe from the same foot JSON (do NOT mix planted pose ankle with
        // unplanted foot tips — that skewed XZ and spun shoes backward).
        dir = footDirectionInRoot({
          footFrame,
          bodyFrame,
          side,
          shoulderAcross,
          torso,
          ankleWorld: null,
        });
      }
      if (!dir) continue;
      const mode =
        footMode === "direction" ? "direction"
        : footMode === "rest" ? "rest"
        : "yawFromDir";
      rotateFoot(model, rig, footName, dir, { mode, strength: 0.85, timestampMs });
    }
  }

  if (plantGround) plantAvatarOnGround(model, rig, groundY);
}
