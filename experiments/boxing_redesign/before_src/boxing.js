import { BoxingAudio } from "/static/boxing_audio.js";
import * as THREE from "three";
import {
  loadAvatar,
  fillAvatarSelect,
  CANONICAL_SKELETON_HEIGHT,
} from "/static/avatar_assets.js";
import {
  buildAvatarRig,
  createAvatarMotion,
  updateAvatarPose,
  setRetargetSmoothing,
  setRetargetBoneSmoothing,
  resetRetargetFilters,
  footDirectionsFromSmplAux,
  headForwardFromSmplAux,
} from "/static/mikapo_mixamo_solver.js";
import {
  clamp,
  JOINTS,
  validPose,
  demoPose,
  neutralPose,
  PunchDetector,
  guarded,
  orbitalStep,
  orbitalShift,
  radialShift,
  WebcamFootwork,
  segmentSphere,
  segmentCapsule,
  PoseRenderBuffer,
} from "/static/boxing_core.mjs";
import { DuelConnection } from "/static/boxing_net.js";
import { FootPlanting } from "/static/boxing_feet.js";
const $ = (id) => document.getElementById(id),
  sound = new BoxingAudio();
let effect = null,
  lastEffect = 0;
function reviveVector(p) {
  if (!p) return null;
  const v = [p.x ?? p[0], p.y ?? p[1], p.z ?? p[2]];
  return v.every(Number.isFinite) ? new THREE.Vector3(...v) : null;
}
function constrainFacing(p, aux) {
  // Align the base to the opponent without cancelling chest rotation in hooks.
  const across = new THREE.Vector3(...p[1]).sub(new THREE.Vector3(...p[2]));
  const heading = Math.atan2(-across.z, across.x);
  const correction = clamp(heading, -Math.PI / 15, Math.PI / 15) - heading;
  const c = Math.cos(correction),
    sn = Math.sin(correction),
    pivot = new THREE.Vector3(...p[0]);
  const rotate = (v) => {
    const x = v.x - pivot.x,
      z = v.z - pivot.z;
    v.x = pivot.x + x * c + z * sn;
    v.z = pivot.z - x * sn + z * c;
    return v;
  };
  for (let i = 0; i < p.length; i++)
    p[i] = rotate(new THREE.Vector3(...p[i])).toArray();
  if (aux) {
    const anchor = aux.pelvis?.clone() || new THREE.Vector3();
    for (const [key, v] of Object.entries(aux))
      if (v?.isVector3) {
        const x = v.x - anchor.x,
          z = v.z - anchor.z;
        v.x = anchor.x + x * c + z * sn;
        v.z = anchor.z - x * sn + z * c;
      }
  }
  return p;
}
function demoAux(p) {
  const aux = { kind: "smpl" };
  for (const [name, i] of Object.entries(JOINTS))
    aux[name] = new THREE.Vector3(...p[i]);
  for (const [name, v] of Object.entries({
    spine1: [0, 1.05, 0],
    spine2: [0, 1.2, 0],
    spine3: [0, 1.4, 0],
    left_collar: [0.075, 1.43, 0],
    right_collar: [-0.075, 1.43, 0],
    left_eye: [0.035, 1.74, 0.075],
    right_eye: [-0.035, 1.74, 0.075],
    left_foot: [0.19, 0.05, 0.24],
    right_foot: [-0.19, 0.05, 0.09],
  }))
    aux[name] = new THREE.Vector3(...v);
  aux.head.z += 0.065;
  return aux;
}
function reviveAux(aux) {
  if (!aux || typeof aux !== "object") return null;
  const out = { kind: aux.kind };
  for (const [k, v] of Object.entries(aux)) {
    if (k === "kind") continue;
    const p = reviveVector(v);
    if (p) out[k] = p;
  }
  return out;
}
const scene = new THREE.Scene();
scene.background = new THREE.Color("#0a101c");
scene.fog = new THREE.FogExp2("#0a101c", 0.055);
const renderer = new THREE.WebGLRenderer({
  canvas: $("arena"),
  antialias: true,
});
renderer.setPixelRatio(Math.min(devicePixelRatio, 1.7));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.02;
const camera = new THREE.PerspectiveCamera(48, 1, 0.05, 80);
camera.position.set(8, 5.2, 8);
const targetCamera = new THREE.Vector3(),
  targetLook = new THREE.Vector3();
function keepEyeOutsideUpperBody(actor, eye, forward) {
  if (!actor) return;
  const point = (name) =>
    actor.rig.bones.get(name)?.bone.getWorldPosition(new THREE.Vector3());
  const heavy = actor.avatarId === "boxeador";
  const capsules = [
    [point("spine2"), point("neck"), heavy ? 0.2 : 0.16],
    [point("leftArm"), point("leftForeArm"), heavy ? 0.18 : 0.14],
    [point("rightArm"), point("rightForeArm"), heavy ? 0.18 : 0.14],
  ].filter(([a, b]) => a && b);
  const origin = eye.clone();
  for (let pass = 0; pass < 3; pass++) {
    for (const [a, b, r] of capsules) {
      const segment = b.clone().sub(a),
        length = segment.lengthSq();
      const t = length
        ? clamp(eye.clone().sub(a).dot(segment) / length, 0, 1)
        : 0;
      const nearest = a.clone().addScaledVector(segment, t);
      const away = eye.clone().sub(nearest),
        distance = away.length();
      if (distance < r + camera.near) {
        if (distance < 0.001) away.copy(forward);
        else away.divideScalar(distance);
        eye.addScaledVector(away, r + camera.near - distance);
      }
    }
    // Prefer the nearest exterior point, with bounded clearance at eye level.
    const correction = eye.clone().sub(origin).clampLength(0, 0.12);
    eye.copy(origin).add(correction);
  }
}
scene.add(new THREE.HemisphereLight("#d5e5fa", "#817b78", 1.1));
const eyeFill = new THREE.PointLight("#ffede0", 0.75, 2.4, 2);
eyeFill.visible = false;
scene.add(eyeFill);
function spot(color, x, y, z, power) {
  const l = new THREE.SpotLight(color, power, 35, 0.6, 0.65, 1.2);
  l.position.set(x, y, z);
  l.target.position.set(0, 1, 0);
  scene.add(l, l.target);
  l.castShadow = x < 0;
  l.shadow.mapSize.set(2048, 2048);
  l.shadow.normalBias = 0.015;
  l.shadow.radius = 3;
  l.shadow.bias = -0.0004;
  return l;
}
spot("#ffdab1", -4, 8, 2, 105);
spot("#adcaff", 4, 7, -4, 90);
spot("#ffffff", 1, 8, 4, 42);
const mat = (color, roughness = 0.75, metalness = 0) =>
  new THREE.MeshStandardMaterial({ color, roughness, metalness });
