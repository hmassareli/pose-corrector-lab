/**
 * Single source of truth for the characters the viewers can drive.
 *
 * Before this, every viewer hardcoded its own loader + URL + scale
 * (index.html an FBX at 0.01, live.html and the bake viewers a GLB at 1.0), so
 * swapping a character meant editing each file and knowing its unit convention.
 * The registry keeps the per-asset quirks (format, unit scale) next to the asset
 * instead of spread across callers.
 *
 * `scale` is the factor that brings the asset to METRES, which is the space the
 * solver and the fit data share. FBX from Mixamo is authored in centimetres.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { buildAvatarRig } from "/static/mikapo_mixamo_solver.js";

/**
 * Every character is rescaled so its SKELETON (lowest foot bone to head bone) is
 * this tall, which is what makes one camera framing and one ground plane work
 * for all of them. Measured raw: boxeador 0.822, fighter-web 1.402 — a 1.71x
 * difference that would otherwise push a new character out of frame.
 *
 * The value is the boxeador's own height, chosen for COMPATIBILITY rather than
 * physical realism: it keeps existing camera setups and already-rendered videos
 * framed exactly as before, so swapping characters is the only variable.
 *
 * Measured from bones, not Box3.setFromObject — that returns garbage on skinned
 * meshes (it reported 2 mm for the boxeador, whose skeleton is 0.82).
 */
export const CANONICAL_SKELETON_HEIGHT = 0.8218;

function skeletonHeight(root) {
  const rig = buildAvatarRig(root);
  const y = (key) => {
    const rest = rig.bones.get(key);
    return rest ? rest.bone.getWorldPosition(new THREE.Vector3()).y : null;
  };
  const head = y("head");
  const feet = [y("leftFoot"), y("rightFoot")].filter((v) => v !== null);
  if (head === null || !feet.length) return null;
  const h = head - Math.min(...feet);
  return h > 1e-6 ? h : null;
}

export const AVATARS = [
  {
    id: "boxer-prism31",
    label: "Boxeador Prism 3.1 (Mixamo)",
    url: "/assets/boxer_prism31_rig.glb",
    format: "glb",
    scale: 1.0,
    // Mixamo exported this character facing +X; the solver expects +Z.
    yaw: -Math.PI / 2,
    note: "Rig Mixamo em pose de repouso, sem animação embutida",
  },
  {
    id: "boxeador",
    label: "Boxeador (Trellis GLB)",
    url: "/assets/boxeador_mixamo_trellis.glb",
    format: "glb",
    scale: 1.0,
    note: "index finger chain only",
  },
  {
    id: "fighter-web",
    label: "Fighter Web (FBX)",
    url: "/assets/fighter-web.fbx",
    format: "fbx",
    scale: 0.01,
    // The FBX references its 6 maps by bare filename (eye.png, head_f.png, ...),
    // which the loader would resolve next to the .fbx and 404. They live in a
    // subfolder, so point the loader there instead of flattening copies into
    // /assets. Each asset declares its own layout.
    resourcePath: "/assets/textures/",
    note: "full 5-finger hands",
  },
];

export const DEFAULT_AVATAR_ID = "boxeador";

export function getAvatarSpec(id) {
  return AVATARS.find((a) => a.id === id) || AVATARS.find((a) => a.id === DEFAULT_AVATAR_ID);
}

/**
 * Load a character by registry id and return its root Object3D, already scaled
 * to metres and with materials made opaque (several of these assets ship with
 * alpha settings that render the body see-through under the bake lighting).
 */
export async function loadAvatar(id) {
  const spec = getAvatarSpec(id);
  const loader = spec.format === "fbx" ? new FBXLoader() : new GLTFLoader();
  if (spec.resourcePath) loader.setResourcePath(spec.resourcePath);
  const loaded = await loader.loadAsync(spec.url);
  const root = spec.format === "fbx" ? loaded : loaded.scene;
  if (spec.yaw) {
    // Correct the asset BELOW the solver root, so its reference axes remain
    // +Y up / +Z forward. Rotating the root itself would rotate mocap targets
    // too and cancel the correction. Keep mesh and skeleton together.
    const orientation = new THREE.Group();
    for (const child of [...root.children]) orientation.add(child);
    orientation.rotation.y = spec.yaw;
    root.add(orientation);
  }
  root.scale.setScalar(spec.scale);
  root.traverse((node) => {
    if (!node.isMesh || !node.material) return;
    for (const m of Array.isArray(node.material) ? node.material : [node.material]) {
      m.transparent = false;
      m.alphaTest = 0;
      m.depthWrite = true;
      m.needsUpdate = true;
    }
  });
  root.updateWorldMatrix(true, true);
  // Normalise size so callers can keep one camera and one ground plane.
  const h = skeletonHeight(root);
  if (h) {
    root.scale.multiplyScalar(CANONICAL_SKELETON_HEIGHT / h);
    root.updateWorldMatrix(true, true);
  }
  return { root, spec, skeletonHeight: h };
}

/** Populate a <select> with the registry; returns the chosen id. */
export function fillAvatarSelect(select, selectedId, { includePreview = false } = {}) {
  select.innerHTML = "";
  for (const a of AVATARS) {
    if (a.previewOnly && !includePreview) continue;
    const opt = document.createElement("option");
    opt.value = a.id;
    opt.textContent = a.label;
    if (a.id === selectedId) opt.selected = true;
    select.appendChild(opt);
  }
  return select.value;
}
