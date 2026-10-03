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
 * - hands: palm across twists ForeArm (pronation) and Hand (same across, aim along knuckles).
 *   Across comes from index/pinky only — never hand×forearm (that proxy inverts).
 * - One-Euro on bone local quaternions
 *
 * Not a line-for-line copy: MMD / fingers / face morphs omitted.
 */

import * as THREE from "three";

const MIN_DIR = 1e-6;
const WITNESS_FADE_LO = 0.15;
const WITNESS_FADE_HI = 0.35;
// Across-fade bounds. These gate how much of the twist/roll is applied.
//
// CAREFUL — `obs` (the projected across length) means two different things:
//   * Torso callers (hips, spine, head) pass a RAW across — a hip or shoulder
//     span in METRES — so the fade is a metric observability gate.
//   * Hand callers pass a NORMALIZED across (computeHandPalmAxes normalizes),
//     so `obs` is sin(angle between across and the bone axis) — dimensionless,
//     always <= 1, and unrelated to how well the hand was observed.
// Sharing one constant across both silently faded the palm roll. UNIT_* is the
// angular pair for the normalized case: full roll past ~11.5 deg off-axis, and
// only genuine degeneracy (across parallel to the bone) is rejected.
const ACROSS_FADE_LO = 0.12;
const ACROSS_FADE_HI = 0.32;
const UNIT_ACROSS_FADE = { lo: 0.05, hi: 0.2 };

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

/**
 * Normalize a bone name for alias matching.
 *
 * DIGITS ARE SIGNIFICANT and must be kept: Mixamo distinguishes Spine/Spine1/
 * Spine2 and HandIndex1/2/3 only by the number. Stripping them (the old
 * `[^a-z]`) made "mixamorig:Spine1" normalize to "mixamorigspine", so the
 * "spine1"/"spine2" aliases could never match on ANY rig — the solver silently
 * drove the whole torso with a single spine bone (which is what made the
 * character hinge at one point instead of curving), and the hand childAliases
 * fell through to "first bone child", which lands on the thumb on a full
 * 5-finger rig.
 */
function normalizedBoneName(name) {
  return (name || "").toLowerCase().replace(/[^a-z0-9]/g, "");
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

/** Eigen-decomposition of a symmetric 3x3 via cyclic Jacobi. Returns eigenvalues
 *  ascending plus their eigenvectors. */
function symmetricEigen3(C) {
  const A = [C[0].slice(), C[1].slice(), C[2].slice()];
  const V = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
  for (let sweep = 0; sweep < 16; sweep++) {
    const off = Math.abs(A[0][1]) + Math.abs(A[0][2]) + Math.abs(A[1][2]);
    if (off < 1e-18) break;
    for (const [p, q] of [[0, 1], [0, 2], [1, 2]]) {
      if (Math.abs(A[p][q]) < 1e-20) continue;
      const theta = (A[q][q] - A[p][p]) / (2 * A[p][q]);
      const sgn = theta >= 0 ? 1 : -1;
      const t = sgn / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
      const c = 1 / Math.sqrt(t * t + 1);
      const s = t * c;
      for (let k = 0; k < 3; k++) {
        const akp = A[k][p], akq = A[k][q];
        A[k][p] = c * akp - s * akq;
        A[k][q] = s * akp + c * akq;
      }
      for (let k = 0; k < 3; k++) {
        const apk = A[p][k], aqk = A[q][k];
        A[p][k] = c * apk - s * aqk;
        A[q][k] = s * apk + c * aqk;
      }
      for (let k = 0; k < 3; k++) {
        const vkp = V[k][p], vkq = V[k][q];
        V[k][p] = c * vkp - s * vkq;
        V[k][q] = s * vkp + c * vkq;
      }
    }
  }
  const order = [0, 1, 2].sort((i, j) => A[i][i] - A[j][j]);
  return {
    values: order.map((i) => A[i][i]),
    vectors: order.map((i) => new THREE.Vector3(V[0][i], V[1][i], V[2][i])),
  };
}

/**
 * Normal of the best-fit plane through `pts`, or null if the plane is not
 * well determined (a straight chain has no unique plane: its two smallest
 * eigenvalues collapse together and the "normal" is arbitrary).
 */
function fittedPlaneNormal(pts) {
  if (pts.length < 4) return null;
  const c = new THREE.Vector3();
  for (const p of pts) c.add(p);
  c.multiplyScalar(1 / pts.length);
  const C = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  for (const p of pts) {
    const d = [p.x - c.x, p.y - c.y, p.z - c.z];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) C[i][j] += d[i] * d[j];
  }
  const { values, vectors } = symmetricEigen3(C);
  if (!(values[1] > 1e-18) || values[0] / values[1] > 0.5) return null;
  const n = vectors[0];
  return n.lengthSq() > MIN_DIR ? n.normalize() : null;
}