function box(w, h, d, x, y, z, m) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  mesh.position.set(x, y, z);
  mesh.castShadow = mesh.receiveShadow = true;
  scene.add(mesh);
  return mesh;
}
function tube(a, b, r, m) {
  const dir = new THREE.Vector3().subVectors(b, a),
    mesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, dir.length(), 8), m);
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(
    new THREE.Vector3(0, 1, 0),
    dir.normalize(),
  );
  mesh.castShadow = true;
  scene.add(mesh);
  return mesh;
}
const floor = mat("#111d30"),
  canvasMat = mat("#35475c"),
  gold = mat("#b68d52", 0.35, 0.65),
  blue = mat("#37629c"),
  red = mat("#a84751"),
  white = mat("#d2d3d1");
box(45, 0.1, 45, 0, -0.75, 0, mat("#080d18"));
box(6.9, 0.55, 6.9, 0, -0.35, 0, floor);
box(6.6, 0.09, 6.6, 0, -0.025, 0, canvasMat);
const textureCanvas = document.createElement("canvas");
textureCanvas.width = textureCanvas.height = 1024;
const cx = textureCanvas.getContext("2d");
cx.fillStyle = "#253950";
cx.fillRect(0, 0, 1024, 1024);
let noiseSeed = 17;
for (let y = 0; y < 1024; y += 4)
  for (let x = 0; x < 1024; x += 4) {
    noiseSeed = (noiseSeed * 16807) % 2147483647;
    cx.fillStyle =
      "rgba(180,204,225," + (0.015 + (noiseSeed % 100) / 4000) + ")";
    cx.fillRect(x, y, 2, 1);
  }
cx.strokeStyle = "rgba(165,187,209,.03)";
cx.lineWidth = 1;
for (let q = 0; q < 1024; q += 8) {
  cx.beginPath();
  cx.moveTo(q, 0);
  cx.lineTo(q, 1024);
  cx.moveTo(0, q);
  cx.lineTo(1024, q);
  cx.stroke();
}
cx.strokeStyle = "#4f6680";
cx.lineWidth = 4;
cx.strokeRect(64, 64, 896, 896);
cx.save();
cx.translate(512, 512);
cx.rotate(-Math.PI / 2);
cx.fillStyle = "#95abc160";
cx.font = "800 125px sans-serif";
cx.textAlign = "center";
cx.fillText("CORNER", 0, 25);
cx.font = "22px sans-serif";
cx.fillText("CHAMPIONSHIP  /  2026", 0, 70);
cx.restore();
const tex = new THREE.CanvasTexture(textureCanvas);
tex.colorSpace = THREE.SRGBColorSpace;
const ringTop = new THREE.Mesh(
  new THREE.PlaneGeometry(6.55, 6.55),
  new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95 }),
);
ringTop.rotation.x = -Math.PI / 2;
ringTop.position.y = 0.026;
ringTop.receiveShadow = true;
scene.add(ringTop);
for (const x of [-3.12, 3.12])
  for (const z of [-3.12, 3.12]) {
    box(0.16, 1.62, 0.16, x, 0.78, z, gold);
    box(0.25, 0.75, 0.25, x, 0.94, z, x === z ? blue : red);
  }
for (let j = 0; j < 4; j++) {
  const y = 0.43 + j * 0.31,
    m = [blue, white, white, red][j];
  for (const s of [-1, 1]) {
    tube(
      new THREE.Vector3(-3.12, y, s * 3.12),
      new THREE.Vector3(3.12, y, s * 3.12),
      0.027,
      m,
    );
    tube(
      new THREE.Vector3(s * 3.12, y, -3.12),
      new THREE.Vector3(s * 3.12, y, 3.12),
      0.027,
      m,
    );
  }
}
box(1, 0.18, 0.8, 0, -0.5, 3.85, floor);
box(1, 0.18, 0.8, 0, -0.32, 3.5, floor);
// Low cost instanced audience, separated from the combat silhouettes.
const count = 180,
  crowd = new THREE.InstancedMesh(
    new THREE.CapsuleGeometry(0.13, 0.28, 2, 5),
    mat("#222b3f"),
    count,
  ),
  heads = new THREE.InstancedMesh(
    new THREE.SphereGeometry(0.095, 6, 5),
    mat("#584c4c"),
    count,
  ),
  dummy = new THREE.Object3D();
for (let i = 0; i < count; i++) {
  const side = i % 4,
    row = Math.floor(i / 60),
    col = Math.floor(i / 4) % 15,
    u = (col - 7) * 0.62,
    v = 5.2 + row * 0.95;
  dummy.position.set(
    side < 2 ? u : side === 2 ? v : -v,
    -0.27 + row * 0.24,
    side < 2 ? (side === 0 ? v : -v) : u,
  );
  dummy.rotation.set(
    0,
    (side * Math.PI) / 2 + Math.sin(i * 3.1) * 0.15,
    Math.sin(i * 2.7) * 0.04,
  );
  dummy.updateMatrix();
  crowd.setMatrixAt(i, dummy.matrix);
  crowd.setColorAt(
    i,
    new THREE.Color().setHSL(
      0.61 + (i % 7) * 0.007,
      0.18 + (i % 4) * 0.035,
      0.075 + (i % 5) * 0.016,
    ),
  );
  dummy.position.y += 0.35;
  dummy.updateMatrix();
  heads.setMatrixAt(i, dummy.matrix);
  heads.setColorAt(
    i,
    new THREE.Color().setHSL(0.06, 0.15, 0.18 + (i % 6) * 0.016),
  );
}
scene.add(crowd, heads);
for (const s of [-1, 1]) {
  box(14, 0.45, 2, 0, -0.63, s * 6.2, floor);
  box(2, 0.45, 14, s * 6.2, -0.63, 0, floor);
  tube(
    new THREE.Vector3(-5, 8.5, s * 5),
    new THREE.Vector3(5, 8.5, s * 5),
    0.075,
    gold,
  );
  for (const x of [-4, -2, 0, 2, 4])
    box(
      0.3,
      0.09,
      0.45,
      x,
      8.45,
      s * 5,
      new THREE.MeshBasicMaterial({ color: s < 0 ? "#a4caff" : "#ffc78c" }),
    );
}
function sign(text, x, y, z, rot) {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 128;
  const t = c.getContext("2d");
  t.fillStyle = "#142137";
  t.fillRect(0, 0, 1024, 128);
  t.fillStyle = "#d9ae73";
  t.textAlign = "center";
  t.font = "bold 50px sans-serif";
  t.fillText(text, 512, 85);
  const map = new THREE.CanvasTexture(c);
  map.colorSpace = THREE.SRGBColorSpace;
  const p = new THREE.Mesh(
    new THREE.PlaneGeometry(5.8, 0.72),
    new THREE.MeshBasicMaterial({ map }),
  );
  p.position.set(x, y, z);
  p.rotation.y = rot;
  scene.add(p);
}
sign("C O R N E R   /   CHAMPIONSHIP", 0, -0.29, 3.46, 0);
sign("OWN YOUR NEXT MOVE", 0, 2.8, -7, 0);
$("train").disabled = $("online").disabled = true;
let self = 0,
  active = false,
  online = false,
  ready = false,
  clock = 90,
  round = 1,
  acc = 0,
  last = performance.now(),
  sendTime = 0,
  messageUntil = 0,
  first = false,
  smooth = Number(localStorage.getItem("labAvatarSmoothing") ?? 50),
  cameraOn = false,
  lastPoseTime = 0,
  poseFrameTime = -1,
  baseline = null,
  loaded = false;
const fighters = [0, 1].map((i) => ({
  x: 0,
  z: i === 0 ? -0.68 : 0.68,
  yaw: i === 0 ? 0 : Math.PI,
  hp: 100,
  stun: 0,
  pose: neutralPose(),
  aux: demoAux(neutralPose()),
  lateral: 0,
  radial: 0,
  footwork: new WebcamFootwork(),
  detector: new PunchDetector(),
  attacks: [],
  score: 0,
  avatarId:
    i === 0
      ? localStorage.getItem("labAvatarId") || "boxer-prism31"
      : "boxeador",
}));
const actors = [null, null],
  sparkGroup = new THREE.Group();
const presentation = [new PoseRenderBuffer(), new PoseRenderBuffer()];
const presentedSource = [null, null];
scene.add(sparkGroup);
let sparks = [];
function notify(text, seconds = 1.1) {
  $("combatMessage").textContent = text;
  messageUntil = performance.now() + seconds * 1000;
}
function setSmooth() {
  smooth = clamp(Number($("smooth").value), 0, 100);
  $("smoothValue").textContent = smooth + "%";
  localStorage.setItem("labAvatarSmoothing", smooth);
  for (const buffer of presentation) buffer.reset();
  presentedSource.fill(null);
  for (const a of actors)
    if (a) {
      setRetargetSmoothing(
        a.rig,
        (1.5 * 50) / Math.max(1, smooth),
        (1.5 * 50) / Math.max(1, smooth),
      );
      setRetargetBoneSmoothing(
        a.rig,
        [
          "leftShoulder",
          "rightShoulder",
          "leftArm",
          "rightArm",
          "leftForeArm",
          "rightForeArm",
          "leftHand",
          "rightHand",
        ],
        (4 * 50) / Math.max(1, smooth),
        (4 * 50) / Math.max(1, smooth),
      );
      resetRetargetFilters(a.rig);
    }
}
$("audio").checked = sound.enabled;
$("volume").value = sound.volume * 100;
$("audio").onchange = () => sound.setEnabled($("audio").checked);
$("volume").oninput = () => sound.setVolume(Number($("volume").value) / 100);
$("smooth").value = smooth;
setSmooth();
$("smooth").oninput = setSmooth;
async function createActor(i, id) {
  const previous = actors[i];
  const { root } = await loadAvatar(id);
  root.scale.multiplyScalar(1.72 / CANONICAL_SKELETON_HEIGHT);
  const group = new THREE.Group();
  group.add(root);
  scene.add(group);
  root.traverse((n) => {
    if (n.isMesh) {
      n.castShadow = n.receiveShadow = true;
    }
  });
  const a = {
    avatarId: id,
    root,
    group,
    rig: buildAvatarRig(root),
    motion: createAvatarMotion(),
    feet: new FootPlanting(),
    groundInitialized: false,
    gloves: [],
    clip: { active: { value: 0 }, head: { value: new THREE.Vector3() } },
  };
  root.traverse((n) => {
    if (!n.isMesh) return;
    for (const m of Array.isArray(n.material) ? n.material : [n.material]) {
      m.userData.cornerOriginalSide = m.side;
      m.onBeforeCompile = (shader) => {
        shader.uniforms.cornerClip = a.clip.active;
        shader.uniforms.cornerHead = a.clip.head;
        shader.uniforms.cornerBones = {
          value: new THREE.Vector2(
            n.skeleton?.bones.indexOf(a.rig.bones.get("head")?.bone) ?? -2,
            n.skeleton?.bones.indexOf(a.rig.bones.get("neck")?.bone) ?? -2,
          ),
        };
        shader.vertexShader =
          "varying vec3 cornerWorld;varying float cornerHeadWeight;uniform vec2 cornerBones;\nfloat cornerBoneWeight(float id,float weight){return (abs(id-cornerBones.x)<0.5||abs(id-cornerBones.y)<0.5)?weight:0.0;}\n" +
          shader.vertexShader;
        shader.vertexShader = shader.vertexShader.replace(
          "#include <worldpos_vertex>",
          "#include <worldpos_vertex>\ncornerWorld=(modelMatrix*vec4(transformed,1.0)).xyz;\ncornerHeadWeight=-1.0;\n#ifdef USE_SKINNING\ncornerHeadWeight=cornerBoneWeight(skinIndex.x,skinWeight.x)+cornerBoneWeight(skinIndex.y,skinWeight.y)+cornerBoneWeight(skinIndex.z,skinWeight.z)+cornerBoneWeight(skinIndex.w,skinWeight.w);\n#endif\n",
        );
        shader.fragmentShader =
          "varying vec3 cornerWorld;varying float cornerHeadWeight;uniform float cornerClip;uniform vec3 cornerHead;\n" +
          shader.fragmentShader;
        shader.fragmentShader = shader.fragmentShader.replace(
          "#include <clipping_planes_fragment>",
          "#include <clipping_planes_fragment>\nif(cornerClip>0.5 && (cornerHeadWeight>0.08 || (cornerHeadWeight<0.0 && length(cornerWorld.xz-cornerHead.xz)<0.36 && cornerWorld.y>cornerHead.y-0.12))) discard;",
        );
      };
      m.customProgramCacheKey = () => "corner-head-clip-v2";
      m.needsUpdate = true;
    }
  });
  updateAvatarPose({
    model: root,
    rig: a.rig,
    pose: neutralPose(),
    nameToIndex: JOINTS,
    motion: a.motion,
    aux: demoAux(neutralPose()),
    allowFeet: true,
    plantGround: true,
    groundY: 0,
  });
  root.updateWorldMatrix(true, true);
  const headY = a.rig.bones
    .get("head")
    .bone.getWorldPosition(new THREE.Vector3()).y;
  const feetY = Math.min(
    ...["leftFoot", "rightFoot"].map(
      (n) => a.rig.bones.get(n).bone.getWorldPosition(new THREE.Vector3()).y,
    ),
  );
  root.scale.multiplyScalar(1.72 / Math.max(0.5, headY - feetY));
  a.rig = buildAvatarRig(root);
  a.motion = createAvatarMotion();
  actors[i] = a;
  if (previous) {
    scene.remove(previous.group, ...previous.gloves);
    previous.root.traverse((n) => {
      if (n.isMesh) {
        n.geometry?.dispose();
        for (const m of Array.isArray(n.material) ? n.material : [n.material])
          m?.dispose();
      }
    });
  }
  fighters[i].avatarId = id;
  setSmooth();
}
fillAvatarSelect($("avatarSelect"), fighters[0].avatarId);
for (const opt of $("avatarSelect").options)
  opt.textContent =
    {
      "boxer-prism31": "Prism • técnico",
      boxeador: "Titan • peso pesado",
      "fighter-web": "Fighter • clássico",
    }[opt.value] || opt.textContent;