/**
 * Rest palm-across derived from the rig's OWN finger geometry.
 *
 * Why not the old estimate: `restDirection × up` assumes a T-pose with palms
 * facing down. Most rigs are not modelled that way — this boxer's arms hang
 * ~66° below horizontal — so that axis misses the real palm plane (measured
 * 41° off on the left hand, 35° on the right). Aligning a wrong rest across to
 * the fit's palm rotates the applied pronation away from the target, which is
 * what left the fist lateral instead of turning palm-down on the punch.
 *
 * Why not glove-mesh PCA: a boxing glove is a rounded mitt, not a flat hand.
 * Measured on this GLB the hand vertex cloud is ~10x12x10 cm with principal
 * values 6.57 / 6.12 / 4.22 — the two in-plane axes are nearly degenerate, so
 * the "widest axis" is noise. It flipped the LEFT hand ~180° relative to the
 * right (the two hands ended up with opposing acrosses).
 *
 * What works: the palm across IS the finger FLEXION axis. Fingers bend in a
 * plane; that plane's normal is the medial-lateral axis of the palm. Fitting a
 * plane to [hand + one finger chain] is well conditioned even when a single
 * cross product is not (the chain is nearly collinear, S2/S1 ~ 0.10). Measured:
 * the two independently modelled hands agree to 3.3° under mirroring, versus
 * 33-37° for subsets of the chain — including the hand root is what stabilises
 * it, because it extends the baseline.
 *
 * A plane normal's sign is arbitrary, so anchor it to the old heuristic, which
 * only has to be within 90° to disambiguate (it is 35-41° away).
 * Returns the across in ROOT space, or null if the rig has no usable chain.
 */
function deriveRestPalmAcross(handRest, inverseRoot) {
  const toRoot = (b) => b.getWorldPosition(new THREE.Vector3()).applyQuaternion(inverseRoot);
  const handPos = toRoot(handRest.bone);

  // Sign reference only — needs to be within 90°, and it is 35-41° away here.
  const ref = new THREE.Vector3()
    .crossVectors(handRest.restDirectionInRoot, new THREE.Vector3(0, 1, 0));
  if (ref.lengthSq() < MIN_DIR) return null;
  ref.normalize();

  // One plane PER FINGER, then average — do NOT fit a single plane to the whole
  // hand. On a rig with all five fingers the points fan out across the palm, so
  // the single best-fit plane IS the palm and its normal is the palm normal —
  // 90° from the across. Per finger, the plane is that finger's flexion plane
  // and its normal is the across, which is what we want. (This rig exposes only
  // an index chain, so the averaging is a no-op here and the measured 3.3°
  // mirror agreement still holds.)
  const acc = new THREE.Vector3();
  let used = 0;
  const handWorld = handRest.bone.getWorldPosition(new THREE.Vector3());
  for (const root of handRest.bone.children) {
    if (!root.isBone && root.type !== "Bone") continue;
    // The thumb opposes the palm; its flexion plane is not the palm's.
    if (normalizedBoneName(root.name).includes("thumb")) continue;
    // Mixamo FBX ships duplicate nodes (fighter-web: 124 nodes for 52 names),
    // including a copy of the hand parented to the hand itself, sitting at the
    // same position. It is not a finger — averaging its "plane" in would skew
    // the palm axis. Same coincident-node rule the rig builder uses above.
    if (root.getWorldPosition(new THREE.Vector3()).distanceTo(handWorld) <= 1e-5) continue;
    const pts = [handPos];
    const walk = (b) => {
      pts.push(toRoot(b));
      for (const ch of b.children) if (ch.isBone || ch.type === "Bone") walk(ch);
    };
    walk(root);
    const n = fittedPlaneNormal(pts);
    if (!n) continue;
    if (n.dot(ref) < 0) n.negate();
    acc.add(n);
    used += 1;
  }
  if (!used || acc.lengthSq() < MIN_DIR) return null;
  return acc.normalize();
}