$("avatarSelect").onchange = async () => {
  try {
    $("avatarSelect").disabled = true;
    await createActor(self, $("avatarSelect").value);
    localStorage.setItem("labAvatarId", $("avatarSelect").value);
  } catch (e) {
    notify("Falha ao carregar personagem");
    $("loadStatus").textContent = e.message;
  } finally {
    $("avatarSelect").disabled = false;
  }
};
try {
  await Promise.all([
    createActor(0, fighters[0].avatarId),
    createActor(1, fighters[1].avatarId),
  ]);
  loaded = true;
  $("train").disabled = $("online").disabled = false;
  $("loadStatus").textContent = "3 personagens • primeira e terceira pessoa";
} catch (e) {
  $("loadStatus").textContent = "Erro ao carregar lutadores: " + e.message;
}
function reset() {
  for (const buffer of presentation) buffer.reset();
  presentedSource.fill(null);
  finalResult = null;
  effect = null;
  lastEffect = 0;
  baseline = null;
  clock = 90;
  round = 1;
  for (let i = 0; i < 2; i++) {
    Object.assign(fighters[i], {
      x: 0,
      z: i ? 0.68 : -0.68,
      hp: 100,
      stun: 0,
      score: 0,
      tracking: false,
      pose: neutralPose(),
      aux: demoAux(neutralPose()),
      lateral: 0,
      lateralTarget: 0,
      lateralApplied: 0,
      lateralOrigin: 0,
      radial: 0,
      radialTarget: 0,
      radialApplied: 0,
      radialOrigin: 0,
      footContacts: null,
      footVisible: null,
      attacks: [],
      reaction: null,
    });
    fighters[i].detector = new PunchDetector();
    fighters[i].footwork.reset();
    if (actors[i]) { actors[i].feet.reset(); actors[i].groundInitialized=false; }
  }
}
function enter(isOnline = false) {
  if (!loaded) return;
  sound.start().catch((e) => ($("trackingStatus").textContent = e.message));
  active = true;
  online = isOnline;
  $("lobby").hidden = true;
  $("hud").hidden = false;
  $("guide").hidden = false;
  $("exit").hidden = false;
  document.body.classList.add("fighting");
  if (window.cornerDebug) window.cornerDebug.snapCamera = true;
  $("opponentName").textContent = isOnline ? "OPONENTE" : "SPARRING";
  $("exit").textContent = isOnline ? "Sair da sala" : "Sair do treino";
  $("fightState").textContent = isOnline ? "DUELO ONLINE" : "TREINAMENTO";
  if (!isOnline) {
    self = 0;
    reset();
    notify("Ative sua webcam", 1.8);
  }
  if (!cameraOn) $("cameraButton").click();
}
function exit() {
  sound.stop();
  if (cameraOn) $("cameraButton").click();
  active = false;
  online = false;
  self = 0;
  net.close();
  $("lobby").hidden = false;
  $("hud").hidden = true;
  $("guide").hidden = true;
  $("exit").hidden = true;
  document.body.classList.remove("fighting");
  $("networkStatus").textContent = "ARENA DE TREINO";
  $("result").close();
  reset();
}
$("train").onclick = () => enter();
$("exit").onclick = exit;
$("again").onclick = exit;
for (const b of document.querySelectorAll("[data-close]"))
  b.onclick = () => $(b.dataset.close).close();
$("settingsButton").onclick = () => $("settings").showModal();
$("online").onclick = () => $("match").showModal();
function setView() {
  first = $("view").value === "first";
  document.body.classList.toggle("first-person", first);
  camera.fov = first ? 90 : 48;
  camera.near = first ? 0.018 : 0.05;
  camera.updateProjectionMatrix();
  $("viewButton").innerHTML =
    "Câmera: " + (first ? "primeira" : "terceira") + " pessoa";
}
$("view").onchange = setView;
$("viewButton").onclick = () => {
  $("view").value = first ? "third" : "first";
  setView();
};
$("venue").onchange = () => {
  scene.background.set($("venue").value === "dawn" ? "#242333" : "#0a101c");
  scene.fog.color.copy(scene.background);
  renderer.toneMappingExposure = $("venue").value === "dawn" ? 1.45 : 1.15;
};
let bridgeReady = false;
window.addEventListener("message", (e) => {
  if (e.origin !== location.origin || e.source !== $("tracker").contentWindow)
    return;
  if (e.data.type === "corner-ready") {
    bridgeReady = true;
    return;
  }
  if (
    e.data.type !== "corner-pose" ||
    !cameraOn ||
    !validPose(e.data.pose) ||
    e.data.time <= poseFrameTime
  )
    return;
  poseFrameTime = e.data.time;
  lastPoseTime = performance.now();
  fighters[self].tracking = true;
  const f = fighters[self];
  const hasCameraPosition = validPose(e.data.cameraPose);
  const raw = hasCameraPosition ? e.data.cameraPose : e.data.pose;
  if (baseline === null) { f.footwork.reset(); baseline = true; }
  const movement = f.footwork.update(raw, lastPoseTime, hasCameraPosition ? e.data.cameraInfo : null);
  const p = movement.pose;
  const hydrated = reviveAux(e.data.aux);
  constrainFacing(p, hydrated);
  fighters[self].pose = p;
  fighters[self].aux = hydrated;
  fighters[self].headForward =
    hydrated?.kind === "smpl"
      ? headForwardFromSmplAux(hydrated)
      : reviveVector(e.data.headForward);
  fighters[self].footDirections =
    hydrated?.kind === "smpl" ? footDirectionsFromSmplAux(hydrated) : null;
  fighters[self].detected = fighters[self].detector.update(p, lastPoseTime);
  f.lateral = f.radial = 0;
  f.lateralTarget = clamp((f.lateralOrigin || 0) + movement.lateral, -50, 50);
  f.radialTarget = $("depth").checked ? clamp((f.radialOrigin || 0) + movement.radial, -50, 50) : f.radialApplied || 0;
  f.footContacts = movement.contacts;
  f.footVisible = movement.footVisible;
  $("trackingStatus").textContent =
    e.data.backend === "nlf"
      ? "NLF-S • rastreamento ativo"
      : "MediaPipe • rastreamento ativo";
  if (!movement.framed) $("trackingStatus").textContent = "Mostre o tronco • deslocamento suspenso";
  else if (movement.footVisible.some(v=>!v)) $("trackingStatus").textContent = "NLF-S • rastreamento ativo • passos estimados";
});
$("cameraButton").onclick = async () => {
  try {
    const bridge = $("tracker").contentWindow.cornerTracking;
    if (!bridge)
      throw Error("Rastreamento ainda está carregando. Tente novamente.");
    if (cameraOn) {
      bridge.stop();
      cameraOn = false;
      fighters[self].tracking = false;
      $("preview").hidden = true;
      $("cameraButton").textContent = "Ativar webcam";
      $("trackingStatus").textContent = "Webcam desligada • luta pausada";
      return;
    }
    cameraOn = true;
    fighters[self].tracking = false;
    fighters[self].lateralOrigin = fighters[self].lateralTarget || 0;
    fighters[self].radialOrigin = fighters[self].radialTarget || 0;
    actors[self]?.feet.reset();
    if (actors[self]) actors[self].groundInitialized = false;
    baseline = null;
    poseFrameTime = -1;
    lastPoseTime = 0;
    document.getElementById("trackingStatus").textContent =
      "Preparando NLF-S • aguarde…";
    await bridge.start();
    $("cameraButton").textContent = "Desativar webcam";
    $("preview").srcObject = bridge.video.srcObject;
    $("preview").hidden = false;
    $("trackingStatus").textContent =
      "Aguardando NLF-S • fique inteiro no enquadramento";
  } catch (e) {
    cameraOn = false;
    $("trackingStatus").textContent = "Webcam: " + e.message;
  }
};
$("calibrate").onclick = () => {
  fighters[self].lateralOrigin = fighters[self].lateralTarget || 0;
  fighters[self].radialOrigin = fighters[self].radialTarget || 0;
  actors[self]?.feet.reset();
  if (actors[self]) actors[self].groundInitialized = false;
  baseline = null;
  notify("Centro recalibrado");
};
const net = new DuelConnection(
  (m) => {
    if (m.type === "joined") {
      self = m.slot;
      ready = false;
      reset();
      enter(true);
      syncAvatar(self, $("avatarSelect").value);
    }
    if (m.type === "ready") {
      ready = true;
      reset();
      $("match").close();
      notify("Lutadores prontos", 2);
    }
    if (m.type === "disconnected") {
      ready = false;
      notify("Luta pausada", 3);
    }
    if (m.type === "input" && self === 0 && validPose(m.pose)) {
      const f = fighters[1];
      f.tracking = !!m.tracking;
      syncAvatar(1, m.avatarId);
      f.pose = m.pose;
      f.aux = reviveAux(m.aux);
      f.lateral = clamp(Number(m.lateral) || 0, -1, 1);
      f.lateralTarget = clamp(Number(m.lateralTarget) || 0, -50, 50);
      f.radialTarget = clamp(Number(m.radialTarget) || 0, -50, 50);
      f.footContacts = Array.isArray(m.footContacts) ? m.footContacts.slice(0,2).map(Boolean) : null;
      f.footVisible = Array.isArray(m.footVisible) ? m.footVisible.slice(0,2).map(Boolean) : null;
      f.radial = clamp(Number(m.radial) || 0, -1, 1);
      f.lastInput = performance.now();
      if (Array.isArray(m.attacks))
        for (const a of m.attacks.slice(0, 2))
          if (
            [0, 1].includes(a.hand) &&
            performance.now() - (f.lastRemoteAttack?.[a.hand] || 0) > 300
          ) {
            f.lastRemoteAttack ??= [0, 0];
            f.lastRemoteAttack[a.hand] = performance.now();
            f.attacks.push({
              hand: a.hand,
              start: performance.now(),
              hit: false,
            });
          }
    }
    if (m.type === "state" && self === 1 && Array.isArray(m.fighters)) {
      clock = m.clock;
      round = m.round;
      for (let i = 0; i < 2; i++) {
        const f = m.fighters[i];
        if (i !== self) syncAvatar(i, f.avatarId);
        if (
          !validPose(f.pose) ||
          ![f.x, f.z, f.yaw, f.hp, f.stun].every(Number.isFinite)
        )
          continue;
        Object.assign(fighters[i], {
          x: clamp(f.x, -2.55, 2.55),
          z: clamp(f.z, -2.55, 2.55),
          yaw: f.yaw,
          tracking: !!f.tracking,
          hp: clamp(f.hp, 0, 100),
          stun: f.stun,
          tracking: !!f.tracking,
          score: Number(f.score) || 0,
        });
        if (i !== self) {
          fighters[i].pose = f.pose;
          fighters[i].aux = reviveAux(f.aux);
          fighters[i].footContacts = Array.isArray(f.footContacts) ? f.footContacts.slice(0,2).map(Boolean) : null;
          fighters[i].footVisible = Array.isArray(f.footVisible) ? f.footVisible.slice(0,2).map(Boolean) : null;
          fighters[i].lateralApplied = Number(f.lateralApplied) || 0;
          fighters[i].radialApplied = Number(f.radialApplied) || 0;
        } else {
          // Preserve locally predicted steps not yet acknowledged by host.
          const pending =
            (fighters[i].lateralApplied || 0) - (Number(f.lateralApplied) || 0);
          const peer = m.fighters[1 - i];
          if (peer && [peer.x, peer.z].every(Number.isFinite))
          { orbitalShift(fighters[i], peer, pending);
            radialShift(fighters[i], peer, (fighters[i].radialApplied || 0) - (Number(f.radialApplied) || 0)); }
        }
      }
      if (m.effect && m.effect.seq > lastEffect) {
        lastEffect = m.effect.seq;
        impact(m.effect.pos, m.effect.blocked, m.effect);
        notify(m.effect.blocked ? "Bloqueio" : "Golpe limpo", 0.6);
      }
      if (m.result) finish(m.result, false);
    }
  },
  (s) => {
    $("roomStatus").textContent = s;
    $("networkStatus").textContent = s.toUpperCase();
  },
);
$("server").value =
  localStorage.getItem("cornerServer") ||
  "wss://corner-relay.lnyx9r.easypanel.host";