/** Build Mixamo rig map with rest caches + MiKaPo-style witness rest vectors. */
export function buildAvatarRig(model) {
  const allBones = [];
  model.traverse((node) => {
    if (node.isBone || node.type === "Bone") allBones.push(node);
  });
  const specs = [
    ["hips", ["hips"], ["spine"]],
    // The trunk chain NAMES its reference child. Without childAliases the aim
    // axis is whichever child the exporter happened to list first, and Spine2
    // has three (LeftShoulder, RightShoulder, Neck). On the boxeador GLB that is
    // LeftShoulder, so the upper spine's "along the chain" axis sat 26.5° off
    // vertical with a 0.42 lateral share, and the retarget aimed that sideways
    // axis at a vertical target — a permanent torso twist. Measured on real NLF
    // frames, naming the child cut the boxeador's constant hip→shoulder twist
    // error from -3.6° to -1.0°; fighter-web, whose exporter lists Neck first,
    // was unchanged at +4.8° (the control). Same exporter-order hazard the hand
    // childAliases already guard against.
    ["spine", ["spine"], ["spine1"]],
    ["spine1", ["spine1"], ["spine2"]],
    ["spine2", ["spine2"], ["neck", "spine3"]],
    ["neck", ["neck"], ["head"]],
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
    // Resolve childAliases in ALIAS order, not child order. Scanning children
    // first makes the result depend on how the exporter happened to order them:
    // on fighter-web that picked Index on the left hand and Middle on the right,
    // so the two hands ended up aimed off different reference fingers.
    let child = null;
    for (const alias of childAliases || []) {
      child = children?.find((node) => normalizedBoneName(node.name).endsWith(alias)) || null;
      if (child) break;
    }
    child = child || children?.[0] || null;
    if (!bone || !bone.parent) continue;
    // A leaf bone has no child to point at (e.g. FBXLoader does not expose
    // Mixamo's HeadTop_End, so Head is childless). Fall back to continuing the
    // chain: parent -> bone. That is the same axis the child would have given,
    // just measured one link earlier, so nothing downstream needs to know.
    const boneWorld = bone.getWorldPosition(new THREE.Vector3());
    let restDirection;
    if (child) {
      restDirection = child.getWorldPosition(new THREE.Vector3()).sub(boneWorld);
    } else if (bone.parent.isBone || bone.parent.type === "Bone") {
      restDirection = boneWorld.clone().sub(bone.parent.getWorldPosition(new THREE.Vector3()));
    } else {
      continue;
    }
    if (restDirection.lengthSq() < MIN_DIR) continue;
    restDirection.normalize();
    // Bone-local form of the same axis. For a child bone this equals
    // child.position.normalize(); deriving it from restDirection keeps the two
    // cases on one formula.
    const restLocalDirection = restDirection
      .clone()
      .applyQuaternion(bone.getWorldQuaternion(new THREE.Quaternion()).invert())
      .normalize();
    bones.set(key, {
      bone,
      child: child || null,
      restLocalQuaternion: bone.quaternion.clone(),
      restLocalPosition: bone.position.clone(),
      restLocalDirection,
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
  // Trunk bones keep a canonical UPRIGHT blend reference. Rigs are authored in
  // different neutral poses: fighter-web ships with the torso already leaning
  // ~21° forward and the neck ~52°, so blending `strength` toward the RAW rest
  // leaves that authored lean in every frame — the character looks hunched next
  // to a T-pose rig on the same pose. Blending toward the bone's UPRIGHT
  // orientation instead makes `strength` mean "how far from neutral toward the
  // target", independent of the authored rest. T-pose rigs (rest ≈ upright) are
  // unchanged: for them restUprightInRoot ≈ restQuaternionInRoot.
  const trunkUp = new THREE.Vector3(0, 1, 0);
  for (const name of ["hips", "spine", "spine1", "spine2", "neck", "head"]) {
    const rest = bones.get(name);
    if (!rest) continue;
    const dir = rest.restDirectionInRoot.clone();
    if (dir.lengthSq() < MIN_DIR) continue;
    const up = new THREE.Quaternion().setFromUnitVectors(dir.normalize(), trunkUp);
    rest.restUprightInRoot = up.multiply(rest.restQuaternionInRoot.clone());
  }
  // ForeArm + Hand: rest palm-across fitted from the rig's own FINGER geometry,
  // not from the T-pose estimate (boneDir × up). This GLB's rest is an A-pose,
  // so that estimate sat 41° (left) / 35° (right) off the real palm plane, which
  // rotated the applied pronation away from the fit's palm — the fist stayed
  // lateral instead of turning palm-down on the punch. See deriveRestPalmAcross.
  for (const [handKey, foreKey] of [
    ["leftHand", "leftForeArm"],
    ["rightHand", "rightForeArm"],
  ]) {
    const hand = bones.get(handKey);
    const fore = bones.get(foreKey);
    if (!hand || !fore) continue;
    // The ForeArm is driven with the PALM across (pronation lives there), so it
    // must share the hand's rest reference. Giving it its own `dir × up` had the
    // two bones rolling against axes ~25° apart on this rig.
    const across = deriveRestPalmAcross(hand, inverseRoot);
    if (across) {
      hand.restAcrossInRoot = across.clone();
      fore.restAcrossInRoot = across.clone();
    } else {
      // Fallback (rig without index bones / no usable glove geometry): keep the
      // old T-pose estimate so aim-only rigs behave as before.
      for (const bone of [hand, fore]) {
        const est = new THREE.Vector3().crossVectors(
          bone.restDirectionInRoot,
          new THREE.Vector3(0, 1, 0),
        );
        if (est.lengthSq() > MIN_DIR) bone.restAcrossInRoot = est.normalize();
      }
    }
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

function applyWorldRotationToBone(model, rest, targetWorld, strength = 1, timestampMs, rig, name, blendBaseWorld = null) {
  const rootWorld = model.getWorldQuaternion(new THREE.Quaternion());
  const restWorld = rootWorld.clone().multiply(rest.restQuaternionInRoot);
  const base = blendBaseWorld || restWorld;
  const blendedWorld = base.clone().slerp(targetWorld, strength);
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
  const blendBase = rest.restUprightInRoot
    ? rootWorld.clone().multiply(rest.restUprightInRoot)
    : restWorld;
  applyWorldRotationToBone(model, rest, targetWorld, strength, timestampMs, rig, name, blendBase);
  return true;
}

/**
 * Aim + twist using an across vector (hips / spine / palm).
 * Twist is the acute rotation (<90°) in the plane ⊥ bone dir, faded when
 * across is nearly parallel to the bone (overhead / occluded fingers).
 */
function rotateBoneWithAcross(
  model,
  rig,
  name,
  directionInRoot,
  acrossInRoot,
  strength = 1,
  timestampMs = null,
  acuteTwist = false,
  noAcuteFlip = false,
  fade = null,
) {
  const fadeLo = fade ? fade.lo : ACROSS_FADE_LO;
  const fadeHi = fade ? fade.hi : ACROSS_FADE_HI;
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
  const blendBase = rest.restUprightInRoot
    ? rootWorld.clone().multiply(rest.restUprightInRoot)
    : restWorld;

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
  const obs = desiredAcross.length();
  if (alignedAcross.lengthSq() > MIN_DIR && obs >= fadeLo) {
    alignedAcross.normalize();
    desiredAcross.normalize();
    // Hands/forearms only: a sign flip of pinky−index would otherwise apply ~180°.
    // When the across comes from the fit's rotations (noAcuteFlip) the sign is
    // MEANINGFUL (the fit palm is continuous) — flipping it would mirror the palm.
    if (acuteTwist && !noAcuteFlip && alignedAcross.dot(desiredAcross) < 0) desiredAcross.negate();
    const twisted = new THREE.Quaternion()
      .setFromUnitVectors(alignedAcross, desiredAcross)
      .multiply(targetWorld.clone());
    let t = (obs - fadeLo) / (fadeHi - fadeLo);
    t = Math.min(1, Math.max(0, t));
    t = t * t * (3 - 2 * t);
    if (targetWorld.dot(twisted) < 0) {
      twisted.x *= -1;
      twisted.y *= -1;
      twisted.z *= -1;
      twisted.w *= -1;
    }
    targetWorld.slerp(twisted, t);
  }
  applyWorldRotationToBone(model, rest, targetWorld, strength, timestampMs, rig, name, blendBase);
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
  { mode = "yawFromDir", strength = 0.9, pitchStrength = 0, timestampMs = null } = {},
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

  let targetWorld = new THREE.Quaternion().setFromAxisAngle(upWorld, yaw).multiply(restWorld);
  if (pitchStrength > 0) {
    // Pitch (plantar/dorsiflexion) from the live ankle→toe elevation; roll stays untouched.
    const livePitch = Math.asin(THREE.MathUtils.clamp(liveW.clone().normalize().dot(upWorld), -1, 1));
    const restPitch = Math.asin(THREE.MathUtils.clamp(restToe.clone().normalize().dot(upWorld), -1, 1));
    const dPitch = THREE.MathUtils.clamp(livePitch - restPitch, -1.15, 1.15) * pitchStrength;
    const pitchAxis = new THREE.Vector3().crossVectors(upWorld, liveH).normalize();
    if (pitchAxis.lengthSq() > MIN_DIR) {
      targetWorld = new THREE.Quaternion().setFromAxisAngle(pitchAxis, -dPitch).multiply(targetWorld);
    }
  }
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
  const keys = [
    "pelvis", "left_hip", "right_hip",
    "left_ankle", "right_ankle", "left_foot", "right_foot",
    "left_wrist", "right_wrist", "left_hand", "right_hand",
    "left_elbow", "right_elbow",
    "left_shoulder", "right_shoulder", "left_collar", "right_collar",
    "spine1", "spine2", "spine3", "neck", "head",
    "jaw", "left_eye", "right_eye",
    "left_index", "right_index", "left_pinky", "right_pinky",
    "left_middle", "right_middle", "left_thumb", "right_thumb",
  ];
  const out = { kind: "smpl" };
  for (const name of keys) {
    const p = auxSmpl[name];
    if (!p) continue;
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
  // Real head orientation from SMPL-X eyes: twist follows the head, not the torso.
  const eyeAcross = (aux.left_eye && aux.right_eye)
    ? aux.right_eye.clone().sub(aux.left_eye)
    : null;
  if (eyeAcross && eyeAcross.lengthSq() > MIN_DIR) {
    // Eye separation is ~0.07 m — far below ACROSS_FADE_LO (0.12 m), which would
    // zero the twist out and leave the head frozen. Eye distance is fixed by
    // anatomy, not observability, so the direction is always trustworthy: scale
    // to a full-confidence across so the yaw twist applies at full weight.
    const eyeTwist = eyeAcross.normalize().multiplyScalar(0.4);
    // Neck was 0.4, which left the head turn visibly short: measured against the
    // fit, the neck was the worst bone in the body (aim 7.9°, twist 10.5°) while
    // every other bone sat at 2-4°. 0.75 cuts that to 3.4° / 8.5° and changes no
    // other bone. It is NOT trading smoothness for it: at 0.75 the neck's
    // frame-to-frame jitter is 1.96° p50 vs the FIT's own 2.73°, i.e. still
    // steadier than the source it is following (0.4 gave 1.54°).
    // Caveat: measured on fit-driven (smooth) input. The live x55 path is much
    // noisier, so re-check jitter there before assuming this transfers.
    rotateBoneWithAcross(model, rig, "neck", basis.up, eyeTwist, 0.75, timestampMs);
    rotateBoneWithAcross(model, rig, "head", basis.up, eyeTwist, 0.9, timestampMs);
    return;
  }
  // No eyes (legacy SMPL24 aux): shoulder-across twist + soft torso-forward yaw.
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

/** Live-tunable SMPL/Pose33 hand palm polarity (see Live → Calibrar mãos). */export const handRetargetOpts = {
  palmEnabled: true,
  /** Kept for the Live calib UI; ignored — hand×forearm across is never used. */
  swapCrossOrder: true,
  negateAcrossLeft: true,
  negateAcrossRight: false,
  /** Skip ForeArm pronation — only aim Hand along palm forward. */
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
 * Across is index/pinky only. Without fingers, across is null (aim, no twist).
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
    if (across.lengthSq() < MIN_DIR) {
      return { forward: forward.normalize(), across: null };
    }
    return { forward: forward.normalize(), across: across.normalize() };
  }
  const hand = aux[`${side}_hand`];
  if (!wrist || !hand) return null;
  const forward = hand.clone().sub(wrist);
  if (forward.lengthSq() < MIN_DIR) return null;
  return { forward: forward.normalize(), across: null };
}

function applyHandAimFromAux(model, rig, aux, side, timestampMs, fitPalm = false) {
  if (!handRetargetOpts.palmEnabled) return;
  const handName = side === "left" ? "leftHand" : "rightHand";
  if (!rig.bones.get(handName) || !aux) return;
  const axes = computeHandPalmAxes(aux, side);
  if (!axes) return;
  // ForeArm already carries pronation. Hand still needs the same across in world
  // space; otherwise shortest-arc aim leaves the fist at rest roll (~90° off).
  // Fit-palm path is exact (the fit knows the palm); live keeps the 0.85 smooth.
  const strength = fitPalm ? 1.0 : 0.85;
  if (handRetargetOpts.aimOnly || !axes.across) {
    rotateBoneToward(model, rig, handName, axes.forward, strength, timestampMs);
    return;
  }
  rotateBoneWithAcross(model, rig, handName, axes.forward, axes.across, strength, timestampMs, true, fitPalm, UNIT_ACROSS_FADE);
}

/**
 * Standing-neutral collar elevation/azimuth in the live torso frame (viewer Y-up).
 * Benchmark NLF mean elev ≈ 0°; T-pose SMPL-X cano is ~+40° and is NOT a relaxed shrug zero.
 */
const SMPL_SHOULDER_NEUTRAL = { elev: 0, az: 0 };

/**
 * Clavicle: keep Mixamo rest as the visual zero, add only (live − neutral) deltas from NLF.
 * Absolute SMPL collar aim lifts Mixamo because Mixamo rest points down and SMPL neutral is flatter.
 */
function applyShoulderFromSmpl(model, rig, aux, side, timestampMs) {
  const name = side === "left" ? "leftShoulder" : "rightShoulder";
  const rest = rig?.bones.get(name);
  const collar = aux?.[`${side}_collar`];
  const sh = aux?.[`${side}_shoulder`];
  if (!rest || !collar || !sh || !aux.left_shoulder || !aux.right_shoulder || !aux.neck) {
    return false;
  }

  // Torso frame from live shoulders + neck (more stable than spine1 on bent poses).
  const hipMid = (aux.left_hip && aux.right_hip)
    ? aux.left_hip.clone().add(aux.right_hip).multiplyScalar(0.5)
    : (aux.pelvis ? aux.pelvis.clone() : null);
  const upU = hipMid
    ? aux.neck.clone().sub(hipMid)
    : aux.neck.clone().sub(aux.spine1 || collar);
  const across = aux.right_shoulder.clone().sub(aux.left_shoulder);
  if (upU.lengthSq() < MIN_DIR || across.lengthSq() < MIN_DIR) return false;
  upU.normalize();
  const acrossU = across.addScaledVector(upU, -across.dot(upU));
  if (acrossU.lengthSq() < MIN_DIR) return false;
  acrossU.normalize();
  const fwdU = new THREE.Vector3().crossVectors(acrossU, upU);
  if (fwdU.lengthSq() < MIN_DIR) return false;
  fwdU.normalize();

  const live = sh.clone().sub(collar);
  if (live.lengthSq() < MIN_DIR) return false;
  live.normalize();

  const latU = acrossU.clone().multiplyScalar(side === "left" ? -1 : 1);
  const liveElev = Math.asin(THREE.MathUtils.clamp(live.dot(upU), -1, 1));
  const liveAz = Math.atan2(live.dot(fwdU), live.dot(latU));
  const dElev = THREE.MathUtils.clamp(liveElev - SMPL_SHOULDER_NEUTRAL.elev, -1.2, 1.2);
  let dAz = liveAz - SMPL_SHOULDER_NEUTRAL.az;
  dAz = Math.atan2(Math.sin(dAz), Math.cos(dAz));
  dAz = THREE.MathUtils.clamp(dAz, -1.2, 1.2);

  // Mixamo rest spherical coords in upright root; recompose on LIVE torso axes.
  const upR = new THREE.Vector3(0, 1, 0);
  const restDir = rest.restDirectionInRoot.clone().normalize();
  const latR = restDir.clone().addScaledVector(upR, -restDir.dot(upR));
  if (latR.lengthSq() < MIN_DIR) return false;
  latR.normalize();
  const restElev = Math.asin(THREE.MathUtils.clamp(restDir.dot(upR), -1, 1));
  const restAz = Math.atan2(restDir.dot(new THREE.Vector3(0, 0, -1)), restDir.dot(latR));
  const e = restElev + dElev;
  const az = restAz + dAz;
  const targetDir = latU.clone().multiplyScalar(Math.cos(e) * Math.cos(az))
    .addScaledVector(fwdU, Math.cos(e) * Math.sin(az))
    .addScaledVector(upU, Math.sin(e));
  if (targetDir.lengthSq() < MIN_DIR) return false;
  return rotateBoneToward(model, rig, name, targetDir.normalize(), 1, timestampMs);
}

/**
 * Baker-top v2: add the fit's LOCAL bone-axis rolls (pronation, spine torsion)
 * as a world-space twist about the LIVE bone axis, on top of the position-based
 * aim. Direction always comes from positions (the fit's joint directions), so
 * the pose can never go inverted/broken; only the roll about the axis is taken
 * from the fit's rotations. `twist` = { boneName: deg } per frame, about the
 * live axis in viewer space. The roll is a LOCAL quantity (the child joint's
 * rotation about the parent's bone axis), so it is small, stable and free of
 * the axis-angle decomposition ambiguity of full-frame transfer.
 */
export function applyFitTwists(model, rig, twist, pose, nameToIndex, aux, timestampMs = null) {
  if (!model || !rig || !twist) return;
  const P = (name) => {
    const idx = nameToIndex[name];
    if (idx == null || !pose[idx]) return null;
    return new THREE.Vector3(pose[idx][0], pose[idx][1], pose[idx][2]);
  };
  const axisFor = (name) => {
    if (name === "leftForeArm" || name === "rightForeArm") {
      const el = P(name === "leftForeArm" ? "left_elbow" : "right_elbow");
      const wr = P(name === "leftForeArm" ? "left_wrist" : "right_wrist");
      return el && wr ? wr.clone().sub(el) : null;
    }
    if (name === "spine1") {
      return aux?.spine2 && aux?.spine1 ? aux.spine2.clone().sub(aux.spine1) : null;
    }
    if (name === "spine2") {
      return aux?.spine3 && aux?.spine2 ? aux.spine3.clone().sub(aux.spine2) : null;
    }
    return null;
  };
  for (const [name, deg] of Object.entries(twist)) {
    const rest = rig?.bones.get(name);
    if (!rest) continue;
    const axis = axisFor(name);
    if (!axis || axis.lengthSq() < MIN_DIR) continue;
    axis.normalize();
    const cur = rest.bone.getWorldQuaternion(new THREE.Quaternion());
    const roll = new THREE.Quaternion().setFromAxisAngle(axis, THREE.MathUtils.degToRad(Number(deg) || 0));
    const targetWorld = roll.multiply(cur);
    applyWorldRotationToBone(model, rest, targetWorld, 1, timestampMs, rig, name);
  }
}

/**
 * Apply lab pose to Mixamo avatar (MiKaPo-style FK + witness).
 *
 * @param {object} opts
 * @param {object|null} [opts.aux]  pose-33 viewer-space points from auxFromPose33
 * @param {boolean} [opts.plantGround=true]
 * @param {number} [opts.groundY=0}
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
  useCollarShoulders = false,
  useSurfaceBody = false,
  surfaceAux = null,
  aux = null,
  plantGround = true,
  groundY = 0,
  twist = null,
  fitPalm = false,
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
  const B = (name) => (
    useSurfaceBody && surfaceAux?.[name] ? surfaceAux[name].clone() : P(name)
  );

  updateJointTranslations(model, rig, pose, nameToIndex, shoulderWidth, motion, "shoulder");

  const leftHip = B("left_hip");
  const rightHip = B("right_hip");
  if (!leftHip || !rightHip) return;
  const hipCenter = leftHip.clone().add(rightHip).multiplyScalar(0.5);
  const isSmplAux = aux?.kind === "smpl";
  const torso = hipCenter.clone().negate();
  if (!isSmplAux) {
    // MediaPipe-era amplification hack; NLF trunk direction is trustworthy as-is.
    torso.x *= 1.5;
    torso.z *= 1.5;
  }

  // Spine chain, built BEFORE hips so the pelvis can share its first segment.
  //
  // NLF interior spine joints (spine1/2/3) oscillate with alternating-sign
  // bends of 20-40° per segment even when the fitted SMPL-X mesh — whose skin
  // averages every vertex over several bones (LBS) — shows a straight trunk.
  // Invisible on the mesh, that zig-zag becomes a visible S-curve ("crooked
  // bone") when retargeted 1:1 onto Mixamo bones. Two Laplacian passes on the
  // interior waypoints kill the oscillation while preserving real sustained
  // bends (forward lean): measured on nlf_fit_webcam1 f37/65/528/1052, the
  // spine→spine1 kink dropped 35-51° → ≤15° with trunk lean unchanged (<1°).
  let spineWaypoints = null;
  if (aux?.spine1 && aux?.spine2 && aux?.spine3 && aux?.neck) {
    spineWaypoints = [aux.pelvis, aux.spine1, aux.spine2, aux.spine3, aux.neck]
      .filter((p) => p)
      .map((p) => p.clone());
    if (isSmplAux && spineWaypoints.length >= 3) {
      for (let iter = 0; iter < 2; iter++) {
        for (let i = 1; i < spineWaypoints.length - 1; i++) {
          const mid = spineWaypoints[i - 1].clone().add(spineWaypoints[i + 1]).multiplyScalar(0.5);
          spineWaypoints[i].lerp(mid, 0.5);
        }
      }
    }
  }

  updateRootTranslation(model, rig, pose, nameToIndex, shoulderCenter, shoulderWidth, motion);
  // Hips share the chain's first segment (pelvis→spine1) instead of the
  // shoulder-normalised "-hipCenter": the two definitions disagreed by 17-30°
  // per frame, a permanent extra kink at the hips→spine junction.
  const hipsDir = spineWaypoints && spineWaypoints.length >= 2
    ? spineWaypoints[1].clone().sub(spineWaypoints[0])
    : torso;
  rotateBoneWithAcross(
    model, rig, "hips",
    hipsDir.lengthSq() > MIN_DIR ? hipsDir : torso,
    rightHip.clone().sub(leftHip), isSmplAux ? 0.95 : 0.78, timestampMs,
  );
  updateJointTranslations(model, rig, pose, nameToIndex, shoulderWidth, motion, "hip");

  const leftSh = B("left_shoulder");
  const rightSh = B("right_shoulder");
  if (!leftSh || !rightSh) return;
  const shoulderAcross = rightSh.clone().sub(leftSh);

  // Multi-segment spine bending using SMPL spine points when available.
  //
  // The rig has 3 spine bones spanning hips→neck but SMPL-X has 4 segments
  // there (pelvis→spine1→spine2→spine3→neck). Mapping each rig bone to the
  // segment ABOVE it (dropping pelvis→spine1) shifts every bone one segment
  // forward; in a bent trunk each segment leans further than the one below, so
  // the errors add up the chain — measured as ~+9° of excess trunk lean.
  //
  // Fix: cover the WHOLE chain with a continuous chain parameterisation (bone i
  // spans [i*seg/count, (i+1)*seg/count], interpolated between waypoints), so
  // no segment is dropped and none is doubled. The stride derives from the
  // waypoint count, which also generalises to rigs with 1, 2 or 4 spine bones.
  if (spineWaypoints) {
    // Waypoints were built (and de-zigzagged for SMPL aux) before the hips
    // rotation above; reuse them here.
    const waypoints = spineWaypoints;
    const present = ["spine", "spine1", "spine2"].filter((n) => rig.bones.get(n));
    const st = isSmplAux ? 0.95 : 0.7;
    const count = present.length;
    const seg = waypoints.length - 1;
    const chainPoint = (u) => {
      const s = Math.min(seg - 1, Math.floor(u));
      const f = u - s;
      return waypoints[s].clone().lerp(waypoints[s + 1], f);
    };
    for (let i = 0; i < count; i++) {
      const a = chainPoint((i * seg) / count);
      const b = chainPoint(((i + 1) * seg) / count);
      const dir = b.clone().sub(a);
      if (dir.lengthSq() > MIN_DIR) {
        rotateBoneWithAcross(model, rig, present[i], dir, shoulderAcross, st, timestampMs);
      }
    }
  } else {
    rotateBoneWithAcross(model, rig, "spine", torso, shoulderAcross, 0.28, timestampMs);
    rotateBoneWithAcross(model, rig, "spine1", torso, shoulderAcross, 0.48, timestampMs);
    rotateBoneWithAcross(model, rig, "spine2", torso, shoulderAcross, 0.7, timestampMs);
  }

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

  const shoulderAux = useSurfaceBody && surfaceAux ? surfaceAux : aux;
  const leftCollarDir = shoulderAux?.left_shoulder?.clone().sub(shoulderAux.left_collar);
  const rightCollarDir = shoulderAux?.right_shoulder?.clone().sub(shoulderAux.right_collar);
  const usedSmplShoulder = {
    left: isSmplAux && applyShoulderFromSmpl(model, rig, aux, "left", timestampMs),
    right: isSmplAux && applyShoulderFromSmpl(model, rig, aux, "right", timestampMs),
  };

  if (!usedSmplShoulder.left) {
    if ((useCollarShoulders || useSurfaceBody || aux?.kind === "smpl") && leftCollarDir?.lengthSq() > MIN_DIR) {
      rotateBoneToward(model, rig, "leftShoulder", leftCollarDir, 1.0, timestampMs);
    } else if (leftSh) {
      rotateBoneToward(model, rig, "leftShoulder", leftSh, 0.5, timestampMs);
    }
  }
  if (!usedSmplShoulder.right) {
    if ((useCollarShoulders || useSurfaceBody || aux?.kind === "smpl") && rightCollarDir?.lengthSq() > MIN_DIR) {
      rotateBoneToward(model, rig, "rightShoulder", rightCollarDir, 1.0, timestampMs);
    } else if (rightSh) {
      rotateBoneToward(model, rig, "rightShoulder", rightSh, 0.5, timestampMs);
    }
  }

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
    const palm = aux ? computeHandPalmAxes(aux, side) : null;
    // Baker-top: when the fit's local pronation twist is provided, use it for the
    // ForeArm roll (aim still from positions) instead of the noisy index-pinky across.
    // Key presence (even 0) opts into the fit roll path.
    const fitBone = side === "left" ? "leftForeArm" : "rightForeArm";
    const hasFitTwist = twist != null && Object.prototype.hasOwnProperty.call(twist, fitBone);
    if (palm?.across && handRetargetOpts.palmEnabled && !handRetargetOpts.aimOnly && !hasFitTwist) {
      rotateBoneWithAcross(model, rig, fore, foreDir, palm.across, 1, timestampMs, true, fitPalm, UNIT_ACROSS_FADE);
    } else {
      rotateBoneToward(model, rig, fore, foreDir, 1, timestampMs);
    }
  }

  // Hand aims along palm forward; pronation already lives on ForeArm.
  if (aux) {
    applyHandAimFromAux(model, rig, aux, "left", timestampMs, fitPalm);
    applyHandAimFromAux(model, rig, aux, "right", timestampMs, fitPalm);
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
      rotateFoot(model, rig, footName, dir, {
        mode,
        strength: 0.85,
        pitchStrength: aux?.kind === "smpl" ? 0.9 : 0,
        timestampMs,
      });
    }
  }

  // Baker-top: add the fit's LOCAL rolls (pronation, torsion) about the live
  // axis, after the position solve (aim never changes; only roll is refined).
  if (twist) applyFitTwists(model, rig, twist, pose, nameToIndex, aux, timestampMs);

  if (plantGround) plantAvatarOnGround(model, rig, groundY);
}