$("join").onclick = () => {
  const url = $("server").value.trim(),
    room = $("room").value.trim().toUpperCase();
  if (!/^wss?:\/\//.test(url) || !/^[A-Z0-9_-]{3,24}$/.test(room)) {
    $("roomStatus").textContent =
      "Use ws:// ou wss:// e código com 3–24 letras/números.";
    return;
  }
  localStorage.setItem("cornerServer", url);
  net.connect(url, room, $("transport").value);
};
let finalResult = null;
function finish(result, broadcast = true) {
  if (finalResult) return;
  finalResult = result;
  active = false;
  sound.bell();
  sound.stop();
  $("resultTitle").textContent =
    result.winner === null
      ? "Empate."
      : result.winner === self
        ? "Vitória."
        : "Fim da luta.";
  $("resultText").textContent =
    result.reason + " • " + fighters[self].score + " golpes limpos";
  $("result").showModal();
  if (online && self === 0 && broadcast) net.send(snapshot());
}
const switching = [false, false];
function syncAvatar(i, id) {
  if (
    !["boxer-prism31", "boxeador", "fighter-web"].includes(id) ||
    fighters[i].avatarId === id ||
    switching[i]
  )
    return;
  switching[i] = true;
  createActor(i, id)
    .catch((e) => notify("Erro no avatar do oponente"))
    .finally(() => (switching[i] = false));
}
function snapshot() {
  return {
    type: "state",
    clock,
    round,
    effect,
    result: finalResult,
    fighters: fighters.map((f) => ({
      x: f.x,
      z: f.z,
      yaw: f.yaw,
      hp: f.hp,
      stun: f.stun,
      pose: f.pose,
      aux: f.aux,
      tracking: !!f.tracking,
      score: f.score,
      avatarId: f.avatarId,
      lateralApplied: f.lateralApplied || 0,
      radialApplied: f.radialApplied || 0,
      footContacts: f.footContacts,
      footVisible: f.footVisible,
    })),
  };
}
function worldPoint(f, p) {
  return [
    f.x + p[0] * Math.cos(f.yaw) + p[2] * Math.sin(f.yaw),
    p[1],
    f.z - p[0] * Math.sin(f.yaw) + p[2] * Math.cos(f.yaw),
  ];
}
const impactCanvas = document.createElement("canvas");
impactCanvas.width = impactCanvas.height = 64;
const impactCtx = impactCanvas.getContext("2d"),
  impactGradient = impactCtx.createRadialGradient(32, 32, 0, 32, 32, 31);
impactGradient.addColorStop(0, "rgba(255,255,255,.8)");
impactGradient.addColorStop(0.25, "rgba(255,255,255,.5)");
impactGradient.addColorStop(1, "rgba(255,255,255,0)");
impactCtx.fillStyle = impactGradient;
impactCtx.fillRect(0, 0, 64, 64);
const impactTexture = new THREE.CanvasTexture(impactCanvas);
function impact(pos, blocked, hit = null) {
  sound.hit(blocked);
  if (
    hit &&
    [0, 1].includes(hit.victim) &&
    Array.isArray(hit.dir) &&
    hit.dir.length === 3 &&
    hit.dir.every(Number.isFinite)
  ) {
    fighters[hit.victim].reaction = {
      dir: hit.dir.slice(),
      head: !!hit.head,
      blocked: !!blocked,
      start: performance.now(),
    };
  }
  for (let i = 0; i < 10; i++) {
    const mesh = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: impactTexture,
        color: blocked ? "#a8c1d4" : i % 3 ? "#e5c2ac" : "#c88e7c",
        transparent: true,
        opacity: 0.6,
        depthWrite: false,
      }),
    );
    mesh.scale.setScalar(i === 0 ? 0.15 : 0.035 + Math.random() * 0.025);
    mesh.position.set(...pos);
    sparkGroup.add(mesh);
    sparks.push({
      mesh,
      v: new THREE.Vector3(
        (Math.random() - 0.5) * 0.7,
        Math.random() * 0.5,
        (Math.random() - 0.5) * 0.7,
      ),
      life: 0.2,
      size: mesh.scale.x,
    });
  }
}
let botNext = 0;
function simulate(dt, now) {
  if (!active || (online && !ready)) return;
  const f = fighters[self];
  if (!cameraOn || !f.tracking || now - lastPoseTime > 500) {
    f.lateral = f.radial = 0;
    f.attacks = [];
    f.detected = [];
    $("trackingStatus").textContent = cameraOn
      ? lastPoseTime === 0
        ? "Aguardando a primeira pose do NLF-S…"
        : "Rastreamento sem atualização • luta pausada"
      : "Ative a webcam para entrar na luta";
    return;
  }
  if (
    online &&
    (!fighters[1 - self].tracking ||
      (self === 0 && now - (fighters[1].lastInput || 0) > 1000))
  ) {
    $("fightState").textContent = "AGUARDANDO WEBCAM";
    return;
  }
  $("fightState").textContent = online ? "DUELO ONLINE" : "TREINAMENTO";
  for (const hit of f.detected || [])
    f.attacks.push({
      hand: hit.hand,
      start: now,
      hit: false,
      mocap: true,
      previous: hit.previous ? worldPoint(f, hit.previous) : null,
    });
  f.detected = [];
  if (online && self === 1) {
    applyLateralPose(f, fighters[0]);
    f.attacks = f.attacks.filter((a) => now - a.start < 400);
    return;
  }
  if (!online) {
    const bot = fighters[1];
    bot.lateral = Math.sin(now / 1800) * 0.25;
    bot.radial = 0.15;
    bot.footContacts = [true,true];
    bot.footVisible = [false,false];
    if (now > botNext) {
      bot.attacks.push({
        hand: Math.random() > 0.5 ? 1 : 0,
        start: now,
        hit: false,
      });
      botNext = now + 1300 + Math.random() * 900;
    }
    const a = bot.attacks.at(-1);
    bot.pose = demoPose(
      now / 1000,
      a?.hand ?? -1,
      a ? Math.sin(clamp((now - a.start) / 260, 0, 1) * Math.PI) : 0,
    );
    if (Math.sin(now / 1600) > 0.2) {
      bot.pose[12][1] -= 0.28;
      bot.pose[13][1] -= 0.28;
    }
    bot.aux = demoAux(bot.pose);
  } else if (now - (fighters[1].lastInput || 0) > 1000) {
    fighters[1].lateral = fighters[1].radial = 0;
    fighters[1].attacks = [];
  }
  fighters[self].tracking = true;
  clock -= dt;
  for (let i = 0; i < 2; i++) {
    const a = fighters[i],
      b = fighters[1 - i];
    applyLateralPose(a, b);
    a.stun = Math.max(0, a.stun - dt);
    // Only the analytic bot uses velocity/autoadvance. Human position is
    // entirely owned by camera translation, including deliberate retreat.
    if (!online && i !== self) orbitalStep(a, b, a.lateral * (a.stun ? 0.65 : 1), a.radial, dt, {min:.95,max:4.8});
    else a.yaw = Math.atan2(b.x-a.x, b.z-a.z);
    for (const atk of a.attacks) {
      const age = now - atk.start;
      if (atk.hit || age > 300) continue;
      const current = worldPoint(a, a.pose[12 + atk.hand]),
        previous = atk.previous || current;
      atk.previous = current;
      const head = worldPoint(b, b.pose[15]),
        torso = worldPoint(b, b.pose[7]);
      const hitHead = segmentSphere(previous, current, head, 0.24),
        hitBody = segmentCapsule(
          previous,
          current,
          worldPoint(b, b.pose[0]),
          worldPoint(b, [0, (b.pose[8][1] + b.pose[9][1]) / 2, 0]),
          0.3,
        );
      if ((atk.mocap || age > 30) && (hitHead || hitBody)) {
        atk.hit = true;
        const blocked = guarded(b.pose),
          damage = blocked ? 2 : hitHead ? 12 : 8;
        b.hp = Math.max(0, b.hp - damage);
        if (!blocked) {
          a.score++;
          b.stun = hitHead ? 0.7 : 0.25;
        }
        const direction = new THREE.Vector3(...current).sub(
          new THREE.Vector3(...previous),
        );
        if (direction.lengthSq() < 0.0001)
          direction.set(b.x - a.x, 0, b.z - a.z);
        direction.normalize();
        const center = hitHead ? head : torso;
        const surface = new THREE.Vector3(...previous).sub(
          new THREE.Vector3(...center),
        );
        if (surface.lengthSq() < 0.0001) surface.copy(direction).negate();
        surface
          .normalize()
          .multiplyScalar(hitHead ? 0.24 : 0.3)
          .add(new THREE.Vector3(...center));
        effect = {
          seq: (effect?.seq || 0) + 1,
          pos: surface.toArray(),
          blocked,
          victim: 1 - i,
          head: hitHead,
          dir: direction.toArray(),
        };
        impact(effect.pos, blocked, effect);
        notify(
          blocked ? "Bloqueio" : hitHead ? "Golpe limpo" : "Golpe no corpo",
          0.6,
        );
      }
    }
    a.attacks = a.attacks.filter((x) => now - x.start < 380);
  }
  if (fighters.some((x) => x.hp <= 0))
    finish({ winner: fighters[0].hp > 0 ? 0 : 1, reason: "Nocaute" });
  if (clock <= 0) {
    if (round < 3) {
      round++;
      clock = 90;
      sound.bell();
      notify("Round " + round, 2);
    } else
      finish({
        winner:
          fighters[0].hp === fighters[1].hp
            ? null
            : fighters[0].hp > fighters[1].hp
              ? 0
              : 1,
        reason: "Decisão por pontos",
      });
  }
}
function applyLateralPose(f, peer) {
  const target = f.lateralTarget || 0,
    previous = f.lateralApplied || 0;
  const delta = clamp(target - previous, -0.25, 0.25);
  orbitalShift(f, peer, delta);
  f.lateralApplied = previous + delta;
  const radialPrevious = f.radialApplied || 0;
  const radialDelta = clamp((f.radialTarget || 0)-radialPrevious,-.25,.25);
  radialShift(f,peer,radialDelta);
  f.radialApplied = radialPrevious + radialDelta;
}
function applyImpactReaction(actor, reaction, now) {
  if (!reaction) return;
  const age = Math.max(0, (now - reaction.start) / 1000);
  if (age > 0.5) return;
  const envelope = (1 - Math.exp(-age / 0.018)) * Math.exp(-age / 0.13);
  const direction = new THREE.Vector3(...reaction.dir).normalize();
  let axis = new THREE.Vector3(0, 1, 0).cross(direction);
  if (axis.lengthSq() < 0.001) axis.set(1, 0, 0);
  axis.normalize();
  const strength = reaction.blocked ? 0.18 : reaction.head ? 1 : 0.4;
  for (const [name, angle] of [
    ["spine2", 0.045],
    ["neck", 0.17],
    ["head", 0.23],
  ]) {
    const bone = actor.rig.bones.get(name)?.bone;
    if (!bone?.parent) continue;
    const localAxis = axis
      .clone()
      .applyQuaternion(
        bone.parent.getWorldQuaternion(new THREE.Quaternion()).invert(),
      );
    bone.quaternion.premultiply(
      new THREE.Quaternion().setFromAxisAngle(
        localAxis,
        angle * strength * envelope,
      ),
    );
    bone.updateWorldMatrix(false, true);
  }
}
function renderActor(i, now) {
  const a = actors[i],
    f = fighters[i];
  if (!a) return;
  // Feed once per inference/network sample, then sample a continuous timeline.
  // The analytic sparring animation already updates every simulation tick.
  let display = { pose: f.pose, aux: f.aux };
  if (active && online && i !== self) {
    if (presentedSource[i] !== f.pose) {
      presentation[i].push(f.pose, f.aux, now);
      presentedSource[i] = f.pose;
    }
    const sample = presentation[i].sample(now, smooth);
    if (sample && smooth > 0)
      display = { pose: sample.pose, aux: reviveAux(sample.aux) };
  }
  // Hands and shoulders use the newest inference frame; buffering this fast
  // motion added a full inference interval before the quaternion filter.
  if (display.pose !== f.pose) {
    for (let j = 8; j <= 13; j++) display.pose[j] = f.pose[j].slice();
    for (const [key, value] of Object.entries(f.aux || {})) {
      if (
        /^(left|right)_(collar|shoulder|elbow|wrist|hand|pinky|index|thumb|middle)/.test(
          key,
        )
      )
        display.aux[key] = value?.clone?.() || value;
    }
  }
  updateAvatarPose({
    model: a.root,
    rig: a.rig,
    pose: display.pose,
    nameToIndex: JOINTS,
    motion: a.motion,
    aux: display.aux,
    headForward:
      display.aux?.kind === "smpl"
        ? headForwardFromSmplAux(display.aux)
        : f.headForward,
    footDirections:
      display.aux?.kind === "smpl"
        ? footDirectionsFromSmplAux(display.aux)
        : f.footDirections,
    allowFeet: true,
    footMode: "yawFromDir",
    plantGround: !f.footContacts || !a.groundInitialized,
    groundY: 0,
    timestampMs: smooth === 0 ? null : now,
    useWitness: true,
  });
  if (f.footContacts && !a.groundInitialized) {
    a.motion.basePosition.copy(a.root.position);
    a.motion.referencePelvis = new THREE.Vector3(...display.pose[0]);
    a.groundInitialized = true;
  }
  applyImpactReaction(a, f.reaction, now);
  a.group.position.set(f.x, 0.026, f.z);
  a.group.rotation.y = f.yaw;
  a.group.rotation.z = f.stun > 0 ? Math.sin(now * 0.026) * 0.025 : 0;
  a.feet.apply(a,f,now);
  a.clip.active.value = active && first && i === self ? 1 : 0;
  a.clip.head.value.copy(
    a.rig.bones.get("head").bone.getWorldPosition(new THREE.Vector3()),
  );
  const hide = false;
  a.root.traverse((n) => {
    if (!n.isMesh) return;
    const localFirst = active && first && i === self;
    n.castShadow = n.receiveShadow = !localFirst;
    n.visible = !hide;
    for (const m of Array.isArray(n.material) ? n.material : [n.material]) {
      m.side = localFirst
        ? THREE.DoubleSide
        : (m.userData.cornerOriginalSide ?? THREE.FrontSide);
      m.transparent = false;
      m.opacity = 1;
      m.depthWrite = true;
    }
  });
}
function frame(now) {
  const dt = clamp((now - last) / 1000, 0, 0.05);
  last = now;
  document.body.classList.toggle(
    "pose-active",
    active && cameraOn && fighters[self].tracking && now - lastPoseTime < 500,
  );
  sound.update(dt);
  acc += dt;
  while (acc >= 1 / 60) {
    simulate(1 / 60, now);
    acc -= 1 / 60;
  }
  if (active && online && ready && now - sendTime > 33) {
    if (self === 0) net.send(snapshot());
    else
      net.send({
        type: "input",
        tracking: cameraOn && now - lastPoseTime < 500,
        avatarId: fighters[self].avatarId,
        pose: fighters[self].pose,
        aux: fighters[self].aux,
        lateral: fighters[self].lateral,
        lateralTarget: fighters[self].lateralTarget || 0,
        radialTarget: fighters[self].radialTarget || 0,
        footContacts: fighters[self].footContacts,
        footVisible: fighters[self].footVisible,
        radial: fighters[self].radial,
        attacks: fighters[self].attacks
          .filter((a) => !a.sent)
          .map((a) => {
            a.sent = true;
            return { hand: a.hand };
          }),
      });
    sendTime = now;
  }
  for (let i = 0; i < 2; i++) renderActor(i, now);
  for (const s of sparks) {
    s.life -= dt;
    s.mesh.position.addScaledVector(s.v, dt);
    s.mesh.scale.setScalar(s.size * (1 + (1 - s.life / 0.2) * 1.1));
    s.mesh.material.opacity = Math.max(0, s.life / 0.2) * 0.6;
  }
  for (const s of sparks.filter((x) => x.life <= 0)) {
    sparkGroup.remove(s.mesh);
    s.mesh.geometry?.dispose();
    s.mesh.material.dispose();
  }
  sparks = sparks.filter((x) => x.life > 0);
  if (active) {
    const a = fighters[self],
      b = fighters[1 - self],
      forward = new THREE.Vector3(b.x - a.x, 0, b.z - a.z).normalize();
    if (first) {
      const eye = actors[self]?.rig.bones
        .get("head")
        ?.bone.getWorldPosition(new THREE.Vector3());
      targetCamera
        .copy(eye || new THREE.Vector3(a.x, 1.68, a.z))
        .addScaledVector(forward, 0.08);
      keepEyeOutsideUpperBody(actors[self], targetCamera, forward);
      const opponentEye = actors[1 - self]?.rig.bones
        .get("head")
        ?.bone.getWorldPosition(new THREE.Vector3());
      targetLook.copy(opponentEye || new THREE.Vector3(b.x, 1.72, b.z));
    } else {
      targetCamera.set(a.x, 5.2, a.z).addScaledVector(forward, -3.8);
      targetLook.set((a.x + b.x) / 2, 0.9, (a.z + b.z) / 2);
    }
    camera.position.copy(targetCamera);
    camera.lookAt(targetLook);
  } else if (!$("result").open) {
    camera.position.lerp(new THREE.Vector3(7.6, 4.1, 7.4), 0.025);
    camera.lookAt(0, 0.8, 0);
  }
  eyeFill.visible = active && first;
  eyeFill.position.copy(camera.position).add(new THREE.Vector3(0, 0.18, 0));
  if (now > messageUntil) $("combatMessage").textContent = "";
  $("timer").textContent =
    String(Math.floor(Math.max(0, clock) / 60)).padStart(2, "0") +
    ":" +
    String(Math.floor(Math.max(0, clock) % 60)).padStart(2, "0");
  $("roundLabel").textContent = "ROUND 0" + round + " / 03";
  for (let i = 0; i < 2; i++) {
    const index = i === 0 ? self : 1 - self;
    $("hp" + i).style.width = fighters[index].hp + "%";
    $("stun" + i).textContent =
      fighters[index].stun > 0
        ? "ATORDOADO • PROTEJA A GUARDA"
        : guarded(fighters[index].pose)
          ? "GUARDA ALTA"
          : "EM COMBATE";
  }
  renderer.render(scene, camera);
  if (window.cornerDebug && !window.cornerDebug.paused)
    window.cornerDebug.snapCamera = false;
  if (!window.cornerDebug?.paused) requestAnimationFrame(frame);
}
function resize() {
  renderer.setSize(innerWidth, innerHeight);
  camera.aspect = innerWidth / innerHeight;
  camera.updateProjectionMatrix();
  if (window.cornerDebug?.paused) {
    requestAnimationFrame((t) => window.cornerDebug.frame(t));
  }
}
window.addEventListener("resize", resize);
resize();
requestAnimationFrame(frame);
window.cornerDebug = {
  reviewPose: (pose) => {
    cameraOn = true;
    lastPoseTime = performance.now();
    fighters[self].pose = pose;
    fighters[self].aux = demoAux(pose);
    fighters[self].tracking = true;
  },
  fighters,
  actors,
  audio: sound,
  reviewImpact: (victim, dir, head = true, blocked = false) => {
    impact(
      worldPoint(fighters[victim], fighters[victim].pose[head ? 15 : 7]),
      blocked,
      { victim, dir, head },
    );
  },
  frame,
  paused: false,
  snapCamera: false,
  enter,
  exit,
  notify,
  net,
  view: setView,
  state: () => ({
    active,
    online,
    self,
    ready,
    clock,
    round,
    smooth,
    cameraOn,
    loaded,
    renderCalls: renderer.info.render.calls,
  }),
};
$("train").addEventListener("click", () => {
  finalResult = null;
});
$("join").addEventListener("click", () => {
  finalResult = null;
});
