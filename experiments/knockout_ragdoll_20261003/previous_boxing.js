import { t, number, language, setLanguage } from "/static/boxing_i18n.js";
import { prepareHands, alignWrists } from "/static/boxing_hands.js";
import { BoxingAudio } from "/static/boxing_audio.js";
import { VoiceCaption } from "/static/boxing_voice_caption.js";
import { characterScreenRegions, prepareCaptionBounds } from "/static/boxing_caption_bounds.js";
import { BoxingDebugRecorder } from "/static/boxing_debug_recording.js";
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
  resetHeadCalibration,
  footDirectionsFromSmplAux,
  headForwardFromSmplAux,
} from "/static/mikapo_mixamo_solver.js";
import {
  clamp,
  JOINTS,
  validPose,
  neutralPose,
  PunchDetector,
  guarded,
  orbitalStep,
  orbitalShift,
  radialShift,
  WebcamFootwork,
  PoseRenderBuffer,
  COMBAT,
  chinPoint,
  resolvePunch,
  resolvePunchBox,
  punchDamage,
  punchPower, punchTier, PUNCH, safeForce, FightJournal, capsulePenetration,
  addImpactPush, stepImpactPush,
  sparringPose,
} from "/static/boxing_core.mjs";
import { DuelConnection } from "/static/boxing_net.js";
import { validateLibrary, mixFrames, playStrike } from "/static/boxing_mocap.mjs";
let sparringLibrary = null;
fetch('/static/sparring_mocap.json').then(r => {
  if (!r.ok) throw new Error('Sparring motion HTTP ' + r.status);
  return r.json();
}).then(data => { sparringLibrary = validateLibrary(data); })
  .catch(error => console.warn('Sparring motion unavailable; using procedural poses.', error));
let lobbyLoop = null;
fetch('/static/lobby_shadowbox.json').then(r => r.ok ? r.json() : null)
  .then(data => { if (data?.frames?.length) lobbyLoop = data; }).catch(console.warn);
function poseFrame(pose, aux = demoAux(pose)) {
  return { pose, aux: Object.fromEntries(Object.entries(aux)
    .filter(([, v]) => v?.isVector3).map(([k, v]) => [k, v.toArray()])) };
}
import { solveTwoBone, prepareFeet, soleBottom, groundSoles } from "/static/boxing_feet.js";
import { NativeGuardContact } from "/static/avatar_self_contact.js";
import {
  CameraShake,
  ImpactFx,
  GloveTrail,
  DizzyStars,
  CrowdFlashes,
  toonifyAvatar,
} from "/static/boxing_fx.js";
import { buildArena, VENUES } from "/static/boxing_arena.js";
import { prepareKnockout, KnockoutRelaxation } from "/static/boxing_knockout.js";
const $ = (id) => document.getElementById(id),
  sound = new BoxingAudio();
setLanguage(language);
$("language").value=language;
let trackingKey='noCamera',roomStatusKey='';
let peakRecord=safeForce(Number(localStorage.getItem('cornerPeakN')) || 0);
let previousPeak=peakRecord, fightElapsed=0;
const refreshPeak=()=>{
 $("peakRecord").hidden=peakRecord<=0;
 $("peakValue").textContent=number(peakRecord)+' N';
};
const refreshCameraUI=()=>{
 // Training starts the webcam itself; the fight waits for the first pose.
 $("train").disabled=!loaded;
 $("online").disabled=!loaded;
 $("lobbyCamera").classList.toggle('connected',cameraOn);
 $("cameraChipText").textContent=t(cameraOn ? (fighters[self].tracking?'cameraOn':trackingKey) : trackingKey);
 $("trackingStatus").textContent=t(trackingKey);
};
function trackStatus(key){trackingKey=key;refreshCameraUI();}
function rememberPeak(forceN){
 const n=safeForce(forceN);
 if(n>peakRecord){peakRecord=n;localStorage.setItem('cornerPeakN',String(n));refreshPeak();}
}
$("language").onchange=()=>{
 setLanguage($("language").value);refreshPeak();refreshCameraUI();setView();
 if(finalResult)renderResult();
 if(roomStatusKey)$('roomStatus').textContent=t(roomStatusKey);
};
$("lobbyCamera").onclick=()=> $("cameraButton").click();
$("bodyKg").value=clamp(Number(localStorage.getItem('cornerBodyKg'))||80,40,180);
PUNCH.bodyKg=Number($("bodyKg").value);
$("bodyKg").onchange=()=>{
 PUNCH.bodyKg=clamp(Number($("bodyKg").value)||80,40,180);
 $("bodyKg").value=PUNCH.bodyKg;localStorage.setItem('cornerBodyKg',String(PUNCH.bodyKg));
 fighters[self].detector=new PunchDetector(PUNCH.bodyKg);
};
$("voiceVolume").value=sound.voiceVolume*100;
$("voiceVolume").oninput=()=>sound.setVoiceVolume(Number($("voiceVolume").value)/100);
$("reducedImpact").checked=sound.reducedImpact;
$("reducedImpact").onchange=()=>sound.setReducedImpact($("reducedImpact").checked);
refreshPeak();
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
  // Synthetic sparring eyes follow the skull instead of staying at fixed
  // world coordinates while the head moves. Real webcam aux is untouched.
  const skullUp = aux.head.clone().sub(aux.neck).normalize();
  const skullAcross = new THREE.Vector3(1, 0, 0).addScaledVector(skullUp, -skullUp.x).normalize();
  const skullForward = new THREE.Vector3().crossVectors(skullAcross, skullUp).normalize();
  const eyeCenter = aux.head.clone().addScaledVector(skullUp, 0.03).addScaledVector(skullForward, 0.08);
  aux.left_eye = eyeCenter.clone().addScaledVector(skullAcross, 0.035);
  aux.right_eye = eyeCenter.clone().addScaledVector(skullAcross, -0.035);
  aux.jaw = aux.head.clone().addScaledVector(skullUp, -0.06).addScaledVector(skullForward, 0.06);
  // Without knuckles the solver leaves the fist at rest roll (palms out on Prism).
  // Thumb side follows world-up projected off the forearm: palms face inward.
  for (const [side, w, e] of [["left", 12, 10], ["right", 13, 11]]) {
    const wrist = new THREE.Vector3(...p[w]),
      forward = wrist.clone().sub(new THREE.Vector3(...p[e])).normalize();
    const up = new THREE.Vector3(0, 1, 0).addScaledVector(forward, -forward.y).normalize();
    const knuckles = wrist.clone().addScaledVector(forward, 0.08);
    aux[side + "_index"] = knuckles.clone().addScaledVector(up, 0.025);
    aux[side + "_pinky"] = knuckles.clone().addScaledVector(up, -0.025);
    aux[side + "_middle"] = knuckles.clone();
    aux[side + "_hand"] = knuckles.clone();
    aux[side + "_thumb"] = wrist.clone().addScaledVector(forward, 0.04).addScaledVector(up, 0.045);
  }
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
const eyeFill = new THREE.PointLight("#ffede0", 0.75, 2.4, 2);
eyeFill.visible = false;
scene.add(eyeFill);
const arena = buildArena(scene);
const shake = new CameraShake();
const punchZoom = { amount: 0, start: 0 };
const fx = new ImpactFx(scene);
const flashes = new CrowdFlashes(scene, arena.seats);
const trails = [0, 1].map(() => [new GloveTrail(scene), new GloveTrail(scene)]);
const stars = [0, 1].map(() => new DizzyStars(scene));
const GRAPHICS = { high: 1.7, balanced: 1.25, low: .85 };
function setGraphics(level) {
  if (!Object.hasOwn(GRAPHICS, level)) level = 'high';
  $('quality').value = level;
  renderer.setPixelRatio(Math.min(devicePixelRatio, GRAPHICS[level]));
  const shadows = level !== 'low';
  if (renderer.shadowMap.enabled !== shadows) {
    renderer.shadowMap.enabled = shadows;
    scene.traverse(node => {
      if (!node.material) return;
      for (const m of Array.isArray(node.material) ? node.material : [node.material]) m.needsUpdate = true;
    });
  }
  arena.setQuality(level); fx.setQuality(level);
  localStorage.setItem('cornerGraphics', level);
}
setGraphics(localStorage.getItem('cornerGraphics') || 'high');
$('quality').onchange = () => setGraphics($('quality').value);
const CORNER_COLORS = ["#009dff", "#ff183b"];
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
  loaded = false,
  // Presentation clock: hit-stop and slow motion bend it; simulation never does.
  vclock = 0,
  hitstopUntil = 0,
  slowmoUntil = 0,
  ko = null,
  lastTick = -1,
  heartbeatAt = 0,
  liveAnnounced = false;
const combatState = () => ({
  stun: 0,
  dizzy: 0,
  recoil: 0,
  weakened: 0,
  dizzyImmune: 0,
  headHits: [],
  combo: 0,
  comboUntil: 0,
  blockHold: null,
  reaction: null,
  stats: { clean: 0, chin: 0, maxCombo: 0, fastest: 0, blocked: 0 },
  journal: new FightJournal(), lowHpSaid: false,
});
const fighters = [0, 1].map((i) => ({
  x: 0,
  z: i === 0 ? -0.68 : 0.68,
  yaw: i === 0 ? 0 : Math.PI,
  hp: 100,
  ...combatState(),
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
const actors = [null, null];
const presentation = [new PoseRenderBuffer(), new PoseRenderBuffer()];
const presentedSource = [null, null];
const handPrevious = [[null, null], [null, null]];
// Hit volumes measured on the rendered avatars each frame: what you see is what hits.
const hitboxes = [null, null];
const journalRequest=[0,0];
let terminalSynced=false;
const GLOVE_RADIUS = 0.08;
function meshHitBox(i) {
  const a = actors[i];
  if (!a) return null;
  const P = (n) => a.rig.bones.get(n)?.bone.getWorldPosition(new THREE.Vector3());
  const headBone = a.rig.bones.get("head")?.bone;
  const hips = P("hips"), chest = P("spine2") || P("spine1") || P("spine"), leftArm = P("leftArm"), rightArm = P("rightArm");
  if (!headBone || !hips || !chest || !leftArm || !rightArm) return null;
  const surface = a.headSurface;
  const headCenter = surface ? headBone.localToWorld(surface.center.clone()) : P("head").add(new THREE.Vector3(0, 0.1, 0));
  const headRadius = surface ? surface.radius * headBone.getWorldScale(new THREE.Vector3()).x * 1.1 : 0.12;
  const forward = a.group.getWorldDirection(new THREE.Vector3());
  const chin = headCenter.clone().add(new THREE.Vector3(0, -headRadius * 0.65, 0)).addScaledVector(forward, headRadius * 0.55);
  const limbs = ["left", "right"].map((side,h) => {
    const bone=a.rig.bones.get(side+"Hand")?.bone,glove=a.guardContact.hands[h]?.sphere;
    return {elbow:P(side+"ForeArm"),wrist:P(side+"Hand"),gloveCenter:glove&&bone?glove.center.clone().applyQuaternion(bone.getWorldQuaternion(new THREE.Quaternion())).add(P(side+"Hand")):P(side+"Hand"),
      gloveRadius:glove?.radius || .08};
  });
  if (limbs.some((l) => !l.elbow || !l.wrist)) return null;
  const along = (l, k) => l.wrist.clone().add(l.wrist.clone().sub(l.elbow).multiplyScalar(k)).toArray();
  return {
    head: { c: headCenter.toArray(), r: headRadius + GLOVE_RADIUS },
    chin: { c: chin.toArray(), r: 0.05 + GLOVE_RADIUS * 0.5 },
    body: { a: hips.toArray(), b: chest.toArray(), r: leftArm.distanceTo(rightArm) * 0.42 + GLOVE_RADIUS },
    arms: limbs.flatMap((l,h)=>[
      {a:l.elbow.toArray(),b:l.wrist.toArray(),r:.045+GLOVE_RADIUS,hand:h},
      {a:l.gloveCenter.toArray(),b:l.gloveCenter.toArray(),r:l.gloveRadius+GLOVE_RADIUS,hand:h}
    ]),
    gloves:limbs.map(l=>l.gloveCenter.toArray()),
  };
}
const bruises = [[], []];
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
$("musicVolume").value = sound.musicVolume * 100;
$("musicVolume").oninput = () => sound.setMusicVolume(Number($("musicVolume").value) / 100);
// The menu theme starts right away when the browser allows autoplay; otherwise
// the first click/key anywhere unlocks it (listeners stay until it plays).
sound.startMusic();
for (const type of ["pointerdown", "keydown", "touchstart"])
  addEventListener(type, () => sound.musicPlaying() || sound.startMusic(), { capture: true });
$("soundHint").onclick = () => {
  if (!sound.enabled) {
    $("audio").checked = true;
    sound.setEnabled(true);
  }
  sound.startMusic();
};
$("smooth").value = smooth;
setSmooth();
$("smooth").oninput = setSmooth;
async function createActor(i, id) {
  const previous = actors[i];
  const { root } = await loadAvatar(id);
  root.scale.multiplyScalar(1.72 / CANONICAL_SKELETON_HEIGHT);
  if (localStorage.getItem("cornerMaterial") !== "original") toonifyAvatar(root);
  const group = new THREE.Group();
  group.rotation.order = "YXZ";
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

    groundInitialized: false,
    gloves: [],
    clip: { active: { value: 0 }, head: { value: new THREE.Vector3() } },
    flash: { value: 0 },
    flashColor: { value: new THREE.Color("#ffffff") },
    flashStart: -1e9,
    flashPeak: 0,
    bruise: { value: [0, 1, 2, 3].map(() => new THREE.Vector4(0, -10, 0, 0)) },
  };
  root.traverse((n) => {
    if (!n.isMesh) return;
    for (const m of Array.isArray(n.material) ? n.material : [n.material]) {
      m.userData.cornerOriginalSide = m.side;
      m.onBeforeCompile = (shader) => {
        shader.uniforms.cornerClip = a.clip.active;
        shader.uniforms.cornerHead = a.clip.head;
        shader.uniforms.cornerFlash = a.flash;
        shader.uniforms.cornerFlashColor = a.flashColor;
        shader.uniforms.cornerBruise = a.bruise;
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
          "varying vec3 cornerWorld;varying float cornerHeadWeight;uniform float cornerClip;uniform vec3 cornerHead;uniform float cornerFlash;uniform vec3 cornerFlashColor;uniform vec4 cornerBruise[4];\n" +
          shader.fragmentShader;
        shader.fragmentShader = shader.fragmentShader.replace(
          "#include <clipping_planes_fragment>",
          "#include <clipping_planes_fragment>\nif(cornerClip>0.5 && (cornerHeadWeight>0.08 || (cornerHeadWeight<0.0 && length(cornerWorld.xz-cornerHead.xz)<0.36 && cornerWorld.y>cornerHead.y-0.12))) discard;",
        );
        // Bruises tint the skin itself (multiplied, so texture detail survives),
        // only on head/neck-weighted skin so gloves never pick them up.
        shader.fragmentShader = shader.fragmentShader.replace(
          "#include <color_fragment>",
          "#include <color_fragment>\nif(cornerHeadWeight>0.3){float cornerRed=0.0;float cornerCore=0.0;for(int i=0;i<4;i++){vec4 b=cornerBruise[i];float d=distance(cornerWorld,b.xyz);cornerRed=max(cornerRed,b.w*(1.0-smoothstep(0.015,0.06,d)));cornerCore=max(cornerCore,b.w*(1.0-smoothstep(0.004,0.026,d)));}float k=clamp((cornerHeadWeight-0.3)/0.4,0.0,1.0);diffuseColor.rgb*=mix(vec3(1.0),vec3(1.0,0.48,0.5),cornerRed*k);diffuseColor.rgb*=mix(vec3(1.0),vec3(0.62,0.26,0.42),cornerCore*k*0.8);}",
        );
        shader.fragmentShader = shader.fragmentShader.replace(
          "#include <tonemapping_fragment>",
          "gl_FragColor.rgb=mix(gl_FragColor.rgb,cornerFlashColor,cornerFlash);\n#include <tonemapping_fragment>",
        );
      };
      m.customProgramCacheKey = () => "corner-head-clip-v3";
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
  root.updateWorldMatrix(true, true);
  a.guardContact = new NativeGuardContact(a);
  a.headSurface = sampleHeadSurface(a);
  prepareHands(a);
  a.alignWrists=()=>alignWrists(a);
  prepareFeet(a);
  prepareKnockout(a);
  // The solver grounds the lowest foot/toe bone, which sits inside the shoe;
  // offset it by the shoe so the sole (not the bone) lands on the canvas.
  {
    const feet = ["leftFoot", "rightFoot"].map((n) => a.rig.bones.get(n)).filter(Boolean);
    const boneLow = Math.min(...feet.flatMap((r) => [r.bone, r.child].filter(Boolean).map((b) => b.getWorldPosition(new THREE.Vector3()).y)));
    const soleLow = Math.min(...feet.map((r) => soleBottom(a, r.bone)));
    a.groundY = Number.isFinite(boneLow - soleLow) ? boneLow - soleLow : 0;
  }
  actors[i] = a;
  bruises[i] = [];
  handPrevious[i] = [null, null];
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
  // Build bind-space caption envelopes while the avatar is loading, so the
  // first announcement never pays this cost during a punch or KO.
  prepareCaptionBounds(a);
  setSmooth();
}
// Head skin samples in head-bone space: bruises land on the real face surface
// whatever the avatar's proportions.
function sampleHeadSurface(a) {
  const head = a.rig.bones.get("head")?.bone;
  if (!head) return null;
  const points = [];
  a.root.traverse((mesh) => {
    if (!mesh.isSkinnedMesh) return;
    const id = mesh.skeleton.bones.indexOf(head);
    const { position, skinIndex, skinWeight } = mesh.geometry.attributes;
    if (id < 0 || !skinIndex) return;
    mesh.skeleton.update();
    const step = Math.max(1, Math.floor(position.count / 40000));
    for (let v = 0; v < position.count; v += step) {
      let w = 0;
      for (let c = 0; c < 4; c++)
        if (skinIndex.getComponent(v, c) === id) w += skinWeight.getComponent(v, c);
      if (w < 0.6) continue;
      const p = new THREE.Vector3().fromBufferAttribute(position, v);
      mesh.applyBoneTransform(v, p);
      points.push(head.worldToLocal(mesh.localToWorld(p)));
    }
  });
  if (points.length < 20) return null;
  const center = points.reduce((s, p) => s.add(p), new THREE.Vector3()).divideScalar(points.length);
  const radius = points.reduce((s, p) => s + p.distanceTo(center), 0) / points.length;
  return { points, center, radius };
}
// Picks the skin point facing the punch; nearby repeat hits deepen one bruise.
function addBruise(i, worldDirection, strength) {
  const a = actors[i], surface = a?.headSurface, head = a?.rig.bones.get("head")?.bone;
  if (!surface || !head) return;
  const inverse = head.getWorldQuaternion(new THREE.Quaternion()).invert();
  const dir = worldDirection.clone().normalize().applyQuaternion(inverse);
  let best = null, score = -Infinity;
  for (const p of surface.points) {
    const s = p.clone().sub(surface.center).normalize().dot(dir);
    if (s > score) (score = s), (best = p);
  }
  const local = best.clone().lerp(surface.center, 0.06);
  const near = bruises[i].find((b) => b.local.distanceTo(local) < surface.radius * 0.3);
  if (near) near.w = Math.min(1, near.w + strength * 0.6);
  else {
    bruises[i].push({ local, w: strength });
    if (bruises[i].length > 4) bruises[i].shift();
  }
}
fillAvatarSelect($("avatarSelect"), fighters[0].avatarId);
for (const opt of $("avatarSelect").options)
  opt.textContent =
    {
      "boxer-prism31": "PRISM",
      boxeador: "TITAN",
      "fighter-web": "FIGHTER",
    }[opt.value] || opt.textContent;
$("avatarSelect").onchange = async () => {
  showFighter();
  try {
    $("avatarSelect").disabled = true;
    document.body.classList.add("loading-fighter");
    await createActor(self, $("avatarSelect").value);
    localStorage.setItem("labAvatarId", $("avatarSelect").value);
  } catch (e) {
    notify(t("loadError"));
    $("loadStatus").textContent = e.message;
  } finally {
    $("avatarSelect").disabled = false;
    document.body.classList.remove("loading-fighter");
  }
};
try {
  await Promise.all([
    createActor(0, fighters[0].avatarId),
    createActor(1, fighters[1].avatarId),
  ]);
  loaded = true;
  $("loadStatus").replaceChildren();
  refreshCameraUI();
} catch (e) {
  $("loadStatus").textContent = t("loadError");
  console.error(e);
}
function reset() {
  terminalSynced=false;journalRequest.fill(0);
  for (const buffer of presentation) buffer.reset();
  presentedSource.fill(null);
  finalResult = null;
  previousPeak=peakRecord;fightElapsed=0;
  sound.resetFight();
  document.body.classList.remove("ear-plug");
  effect = null;
  lastEffect = 0;
  baseline = null;
  clock = 90;
  round = 1;
  ko = null;
  hitstopUntil = slowmoUntil = 0;
  lastTick = -1;
  liveAnnounced = false;
  fx.clear();
  document.body.classList.remove("dazed", "low-hp");
  for (let i = 0; i < 2; i++) {
    bruises[i] = [];
    trails[i].forEach((t) => t.reset());
    Object.assign(fighters[i], {
      x: 0,
      z: i ? 0.68 : -0.68,
      hp: 100,
      ...combatState(),
      score: 0,
      ai: null,
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
      attacks: [],
      reaction: null,
      remoteIds:new Set(), push:null,
    });
    fighters[i].detector = new PunchDetector();
    fighters[i].footwork.reset();
    if (actors[i]) {
      actors[i].knockout?.reset(); actors[i].knockout=null;
      actors[i].groundOffset=null; actors[i].groundInitialized=false;
      actors[i].group.rotation.set(0, fighters[i].yaw, 0);
    }
  }
}
function enter(isOnline = false) {
  if (!loaded) return;
  sound.start().catch((e) => console.warn(e));
  sound.setMusicMode("fight");
  active = true;
  online = isOnline;
  $("lobby").hidden = true;
  $("hud").hidden = false;
  $("guide").hidden = false;
  $("exit").hidden = false;
  document.body.classList.add("fighting");
  if (window.cornerDebug) window.cornerDebug.snapCamera = true;
  $("opponentName").textContent = isOnline ? "OPPONENT" : "SPARRING";
  document.querySelector(".fighter.right .badge").textContent = isOnline ? "P2" : "CPU";
  $("exit").textContent = t("back");
  $("fightState").textContent = isOnline ? "ONLINE" : "TRAINING";
  if (!isOnline) {
    self = 0;
    // Keep a scale already measured in the menu; rebase translation at fight start.
    const f=fighters[0], old=f.footwork;
    const calibrated=cameraOn && f.tracking && old.reference && performance.now()-lastPoseTime<500;
    const cameraPose=calibrated?{pose:f.pose,aux:f.aux,reference:{...old.reference,root:(old.previous?.root||old.reference.root).slice()},floor:old.floor}:null;
    reset();
    if(cameraPose){
      f.footwork.reference=cameraPose.reference;f.footwork.floor=cameraPose.floor;
      f.pose=cameraPose.pose;f.aux=cameraPose.aux;f.tracking=true;baseline=true;
    }
    sound.start().then(()=>sound.say("pressure_guard_up", 10)).catch(console.warn);
  }
  if (!cameraOn) $("cameraButton").click();
}
function exit() {
  sound.stop();
  sound.setMusicMode("lobby");

  active = false;
  online = false;
  self = 0;
  net.close();
  $("lobby").hidden = false;
  $("hud").hidden = true;
  $("guide").hidden = true;
  $("exit").hidden = true;
  document.body.classList.remove("fighting");
  $("networkStatus").textContent = "TRAINING";
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
  $("viewButton").textContent =
    t(first ? "first" : "third");
}
$("view").onchange = setView;
$("viewButton").onclick = () => {
  $("view").value = first ? "third" : "first";
  setView();
};
$("venue").value = localStorage.getItem("cornerVenue") || "night";
arena.setVenue($("venue").value, renderer);
$("venue").onchange = () => {
  localStorage.setItem("cornerVenue", $("venue").value);
  arena.setVenue($("venue").value, renderer);
};
$("fxShake").checked = localStorage.getItem("cornerFx") !== "off";
const applyFxScale = () => {
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  shake.scale = $("fxShake").checked ? (reduced ? 0.35 : 1) : 0;
  document.body.classList.toggle("calm-fx", !$("fxShake").checked);
};
applyFxScale();
$("fxShake").onchange = () => {
  localStorage.setItem("cornerFx", $("fxShake").checked ? "on" : "off");
  applyFxScale();
};
$("artStyle").value =
  localStorage.getItem("cornerMaterial") === "original" ? "classic" : "modern";
$("artStyle").onchange = async () => {
  localStorage.setItem("cornerMaterial", $("artStyle").value === "classic" ? "original" : "modern");

  $("artStyle").disabled = true;
  try {
    await Promise.all([0, 1].map((i) => createActor(i, fighters[i].avatarId)));
  } finally {
    $("artStyle").disabled = false;
  }
};
// Lobby fighter carousel drives the same select used in settings.
const FIGHTER_INFO = {
  "boxer-prism31": ["PRISM", "Out-boxer · fast hands", [80, 62, 55]],
  boxeador: ["TITAN", "Pressure fighter · heavy hitter", [58, 74, 82]],
  "fighter-web": ["FIGHTER", "All-rounder", [66, 66, 66]],
};
function showFighter() {
  const [name, style, stats = [60, 60, 60]] = FIGHTER_INFO[$("avatarSelect").value] || [$("avatarSelect").selectedOptions[0]?.textContent || "", ""];
  $("fighterName").textContent = name;
  $("fighterStyle").textContent = style;
  $("fighterStats").innerHTML = ["Reach", "Speed", "Chin"].map((label, i) => `<div>${label}<span><i style="width:${stats[i]}%"></i></span></div>`).join("");
}
function cycleFighter(step) {
  const select = $("avatarSelect");
  if (select.disabled) return;
  select.selectedIndex = (select.selectedIndex + step + select.options.length) % select.options.length;
  showFighter();
  select.onchange();
}
$("fighterPrev").onclick = () => cycleFighter(-1);
$("fighterNext").onclick = () => cycleFighter(1);
showFighter();
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
  debugRecorder.pose(e.data, lastPoseTime);
  fighters[self].tracking = true;
  const f = fighters[self];
  const hasCameraPosition = validPose(e.data.cameraPose);
  const raw = hasCameraPosition ? e.data.cameraPose : e.data.pose;
  if (baseline === null) { f.footwork.reset(); baseline = true; }
  const captureTime=Number(e.data.nlfDebug?.capture?.absoluteMs)-performance.timeOrigin;
  const sampleTime=Number.isFinite(captureTime)&&captureTime<=lastPoseTime+10&&lastPoseTime-captureTime<1500?captureTime:lastPoseTime;
  const movement = f.footwork.update(raw, sampleTime, hasCameraPosition ? e.data.cameraInfo : null);
  if(!movement || movement.calibrating){
    f.tracking=false;f.detected=[];trackStatus('calibrating');return;
  }
  const p = movement.pose;
  const hydrated = reviveAux(e.data.aux);
  constrainFacing(p, hydrated);
  fighters[self].pose = p;
  f.poseTimestamp = lastPoseTime;
  fighters[self].aux = hydrated;
  fighters[self].headForward =
    hydrated?.kind === "smpl"
      ? headForwardFromSmplAux(hydrated)
      : reviveVector(e.data.headForward);
  fighters[self].footDirections =
    hydrated?.kind === "smpl" ? footDirectionsFromSmplAux(hydrated) : null;
  // Camera-space +Z points from the tracked fighter toward the virtual
  // opponent. A transverse/backward guard movement cannot borrow momentum.
  fighters[self].detected = fighters[self].detector.update(raw, sampleTime,[0,0,1]);
  f.lateral = f.radial = 0;
  f.lateralTarget = clamp((f.lateralOrigin || 0) + movement.lateral, -50, 50);
  f.radialTarget = $("depth").checked ? clamp((f.radialOrigin || 0) + movement.radial, -50, 50) : f.radialApplied || 0;
  trackStatus(movement.framed?'tracking':'showTorso');
  f.tracking=movement.framed;
  refreshCameraUI();
});
$("cameraButton").onclick = async () => {
  try {
    const bridge = $("tracker").contentWindow.cornerTracking;
    if (!bridge)
      throw Error(t("trackerLoading"));
    if (cameraOn) {
      bridge.stop();
      cameraOn = false;
      fighters[self].tracking = false;
      actors[self]?.guardContact.reset();
      $("preview").hidden = true;
      trackStatus("noCamera");
      return;
    }
    cameraOn = true;
    fighters[self].tracking = false;
    fighters[self].lateralOrigin = fighters[self].lateralTarget || 0;
    fighters[self].radialOrigin = fighters[self].radialTarget || 0;
    if(actors[self]) actors[self].groundOffset=null;
    actors[self]?.guardContact.reset();
    if (actors[self]) actors[self].groundInitialized = false;
    baseline = null;
    poseFrameTime = -1;
    lastPoseTime = 0;
    trackStatus("starting");
    await bridge.start();
    $("cameraButton").textContent = t("webcam");
    $("preview").srcObject = bridge.video.srcObject;
    $("preview").hidden = false;
    trackStatus("calibrating");
  } catch (e) {
    cameraOn = false;
    trackStatus("cameraError");console.warn(e);
  }
};
$("calibrate").onclick = () => {
  if (actors[self]) {
    resetHeadCalibration(actors[self].rig);
    resetRetargetFilters(actors[self].rig);
    actors[self].guardContact.reset();
  }
  fighters[self].lateralOrigin = fighters[self].lateralTarget || 0;
  fighters[self].radialOrigin = fighters[self].radialTarget || 0;
  if(actors[self]) actors[self].groundOffset=null;
  if (actors[self]) actors[self].groundInitialized = false;
  baseline = null;
  trackStatus("calibrating");
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
      notify("READY", 2);
    }
    if (m.type === "disconnected") {
      ready = false;
      notify("WAITING", 3);
    }
    if (m.type === "input" && self === 0 && validPose(m.pose)) {
      if(Array.isArray(m.journalRequest))for(let i=0;i<2;i++)
        journalRequest[i]=clamp(Math.floor(Number(m.journalRequest[i])||0),0,fighters[i].journal.entries.length);
      if(finalResult&&m.resultAck&&journalRequest.every((n,i)=>n>=fighters[i].journal.entries.length)){
        terminalSynced=true;net.send(snapshot());
      }
      const f = fighters[1];
      f.tracking = !!m.tracking;
      syncAvatar(1, m.avatarId);
      f.pose = m.pose;
      f.poseTimestamp = performance.now();
      f.aux = reviveAux(m.aux);
      f.lateral = clamp(Number(m.lateral) || 0, -1, 1);
      f.lateralTarget = clamp(Number(m.lateralTarget) || 0, -50, 50);
      f.radialTarget = clamp(Number(m.radialTarget) || 0, -50, 50);
      f.radial = clamp(Number(m.radial) || 0, -1, 1);
      f.lastInput = performance.now();
      if(Array.isArray(m.attacks))for(const attack of m.attacks.slice(0,4)){
        if(![0,1].includes(attack.hand)||!Number.isInteger(attack.id)||attack.id<1)continue;
        const existing=f.attacks.find(a=>a.remoteId===attack.id);
        if(existing){existing.forceN=Math.max(existing.forceN,safeForce(Number(attack.forceN)));existing.speed=clamp(Number(attack.speed)||0,0,12);continue;}
        f.remoteIds ??= new Set();if(f.remoteIds.has(attack.id))continue;
        f.remoteIds.add(attack.id);
        if(f.remoteIds.size>4000)f.remoteIds=new Set([...f.remoteIds].slice(-1000));
        const forceN=safeForce(Number(attack.forceN)),speed=clamp(Number(attack.speed)||0,0,12);
        f.attacks.push({remoteId:attack.id,hand:attack.hand,start:performance.now(),hit:false,mocap:true,forceN,speed,
          journalIndex:f.journal.attempt({hand:attack.hand,forceN,speed},fightElapsed)});
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
          dizzy: clamp(Number(f.dizzy) || 0, 0, 5),
          recoil: clamp(Number(f.recoil) || 0, 0, 1),
          weakened: clamp(Number(f.weakened) || 0, 0, 2),
          tracking: !!f.tracking,
          score: Number(f.score) || 0,
        });
        if(Array.isArray(f.journal)){
          const offset=Math.max(0,Number(f.journalOffset)||0);
          const incoming=f.journal.filter(e=>Number.isFinite(e.t)&&Number.isFinite(e.forceN));
          incoming.forEach((e,k)=>fighters[i].journal.entries[offset+k]={...e,forceN:safeForce(e.forceN)});
          if(Array.isArray(f.journalArchive)) f.journalArchive.forEach((e,k)=>{
            if(e&&Number.isFinite(e.t)&&Number.isFinite(e.forceN))fighters[i].journal.entries[Math.max(0,f.journalArchiveOffset||0)+k]={...e,forceN:safeForce(e.forceN)};
          });
          fighters[i].journal.maxComboForce=Number(f.journalMeta?.maxComboForce)||0;
          fighters[i].journal.damageReceived=Number(f.journalMeta?.damageReceived)||0;
          fighters[i].journal.receivedPeak=safeForce(Number(f.journalMeta?.receivedPeak));
          if(i===self) for(const row of fighters[i].journal.entries) if(row?.landed)rememberPeak(row.forceN);
        }
        fightElapsed=Number(m.elapsed)||fightElapsed;
        if (f.stats && typeof f.stats === "object")
          for (const k of Object.keys(fighters[i].stats))
            fighters[i].stats[k] = Number(f.stats[k]) || 0;
        if (i !== self) {
          fighters[i].pose = f.pose;
          fighters[i].poseTimestamp = performance.now();
          fighters[i].aux = reviveAux(f.aux);
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
      }
      if (m.result) finish(m.result, false);
      if(m.journalComplete)terminalSynced=true;
      if(finalResult)renderResult();
    }
  },
  (s) => {
    const key=['connectionError','disconnected','connecting','waiting','joined'].includes(s)?s:'connectionError';
    roomStatusKey=key;$("roomStatus").textContent = t(key);
    $("networkStatus").textContent = key==='joined'?'ONLINE':'WAITING';
  },
);
$("server").value =
  localStorage.getItem("cornerServer") ||
  "wss://corner-relay.lnyx9r.easypanel.host";
$("join").onclick = () => {
  const url = $("server").value.trim(),
    room = $("room").value.trim().toUpperCase();
  if (!/^wss?:\/\//.test(url) || !/^[A-Z0-9_-]{3,24}$/.test(room)) {
    roomStatusKey="roomInvalid";$("roomStatus").textContent = t(roomStatusKey);
    return;
  }
  localStorage.setItem("cornerServer", url);
  net.connect(url, room, $("transport").value);
};
let finalResult = null;
function finish(result, broadcast = true) {
  if (finalResult) return;
  finalResult = result;
  terminalSynced=false;
  active = false;
  const victim = result.ko && result.winner !== null ? 1 - result.winner : null;
  ko = { start: performance.now(), vstart: vclock, victim, shown: false, delay: result.ko ? 2600 : 1500 };
  if (victim !== null && actors[victim]) {
    const f=fighters[victim],other=fighters[1-victim];
    actors[victim].knockout=new KnockoutRelaxation(actors[victim], f, [f.x-other.x,0,f.z-other.z]);
    f.push=null;f.blockHold=null;f.guardCompression=null;
  }
  document.body.classList.remove("dazed");
  sound.setMusicMode("ko");
  if (result.ko) {
    sound.ko(victim===self && !sound.reducedImpact);
    sound.say("ko_k_o",100);
    if(victim===self){sound.earPlug(4);if(!sound.reducedImpact)document.body.classList.add('ear-plug');}
    hitstopUntil = performance.now() + 220;
    slowmoUntil = performance.now() + 1500;
    shake.add(0.9, 6);
    flashes.burst(20);
    banner("K.O.", "ko", 2400);
  } else {
    sound.bell();
    banner(result.winner === null ? "DRAW" : "TIME", "end", 1500);
  }
  renderResult();
  if (online && self === 0 && broadcast) net.send(snapshot());
}
function renderResult(){
 const result=finalResult;if(!result)return;
 const j=fighters[self].journal,summary=j.summary(fightElapsed);
 $("resultTitle").textContent=t(result.winner===null?'draw':result.winner===self?'victory':'defeat');
 $("result").dataset.outcome=result.winner===null?'draw':result.winner===self?'win':'loss';
 $("resultText").textContent=t(result.ko?'knockout':'decision');
 const dash='–',n=(v,unit=' N',digits=0)=>v===null?dash:number(v,digits)+unit;
 const newPeak=summary.peak!==null&&summary.peak>previousPeak;
 const cards=[
  [n(summary.peak),'peak',summary.peak!==null?'≈ '+number(summary.peak/9.81)+' kgf':''],
  [summary.total===null?dash:number(summary.total/1000,1)+' kN','total',''],
  [n(summary.average),'average',''],
  [summary.accuracy===null?dash:number(summary.accuracy*100)+'%','accuracy',summary.attempts?summary.hits+' '+t('of')+' '+summary.attempts:'']
 ];
 $("resultStats").innerHTML=cards.map(([value,key,detail],i)=>'<div title="'+t('forceTip')+'" class="'+(i===0&&newPeak?'new-peak':'')+'"><b>'+value+'</b><span>'+t(key)+'</span><em>'+detail+(i===0&&newPeak?' · NEW PEAK':'')+'</em></div>').join('');
 const support=[['headPeak',n(summary.headPeak)],['bodyPeak',n(summary.bodyPeak)],['combo',summary.maxCombo?summary.maxCombo+' '+t('hits')+' · '+n(summary.maxComboForce):dash],['fastest',n(summary.fastest,' m/s',1)],['chin',fighters[self].stats.chin],['blocks',fighters[self].stats.blocked],['perMinute',number(summary.perMinute,1)],['damageReceived',number(summary.damageReceived,1)],['receivedPeak',n(summary.receivedPeak||null)]];
 for(const id of ['forte','pesado','devastador'])support.push(['tier_'+id,summary.tiers[id]]);
 if(newPeak)support.push(['previousPeak',previousPeak>0?n(previousPeak):dash]);
 $("resultSupport").innerHTML='<div class="stat-support">'+support.map(([key,value])=>'<span>'+t(key)+'<b>'+value+'</b></span>').join('')+'</div>';
 const visibleEntries=j.entries.filter(Boolean);
 const max=Math.max(1,...visibleEntries.map(e=>e.forceN)),duration=Math.max(1,fightElapsed,...visibleEntries.map(e=>e.t));
 $("resultTimeline").replaceChildren();
 const peakIndex=j.entries.findIndex(e=>e?.landed&&e.forceN===summary.peak);
 j.entries.forEach((e,i)=>{
  const bar=document.createElement('span');bar.className='bar'+(!e.landed?' miss':'')+(newPeak&&i===peakIndex?' peak':'');
  bar.dataset.tier=e.tier;bar.style.height=Math.max(2,e.forceN/max*85)+'%';bar.style.left=Math.min(99,e.t/duration*99)+'%';bar.style.width=Math.max(.3,Math.min(2,60/Math.max(1,j.entries.length)))+'%';
  bar.title=number(e.t,1)+' s · '+n(e.forceN)+' · '+t('tier_'+e.tier)+' · '+t(e.blocked?'blocked':e.landed?'hit':'miss');
  $("resultTimeline").append(bar);
 });
}
function separateBodies(){
 if(!hitboxes[0]||!hitboxes[1])return;
 const sync=()=>fighters.forEach((f,i)=>{
  const actor=actors[i],box=hitboxes[i];if(!actor||!box)return;
  const dx=f.x-actor.group.position.x,dz=f.z-actor.group.position.z;
  const shift=p=>{p[0]+=dx;p[2]+=dz;};
  shift(box.head.c);shift(box.chin.c);shift(box.body.a);shift(box.body.b);
  box.arms.forEach(c=>{shift(c.a);shift(c.b);});box.gloves.forEach(shift);
  actor.group.position.x=f.x;actor.group.position.z=f.z;actor.group.updateMatrixWorld(true);
 });
 sync();
 const [a,b]=fighters;
 const bodies=hitboxes.map(box=>({...box.body,r:box.body.r-GLOVE_RADIUS+.003}));
 const contact=capsulePenetration(...bodies);
 const pelvisD=Math.hypot(b.x-a.x,b.z-a.z);
 const depth=Math.max(contact.depth,COMBAT.minDistance-pelvisD);
 if(depth<=0)return;
 let dx=contact.normal[0],dz=contact.normal[2],horizontal=Math.hypot(dx,dz);
 if(horizontal<.01){dx=b.x-a.x;dz=b.z-a.z;horizontal=Math.hypot(dx,dz);}
 if(horizontal<.01){dx=Math.sin(a.yaw);dz=Math.cos(a.yaw);horizontal=1;}
 dx/=horizontal;dz/=horizontal;
 // If one root meets a rope boundary, spend the remaining correction on the
 // other fighter. Clamping half of the overlap must not leave bodies crossed.
 const oldAX=a.x,oldAZ=a.z,oldBX=b.x,oldBZ=b.z;
 const move=(f,sign,amount)=>{const x=f.x,z=f.z;f.x=clamp(x+dx*sign*amount,-2.55,2.55);f.z=clamp(z+dz*sign*amount,-2.55,2.55);return (f.x-x)*dx*sign+(f.z-z)*dz*sign;};
 const needed=depth/Math.max(.2,horizontal)+.001;
 const movedA=move(a,-1,needed/2),movedB=move(b,1,needed-movedA);
 if(movedA+movedB<needed)move(a,-1,needed-movedA-movedB);
 sync();
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
    .catch((e) => notify(t("peerError")))
    .finally(() => (switching[i] = false));
}
function snapshot() {
  return {
    type: "state",
    clock,
    round,
    elapsed:fightElapsed,
    effect,
    result: finalResult,
    journalComplete:terminalSynced,
    fighters: fighters.map((f) => ({
      x: f.x,
      z: f.z,
      yaw: f.yaw,
      hp: f.hp,
      stun: f.stun,
      dizzy: f.dizzy,
      recoil: f.recoil,
      weakened: f.weakened,
      stats: f.stats,
      journal: f.journal.entries.slice(-8),
      journalOffset:Math.max(0,f.journal.entries.length-8),
      // Requested history repairs missed snapshots without compacting absolute
      // indices or sending an unbounded journal in a single network packet.
      journalArchive:f.journal.entries.slice(journalRequest[fighters.indexOf(f)],journalRequest[fighters.indexOf(f)]+16),
      journalArchiveOffset:journalRequest[fighters.indexOf(f)],
      journalMeta: {maxComboForce:f.journal.maxComboForce,damageReceived:f.journal.damageReceived,receivedPeak:f.journal.receivedPeak},
      pose: f.pose,
      aux: f.aux,
      tracking: !!f.tracking,
      score: f.score,
      avatarId: f.avatarId,
      lateralApplied: f.lateralApplied || 0,
      radialApplied: f.radialApplied || 0,
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
const hudSide = (i) => (i === self ? 0 : 1);
const powerShownAt = [0, 0];
function restartAnimation(el, ...classes) {
  el.classList.remove(...classes);
  void el.offsetWidth;
  el.classList.add(...classes);
}
let bannerUntil = 0;
function banner(text, kind = "", ms = 1200) {
  const el = $("banner");
  el.textContent = text;
  el.dataset.kind = kind;
  restartAnimation(el, "show");
  bannerUntil = performance.now() + ms;
}
function showPower(i,forceN){
 const side=hudSide(i),power=punchPower(forceN),tier=punchTier(forceN);
 $("pow"+side).style.width=Math.round(power*100)+'%';
 $("pow"+side).parentElement.dataset.level=tier.id;
 $("powLabel"+side).textContent=tier.label;
 powerShownAt[side]=performance.now();
}
function showCombo(i, n) {
  if (!(n >= 3)) return;
  const el = $("combo" + hudSide(i));
  el.innerHTML = "<b>" + n + "</b><span>HITS · "+(n>=7?"UNSTOPPABLE":"COMBO")+"</span>";
  if(i===self){if(n===3)sound.say("combo_combo",20);else if(n===5)sound.say("combo_keep_it_going",20);else if(n===7)sound.say("combo_unstoppable",20);}
  restartAnimation(el, "show");
  sound.combo(n);
}
function impact(pos, blocked, hit = null) {
  const kind = hit?.kind || (blocked ? "guard" : hit?.head === false ? "body" : "clean");
  const forceN=safeForce(Number(hit?.forceN)||0),tier=punchTier(forceN),power=punchPower(forceN);
  const victim = [0, 1].includes(hit?.victim) ? hit.victim : null;
  const attacker = victim === null ? null : 1 - victim;
  const dir = Array.isArray(hit?.dir) && hit.dir.length === 3 && hit.dir.every(Number.isFinite) ? hit.dir.slice() : null;
  const big = kind === "chin" || kind === "finisher" || tier.id === "devastador";
  const t = performance.now();
  sound.impact({ kind, power, tier:tier.id, head: hit?.head !== false });
  fx.hit(pos, kind, power, dir);
  if (victim !== null && dir)
    fighters[victim].reaction = { dir, head: hit?.head !== false, blocked, kind, power, start: vclock };
  // Hit-stop sells weight; blocks get a shorter stop.
  hitstopUntil = Math.max(hitstopUntil, t + (blocked ? 35 : big ? 110 : 45 + power * 35));
  if (big) slowmoUntil = t + 320;
  if (!blocked && power >= 0.5) { punchZoom.amount = big ? 6 : 2 + power * 3; punchZoom.start = t; }
  const weight = victim === self ? 1.25 : attacker === self ? 0.8 : 0.5;
  shake.add((blocked ? 0.12 : big ? 0.65 : 0.22 + power * 0.25) * weight, blocked ? 0 : big ? 5 : 1.5 + power * 2);
  if (!blocked) flashes.burst(big ? 9 : Math.round(power * 4));
  if (victim !== null && actors[victim] && !blocked) {
    const a = actors[victim];
    a.flashStart = vclock;
    a.flashPeak = big ? 0.22 : 0.12;
    a.flashColor.value.set(big ? "#ffb21a" : "#c5e6ff");
  }
  // Strong head shots leave a mark where they land.
  if (victim !== null && !blocked && hit?.head !== false && (power >= 0.5 || big)) {
    const head = actors[victim]?.rig.bones.get("head")?.bone.getWorldPosition(new THREE.Vector3());
    if (head) {
      const toward = new THREE.Vector3(fighters[attacker].x - fighters[victim].x, 0, fighters[attacker].z - fighters[victim].z).normalize();
      const direction = kind === "chin" ? toward.add(new THREE.Vector3(0, -1.3, 0)) : new THREE.Vector3(...pos).sub(head).add(toward.multiplyScalar(0.05));
      addBruise(victim, direction, kind === "chin" ? 0.8 : 0.3 + power * 0.35);
    }
  }
  if (attacker !== null && [0,1].includes(hit?.hand))
    fighters[attacker].blockHold={hand:hit.hand,guard:hit.arm,start:performance.now(),point:null,contact:pos.slice(),dir,blocked,victim};
  if(victim!==null && hitboxes[victim]){
    const actor=actors[victim];
    const nearest=[0,1].sort((a,b)=>new THREE.Vector3(...hitboxes[victim].gloves[a]).distanceTo(new THREE.Vector3(...pos))-new THREE.Vector3(...hitboxes[victim].gloves[b]).distanceTo(new THREE.Vector3(...pos)))[0];
    fighters[victim].guardCompression={hand:[0,1].includes(hit?.arm)?hit.arm:nearest,start:performance.now()};
  }
  if(attacker===self&&!blocked&&forceN>=PUNCH.minN)rememberPeak(forceN);
  // Impact reads through world-space particles; force remains in the HUD.
  if (attacker !== null) {
    showPower(attacker, forceN);
    if (!blocked) showCombo(attacker, hit?.combo);
  }
  if (victim !== null) restartAnimation($("hud").querySelectorAll(".fighter")[hudSide(victim)], blocked ? "blocked" : "hit");
  if (victim === self && !blocked) restartAnimation($("screenFx"), big ? "chin" : "hurt");
  if (victim === self && !blocked) {
    sound.hurtMuffle(big ? 1 : 0.35 + power * 0.35);
    if (big) sound.ring();
  }
  if(hit?.lowHp){sound.say(victim===self?'pressure_he_s_got_you':'hit_he_s_hurt',70);}
  if(hit?.dizzy && victim!==null){
    banner('ROCKED','dizzy',1400);
    sound.say(victim===self?['pressure_you_re_hurt','pressure_stay_up','pressure_hold_it']: 'hit_he_s_rocked',80);
  }else if(kind==='arm'||kind==='guard')notify('BLOCKED',.7);
  else if(kind==='chin')notify('ON THE CHIN',.9);
  else if(kind==='counter')notify('COUNTER',.9);
  else if(kind==='finisher')notify('FINISHER',.9);
  else if(hit?.weakened)notify(victim===self?'LIVER SHOT · WEAKENED':'LIVER SHOT',1);
  if(attacker===self&&!blocked){
    if(kind==='chin')sound.say('hit_clean',60);
    else if(kind==='finisher')sound.say('hit_finish_it',60);
    else if(kind==='counter')sound.say(['counter_counter','counter_caught_him'],60);
    else if(tier.id==='forte')sound.say('hit_good',40);
    else if(tier.id==='pesado')sound.say('hit_heavy',40);
    else if(tier.id==='devastador')sound.say('hit_brutal',40);
  }

}
// Sparring partner: guard rhythm with real openings, telegraphed punches,
// covering after being hit and pressure when the player is dazed.
function updateBot(bot, player, now, dt) {
  const ai = (bot.ai ??= { mode: "guard", until: now + 1600, next: now + 1500, guard: 1, punch: null, attack: 0, lastHand: 1 });
  if (bot.dizzy > 0) ai.mode = "dizzy";
  else if (ai.mode === "dizzy") (ai.mode = "cover"), (ai.until = now + 900);
  else if (now > ai.until) {
    ai.mode = ai.mode === "guard" && Math.random() < 0.6 ? "open" : "guard";
    ai.until = now + (ai.mode === "open" ? 900 + Math.random() * 1000 : 1200 + Math.random() * 1500);
  }
  const target = { guard: 1, cover: 1, open: 0.2, dizzy: 0 }[ai.mode];
  ai.guard += (target - ai.guard) * (1 - Math.exp(-dt * 8));
  const pressing = player.dizzy > 0;
  if (!ai.punch && now > ai.next && bot.stun <= 0 && bot.recoil <= 0 && bot.dizzy <= 0 && ai.mode !== "cover") {
    const candidates = sparringLibrary?.clips.filter(c => c.hand !== ai.lastHand);
    const clip = candidates?.length ? candidates[Math.floor(Math.random() * candidates.length)] : null;
    const hand = clip ? clip.hand : ai.lastHand === 0 ? 1 : Math.random() < 0.7 ? 0 : 1;
    ai.lastHand = hand;
    ai.punch = {
      hand,
      body: Math.random() < 0.25,
      start: now,
      windup: pressing ? 110 : 190,
      speed: (pressing ? 3.1 : 2.2) + Math.random() * 1.3,
      launched: false,
      blockedAt: 0,
      clip,
    };
  }
  let attack = 0, hand = -1, body = false;
  if (ai.punch) {
    const p = ai.punch, age = now - p.start;
    hand = p.hand;
    body = p.body;
    if (p.clip) {
      const elapsed = age / 1000;
      if (!p.launched && elapsed >= p.clip.launch && !p.blockedAt) {
        p.launched = true;
      }
      attack = clamp((elapsed - p.clip.launch + .12) / .15, 0, 1);
      ai.captured = playStrike(p.clip, elapsed, sparringLibrary.guard);
      if (p.blockedAt) {
        p.blockFrame ||= ai.captured;
        ai.captured = mixFrames(p.blockFrame, sparringLibrary.guard, (now - p.blockedAt) / 180);
      }
      if (elapsed >= p.clip.duration || (p.blockedAt && now - p.blockedAt >= 180)) {
        ai.punch = null;
        ai.next = now + (pressing ? 450 + Math.random() * 350 : 1100 + Math.random() * 1000);
      }
    } else if (age < p.windup) attack = -0.15 * Math.sin(((age / p.windup) * Math.PI) / 2);
    else {
      if (!p.launched) {
        p.launched = true;
      }
      const u = (age - p.windup) / 260;
      attack = Math.sin(clamp(u, 0, 1) * Math.PI);
      if (p.blockedAt) attack = Math.min(attack, p.blockedValue * Math.max(0, 1 - (now - p.blockedAt) / 160));
      if (u >= 1) {
        ai.punch = null;
        ai.next = now + (pressing ? 450 + Math.random() * 350 : 1100 + Math.random() * 1000);
      }
    }
  }
  ai.attack = attack;
  const procedural = sparringPose(now / 1000, { guard: ai.guard, hand: sparringLibrary ? -1 : hand, attack, body, dizzy: bot.dizzy > 0 ? 1 : 0 });
  let display = poseFrame(procedural);
  if (sparringLibrary && bot.dizzy <= 0) {
    display = mixFrames(display, sparringLibrary.guard, ai.guard);
    if (ai.punch?.clip || ai.captured) {
      display = ai.captured || display;
      if (!ai.punch) ai.captured = null;
    }
    if (ai.release) {
      display = mixFrames(ai.release.frame, display, (now - ai.release.at) / 180);
      if (now - ai.release.at >= 180) ai.release = null;
    }
  }
  bot.pose = display.pose;
  bot.aux = reviveAux({ kind: 'smpl', ...display.aux });
  bot.poseTimestamp = now;
  bot.lateral = bot.dizzy > 0 ? Math.sin(now / 300) * 0.2 : Math.sin(now / 1800) * 0.25;
  // Hovers at jab range (a face-aimed straight lands up to ~0.9 m) and steps in to throw.
  const range = ai.punch ? 0.76 : pressing ? 0.8 : 0.86;
  const distance = Math.hypot(player.x - bot.x, player.z - bot.z);
  bot.radial = bot.dizzy > 0 ? -0.25 : clamp((distance - range) * 2.5, -0.5, 0.7);
  bot.detected=bot.detector.update(bot.pose.map(p=>worldPoint(bot,p)),now,[player.x-bot.x,0,player.z-bot.z]);
}
function onBotHit(bot, blocked) {
  const ai = bot.ai;
  if (!ai || blocked) return;
  if (ai.punch?.clip) {
    ai.release = { frame: poseFrame(bot.pose, bot.aux), at: vclock };
    ai.punch = null;
    ai.captured = null;
    bot.attacks = [];
    ai.next = vclock + 1000;
  } else if (ai.punch && !ai.punch.launched) ai.punch = null;
  if (bot.dizzy <= 0) (ai.mode = "cover"), (ai.until = vclock + 650 + Math.random() * 450);
}
function simulate(dt, now) {
  if (!active || (online && !ready)) return;
  const f = fighters[self];
  if (!cameraOn || !f.tracking || now - lastPoseTime > 500) {
    f.lateral = f.radial = 0;
    f.attacks = [];
    f.detected = [];
    if (cameraOn && lastPoseTime && now - lastPoseTime < 1500) return;
    trackStatus(!cameraOn?'noCamera':trackingKey==='calibrating'?'calibrating':'trackingLost');
    return;
  }
  if (
    online &&
    (!fighters[1 - self].tracking ||
      (self === 0 && now - (fighters[1].lastInput || 0) > 1000))
  ) {
    $("fightState").textContent = "WAITING FOR CAMERA";
    return;
  }
  $("fightState").textContent = online ? "ONLINE" : "TRAINING";
  if (!liveAnnounced) {
    liveAnnounced = true;
    banner("ROUND " + round, "round", 1500);
    sound.bell();
  }
  for (const hit of f.detected || []) {
    f.attacks.push({
      hand: hit.hand,
      start: now,
      hit: false,
      mocap: true,
      speed: hit.speed,
      forceN:hit.forceN, stroke:hit, id:hit.id,
      journalIndex:f.journal.attempt(hit,fightElapsed),
      previous: hit.previous ? worldPoint(f, hit.previous) : null,
    });
    // Immediate feedback on every punch, hit or miss.
    sound.whoosh(punchPower(hit.forceN));
    showPower(self, hit.forceN);
  }
  f.detected = [];
  if (online && self === 1) {
    applyLateralPose(f, fighters[0]);
    f.attacks = f.attacks.filter((a) => now - a.start < 400);
    return;
  }
  if (!online) {
    updateBot(fighters[1], fighters[0], now, dt);
    const bot=fighters[1];
    for(const hit of bot.detected||[])bot.attacks.push({hand:hit.hand,start:now,hit:false,mocap:true,speed:hit.speed,forceN:hit.forceN,stroke:hit,journalIndex:bot.journal.attempt(hit,fightElapsed)});
    bot.detected=[];
  } else if (now - (fighters[1].lastInput || 0) > 1000) {
    fighters[1].lateral = fighters[1].radial = 0;
    fighters[1].attacks = [];
  }
  fighters[self].tracking = true;
  clock -= dt;fightElapsed+=dt;
  for (let i = 0; i < 2; i++) {
    const a = fighters[i],
      b = fighters[1 - i];
    applyLateralPose(a, b);
    a.stun = Math.max(0, a.stun - dt);
    a.dizzy = Math.max(0, a.dizzy - dt);
    a.recoil = Math.max(0, a.recoil - dt);
    a.weakened = Math.max(0, a.weakened - dt);
    a.dizzyImmune = Math.max(0, a.dizzyImmune - dt);
    // Only the analytic bot uses velocity/autoadvance. Human position is
    // entirely owned by camera translation, including deliberate retreat.
    if (!online && i !== self) orbitalStep(a, b, a.lateral * (a.stun ? 0.65 : 1), a.radial, dt, {min:COMBAT.minDistance,max:4.8});
    else a.yaw = Math.atan2(b.x-a.x, b.z-a.z);
    stepImpactPush(a,dt);
    separateBodies();
    for (const atk of a.attacks) {
      const age = now - atk.start;
      if (atk.hit || age > 300) continue;
      // Damage follows the fastest wrist speed seen during the punch.
      if(atk.stroke){atk.forceN=atk.stroke.forceN;atk.speed=atk.stroke.speed;}
      if(atk.journalIndex===undefined)atk.journalIndex=a.journal.attempt(atk,fightElapsed);
      const mesh = hitboxes[i] && hitboxes[1 - i];
      // Pose-space start points are not comparable with mesh space: restart the sweep.
      if (mesh && !atk.meshSweep) (atk.previous = null), (atk.meshSweep = true);
      const current = mesh ? hitboxes[i].gloves[atk.hand].slice() : worldPoint(a, a.pose[12 + atk.hand]),
        previous = atk.previous || current;
      atk.previous = current;
      if (!atk.mocap && age <= 30) continue;
      // A dazed or recoiling fighter cannot raise a working guard.

      // Fight collision exclusively uses the visible gloves/forearms, even
      // during dizziness. If a rendered avatar is absent, suspend collision.
      const res=mesh?resolvePunchBox(previous,current,hitboxes[1-i]):null;
      if (!res) continue;
      atk.hit = true;
      const speed=clamp(atk.speed||0,0,12),forceN=safeForce(atk.forceN),power=punchPower(forceN);
      if(forceN<PUNCH.minN){
        a.journal.land(atk.journalIndex,{forceN,target:res.target,combo:0,blocked:res.target==='arm',speed});
        impact(res.point,false,{kind:'touch',forceN,victim:1-i,hand:atk.hand,head:res.target==='head'});
        continue;
      }
      const guard=false;
      const counter = b.recoil > 0 || b.attacks.some((x) => !x.hit && now - x.start < 260);
      const chin = res.chin && !guard && power >= COMBAT.chinPower;
      const kind =
        res.target === "arm" ? "arm"
        : guard ? "guard"
        : b.dizzy > 0 ? "finisher"
        : chin ? "chin"
        : counter ? "counter"
        : res.target === "body" ? "body"
        : "clean";
      const blocked = kind === "arm" || kind === "guard";
      const damage = punchDamage({
        forceN,
        target: res.target,
        chin,
        guard,
        dizzy: b.dizzy > 0,
        counter,
        weakened: a.weakened > 0 || a.dizzy > 0,
      });
      const beforeHp=b.hp;
      b.hp = Math.max(0, b.hp - damage);
      const lowHp=beforeHp>25&&b.hp<=25&&!b.lowHpSaid;
      if(lowHp)b.lowHpSaid=true;
      b.journal.damageReceived+=damage;
      if(res.target!=='arm')b.journal.receivedPeak=Math.max(b.journal.receivedPeak,forceN);
      let dizzyStart = false, weakenedStart = false;
      if (blocked) {
        b.stats.blocked++;
        a.combo = 0;
        // The punch stopped on the guard: the puncher's own guard is left open.
        if (kind === "arm") a.recoil = COMBAT.recoilSeconds;
      } else {
        a.score++;
        a.stats.clean++;
        a.combo = now < a.comboUntil ? a.combo + 1 : 1;
        a.comboUntil = now + 1300;
        a.stats.maxCombo = Math.max(a.stats.maxCombo, a.combo);
        a.stats.fastest = Math.max(a.stats.fastest, speed);
        b.combo = 0;
        if (res.target === "head") {
          b.headHits = b.headHits.filter((t) => now - t < 3000);
          b.headHits.push(now);
          b.stun = Math.max(b.stun, 0.45 + 0.4 * power);
          if (chin) a.stats.chin++;
          if ((chin || b.headHits.length >= 3) && b.dizzy <= 0 && b.dizzyImmune <= 0 && b.hp > 0) {
            b.dizzy = chin ? COMBAT.dizzySeconds : 1.8;
            b.stun = b.dizzy;
            b.dizzyImmune = b.dizzy + COMBAT.dizzyImmunity;
            b.headHits = [];
            dizzyStart = true;
          }
        } else {
          b.stun = Math.max(b.stun, 0.25);
          if (power > 0.6) {
            b.weakened = 1.2;
            b.stun = Math.max(b.stun, 0.6);
            weakenedStart = true;
          }
        }
      }
      a.journal.land(atk.journalIndex,{forceN,target:res.target,combo:a.combo,blocked,speed});
      if(!blocked&&i===self)rememberPeak(forceN);
      if(!blocked){
        const away=new THREE.Vector3(b.x-a.x,0,b.z-a.z).normalize();
        addImpactPush(b,away.toArray(),forceN,kind==='finisher');
      }
      if (!online && i === self) onBotHit(b, blocked);
      if (!online && i !== self && kind === "arm" && a.ai?.punch)
        (a.ai.punch.blockedAt = now), (a.ai.punch.blockedValue = a.ai.attack);
      const direction = new THREE.Vector3(...current).sub(new THREE.Vector3(...previous));
      if (direction.lengthSq() < 0.0001) direction.set(b.x - a.x, 0, b.z - a.z);
      direction.normalize();
      let pos = res.point;
      if (res.target !== "arm") {
        const box = mesh ? hitboxes[1 - i] : null;
        const center = new THREE.Vector3(...(box
          ? chin ? box.chin.c : res.target === "head" ? box.head.c : box.body.b
          : chin ? worldPoint(b, chinPoint(b.pose)) : res.target === "head" ? worldPoint(b, b.pose[15]) : worldPoint(b, b.pose[7])));
        const surface = new THREE.Vector3(...previous).sub(center);
        if (surface.lengthSq() < 0.0001) surface.copy(direction).negate();
        const radius = box
          ? chin ? 0.03 : res.target === "head" ? box.head.r - GLOVE_RADIUS : box.body.r - GLOVE_RADIUS
          : chin ? 0.06 : res.target === "head" ? 0.2 : 0.26;
        pos = surface.normalize().multiplyScalar(radius).add(center).toArray();
      }
      effect = {
        seq: (effect?.seq || 0) + 1,
        pos,
        blocked,
        kind,
        power,
        damage,
        forceN,
        lowHp,
        victim: 1 - i,
        hand: atk.hand,
        arm: res.arm,
        head: res.target !== "body",
        dir: direction.toArray(),
        combo: blocked ? 0 : a.combo,
        dizzy: dizzyStart,
        weakened: weakenedStart,
      };
      impact(effect.pos, blocked, { ...effect, mocap: !!atk.mocap });
    }
    a.attacks = a.attacks.filter((x) => now - x.start < 380);
  }
  if (fighters.some((x) => x.hp <= 0))
    finish({ winner: fighters[0].hp > 0 ? 0 : 1, reason: "knockout", ko: true });
  if (clock <= 0) {
    if (round < 3) {
      round++;
      for(const f of fighters)f.lowHpSaid=false;
      clock = 90;
      sound.bell();
      banner("ROUND " + round, "round", 1600);
    } else
      finish({
        winner:
          fighters[0].hp === fighters[1].hp
            ? null
            : fighters[0].hp > fighters[1].hp
              ? 0
              : 1,
        reason: "decision",
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
function applyImpactReaction(actor, reaction, t) {
  if (!reaction) return;
  const age = Math.max(0, (t - reaction.start) / 1000);
  const big = reaction.kind === "chin" || reaction.kind === "finisher";
  if (age > (big ? 0.9 : 0.55)) return;
  const envelope = (1 - Math.exp(-age / 0.035)) * Math.exp(-age / (big ? 0.26 : 0.16));
  const direction = new THREE.Vector3(...reaction.dir).normalize();
  let axis = new THREE.Vector3(0, 1, 0).cross(direction);
  if (axis.lengthSq() < 0.001) axis.set(1, 0, 0);
  axis.normalize();
  const power = reaction.power ?? 0.5;
  const strength = reaction.blocked ? 0.18 : reaction.head ? (big ? 1 + power * .35 : 0.65 + power * 0.4) : 0.6 + power * 0.6;
  // Head shots snap the head back; body shots fold the trunk toward the punch.
  const chain = reaction.head || reaction.blocked
    ? [["spine2", 0.045], ["neck", 0.17], ["head", 0.23]]
    : [["spine", -0.1], ["spine1", -0.09], ["spine2", -0.08], ["head", 0.08]];
  for (const [name, angle] of chain) {
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
// A punch that meets the guard stops on the forearm, holds, then recoils:
// two-bone IK on the rendered arm, independent of the live mocap target.
function applyBlockHold(i){
 const f=fighters[i],hold=f.blockHold,a=actors[i];
 if(!hold||!a)return;
 const age=(performance.now()-hold.start)/1000;
 if(age>.19){f.blockHold=null;return;}
 const side=hold.hand?'right':'left',bone=n=>a.rig.bones.get(side+n)?.bone;
 const arm=bone('Arm'),fore=bone('ForeArm'),hand=bone('Hand');
 if(!arm||!fore||!hand)return;
 const live=hand.getWorldPosition(new THREE.Vector3());
 if(!hold.point){
   const dir=new THREE.Vector3(...(hold.dir||[0,0,1])).normalize();
   const offset=new THREE.Vector3(...hold.contact).sub(live).clampLength(0,.14);
   hold.point=live.clone().add(offset).addScaledVector(dir,-.025);
   hold.back=arm.getWorldPosition(new THREE.Vector3()).sub(hold.point).normalize();
 }
 const target=hold.point.clone();
 const release=clamp((age-.11)/.08,0,1);
 target.lerp(live,release*release*(3-2*release));
 solveTwoBone(arm,fore,hand,target,a.group.getWorldDirection(new THREE.Vector3()));
 alignWrists(a);
}
function compressDefender(actor,fighter){
  const hold=fighter.guardCompression;if(!hold)return;
  const age=(performance.now()-hold.start)/1000;
  if(age>.19){fighter.guardCompression=null;return;}
  const side=hold.hand?'right':'left',bone=n=>actor.rig.bones.get(side+n)?.bone;
  const arm=bone('Arm'),fore=bone('ForeArm'),hand=bone('Hand');
  if(!arm||!fore||!hand)return;
  const at=b=>b.getWorldPosition(new THREE.Vector3());
  const upper=at(fore).sub(at(arm)).normalize(),lower=at(hand).sub(at(fore)).normalize();
  let axis=lower.clone().cross(upper);
  if(axis.lengthSq()<1e-6)axis=actor.group.getWorldDirection(new THREE.Vector3()).cross(lower);
  axis.normalize().applyQuaternion(fore.parent.getWorldQuaternion(new THREE.Quaternion()).invert());
  const envelope=1-clamp((age-.11)/.08,0,1);
  fore.quaternion.premultiply(new THREE.Quaternion().setFromAxisAngle(axis,THREE.MathUtils.degToRad(7)*envelope));
  fore.updateWorldMatrix(false,true);alignWrists(actor);
}
// Direction-only arm retargeting on cartoon proportions (wide shoulders, short
// arms, big head) spreads a tight guard ~2x wider. Re-place each glove where
// the player's wrist is relative to their shoulders/head, rescaled per axis to
// the avatar (lateral by shoulder width, height/depth by arm or head size).
function alignHandsToBody(a, pose) {
  if (!validPose(pose)) return;
  const V = (p) => new THREE.Vector3(...p);
  const bone = (n) => a.rig.bones.get(n)?.bone;
  const local = (b) => a.group.worldToLocal(b.getWorldPosition(new THREE.Vector3()));
  const sides = ["left", "right"].map((s) => ({ arm: bone(s + "Arm"), fore: bone(s + "ForeArm"), hand: bone(s + "Hand") }));
  const head = bone("head");
  if (!head || sides.some((s) => !s.arm || !s.fore || !s.hand)) return;
  const nS = [V(pose[8]), V(pose[9])], nCenter = nS[0].clone().add(nS[1]).multiplyScalar(0.5);
  const nWidth = nS[0].distanceTo(nS[1]);
  const nArm = [0, 1].map((h) => V(pose[8 + h]).distanceTo(V(pose[10 + h])) + V(pose[10 + h]).distanceTo(V(pose[12 + h])));
  const nHead = pose[15][1] - nCenter.y;
  const aS = sides.map((s) => local(s.arm)), aCenter = aS[0].clone().add(aS[1]).multiplyScalar(0.5);
  const aWidth = aS[0].distanceTo(aS[1]);
  const aArm = sides.map((s) => local(s.arm).distanceTo(local(s.fore)) + local(s.fore).distanceTo(local(s.hand)));
  const headCenter = a.headSurface ? a.group.worldToLocal(head.localToWorld(a.headSurface.center.clone())) : local(head);
  const aHead = headCenter.y - aCenter.y;
  if (nWidth < 0.15 || nHead < 0.1 || aWidth < 0.05 || aHead < 0.05) return;
  sides.forEach((s, h) => {
    if (nArm[h] < 0.2) return;
    const d = V(pose[12 + h]).sub(nCenter), armScale = aArm[h] / nArm[h];
    const target = new THREE.Vector3(d.x * (aWidth / nWidth), d.y * (d.y > 0 ? aHead / nHead : armScale), d.z * armScale).add(aCenter);

    solveTwoBone(s.arm, s.fore, s.hand, a.group.localToWorld(target), a.group.getWorldDirection(new THREE.Vector3()));

    s.hand.updateWorldMatrix(false, true);
  });
  alignWrists(a);
}
function renderActor(i, now, dt = 0, fxDt = 0) {
  const a = actors[i],
    f = fighters[i];
  if (!a) return;
  const knockedOut=ko?.victim===i && !!a.knockout;
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
  // Hands, shoulders and facial references use the newest inference frame; buffering this fast
  // motion added a full inference interval before the quaternion filter.
  if (display.pose !== f.pose) {
    for (let j = 8; j <= 13; j++) display.pose[j] = f.pose[j].slice();
    display.aux ||= {};
    // Missing facial references are missing now, even if the buffered pose
    // still has eyes from before the opponent covered their face.
    for (const key of ['head', 'neck', 'jaw', 'left_eye', 'right_eye', 'left_ear', 'right_ear', 'nose'])
      delete display.aux[key];
    for (const [key, value] of Object.entries(f.aux || {})) {
      if (
        /^(left|right)_(collar|shoulder|elbow|wrist|hand|pinky|index|thumb|middle)/.test(
          key,
        ) || /^(head|neck|jaw|left_eye|right_eye|left_ear|right_ear|nose)$/.test(key)
      )
        display.aux[key] = value?.clone?.() || value;
    }
  }
  if (!knockedOut) {
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
      // groundSoles owns the floor; a second planter feeds back through the group offset.
      plantGround: false,
      groundY: a.groundY ?? 0,
      timestampMs: smooth === 0 ? null : now,
      sampleTimestampMs: f.poseTimestamp ?? now,
      presentationTimestampMs: now,
      headCalibrationKey: i === self
        ? (cameraOn && f.tracking ? "webcam" : "preview")
        : (online ? "peer" : "sparring"),
      useWitness: true,
    });
    debugRecorder.stage(i, 'retarget', a, display.pose);
    alignHandsToBody(a, display.pose);
    debugRecorder.stage(i, 'handAlignment', a);
    applyImpactReaction(a, f.reaction, vclock);
  }
  a.group.position.set(f.x, 0.026, f.z);
  a.group.rotation.y = f.yaw;
  const tsec = vclock / 1000;
  if (knockedOut) {
    a.knockout.update(Math.max(0,(vclock-ko.vstart)/1000),fxDt);
  } else {
    a.group.rotation.x = f.dizzy > 0 ? Math.sin(tsec * 8.4) * 0.018 : 0;
    a.group.rotation.z = f.dizzy > 0 ? Math.sin(tsec * 4.2) * 0.05 : f.stun > 0 ? Math.sin(tsec * 26) * 0.025 : 0;
    groundSoles(a,dt);
  }
  debugRecorder.stage(i, 'feetAndReaction', a);
  if (!knockedOut) {
    applyBlockHold(i);
    compressDefender(a,f);
    // Alignment is unconditional after trunk reactions and group rotation; even
    // unusual captured shoulder/head proportions must keep a straight wrist.
    alignWrists(a);
    debugRecorder.stage(i, 'blockHold', a);
    const contactKey = i === self ? (cameraOn && f.tracking ? 'webcam' : 'preview') : (online ? 'peer' : 'sparring');
    if (a.guardContact.trackingKey !== contactKey) { a.guardContact.reset(); a.guardContact.trackingKey = contactKey; }
    // Recompute the support after each wrist rotation; the final visible glove
    // must satisfy the face constraint, not only its pre-IK orientation.
    for(let pass=0;pass<4;pass++)a.guardContact.apply(a, now);
  }
  debugRecorder.stage(i, 'selfContact', a);
  const localFirst = active && first && i === self;
  a.clip.active.value = localFirst ? 1 : 0;
  const headPosition = a.rig.bones.get("head").bone.getWorldPosition(new THREE.Vector3());
  a.clip.head.value.copy(headPosition);
  a.flash.value = a.flashPeak * Math.max(0, 1 - (vclock - a.flashStart) / 110);
  const headBone = a.rig.bones.get("head").bone;
  for (let k = 0; k < 4; k++) {
    const b = bruises[i][k];
    if (b) {
      const w = headBone.localToWorld(b.local.clone());
      a.bruise.value[k].set(w.x, w.y, w.z, b.w);
    } else a.bruise.value[k].set(0, -10, 0, 0);
  }
  stars[i].update(headPosition, (f.dizzy > 0 || ko?.victim === i) && !localFirst, tsec, fxDt);
  hitboxes[i] = meshHitBox(i);
  // Glove-width motion wake; a fast strike during the stun window sheds embers.
  const opponentDazed = fighters[1 - i].dizzy > 0;
  ["leftHand", "rightHand"].forEach((name, h) => {
    const bone = a.rig.bones.get(name)?.bone;
    if (!bone) return;
    const p = hitboxes[i]?.gloves[h] ? new THREE.Vector3(...hitboxes[i].gloves[h]) : bone.getWorldPosition(new THREE.Vector3());
    const prev = handPrevious[i][h];
    const speed = prev && dt > 0 ? p.distanceTo(prev) / dt : 0;
    const velocity = prev && dt > 0 ? p.clone().sub(prev).divideScalar(dt) : new THREE.Vector3();
    handPrevious[i][h] = p.clone();
    const finisher = opponentDazed && speed > 2.4 && speed < 14;
    // NLF under-reads glove speed ~2-3x, so a detected punch also lights the trail.
    const punch = f.attacks?.find((x) => x.hand === h && now - x.start < 320);
    const force = punch ? clamp((punch.forceN || 0) / PUNCH.tierScaleN, 0.25, 1) : 0;
    const fast = speed > 2 && speed < 15 ? clamp((speed - 2) / 3, 0.4, 0.9) : 0;
    trails[i][h].update(
      p,
      finisher ? 1 : Math.max(force, fast),
      finisher ? "#ff9b0a" : CORNER_COLORS[i],
      (finisher ? 0.14 : 0.095 + 0.035 * Math.max(force, fast)) * (localFirst ? 0.85 : 1),
      camera,
      fxDt,
    );
    fx.motion(p, velocity, speed, finisher, i * 2 + h, fxDt);
  });
  const hide = false;
  a.root.traverse((n) => {
    if (!n.isMesh) return;
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
  debugRecorder.beginFrame(now);
  const dt = clamp((now - last) / 1000, 0, 0.05);
  last = now;
  const frozen = now < hitstopUntil;
  const timeScale = frozen ? 0.12 : now < slowmoUntil ? 0.35 : 1;
  const fxDt = dt * timeScale;
  vclock += fxDt * 1000;
  // The panel tolerates short NLF gaps; the fight itself still pauses after 500 ms.
  document.body.classList.toggle(
    "pose-active",
    active && cameraOn && fighters[self].tracking && now - lastPoseTime < 1500,
  );
  sound.update(dt);
  acc += dt;
  while (acc >= 1 / 60) {
    simulate(1 / 60, now);
    acc -= 1 / 60;
  }
  // Final results stay authoritative while the guest repairs missed history.
  // Ending simulation must not also end journal delivery midway through KO.
  if ((active || (finalResult&&!terminalSynced)) && online && ready && now - sendTime > 33) {
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
        radial: fighters[self].radial,
        attacks: fighters[self].attacks.map(a=>({hand:a.hand,id:a.id,speed:a.stroke?.speed||a.speed||0,forceN:a.stroke?.forceN||a.forceN||0})),
        journalRequest:fighters.map(f=>{for(let i=0;i<f.journal.entries.length;i++)if(!f.journal.entries[i])return i;return f.journal.entries.length;}),
        resultAck:!!finalResult,
      });
    sendTime = now;
  }
  // Hit-stop: both fighters hold their pose for a few frames on impact.
  if (!frozen) {
    const idle = fighters[self];
    if (!active && !ko && lobbyLoop && !(cameraOn && idle.tracking)) {
      const frame = lobbyLoop.frames[Math.floor(now / 1000 * lobbyLoop.fps) % lobbyLoop.frames.length];
      idle.pose = frame.pose.map((v) => v.slice());
      idle.aux = reviveAux({ kind: 'smpl', ...frame.aux });
      idle.poseTimestamp = now;
    }
    for (let i = 0; i < 2; i++) renderActor(i, now, dt, fxDt);
    if(active)for(let pass=0;pass<3;pass++)separateBodies();
  }
  fx.update(frozen ? dt * 0.5 : fxDt);
  flashes.update(dt, 0.35 + sound.excitement * 4);
  arena.update(vclock / 1000, sound.excitement);
  const clockText =
    String(Math.floor(Math.max(0, clock) / 60)).padStart(2, "0") +
    ":" +
    String(Math.floor(Math.max(0, clock) % 60)).padStart(2, "0");
  arena.drawBoard({
    title: active || ko ? "ROUND " + round : "HEAVY HANDS",
    timer: active || ko ? clockText : "VS",
    hp: [fighters[0].hp, fighters[1].hp],
    names: [0, 1].map((i) => (FIGHTER_INFO[fighters[i].avatarId] || ["?"])[0]),
  });
  actors.forEach(a=>{if(a)a.group.visible=true;});
  const cinematic = ko && !$("result").open;
  document.body.classList.toggle("cinematic", !!ko);
  const lobby = !active && !ko;
  if (lobby && camera.view?.enabled) camera.clearViewOffset();
  else if (camera.view?.enabled) camera.clearViewOffset();
  if (cinematic) {
    // KO replay: slow side-on orbit framing the fall line.
    const loser = ko.victim ?? 1 - self, winner = 1 - loser;
    const away = new THREE.Vector3(fighters[loser].x - fighters[winner].x, 0, fighters[loser].z - fighters[winner].z).normalize();
    const focus = new THREE.Vector3(fighters[loser].x, 0, fighters[loser].z).addScaledVector(away, ko.victim === null ? -0.6 : 0.35);
    const angle = Math.atan2(away.x, away.z) + Math.PI / 2 + (performance.now() - ko.start) * 0.00012;
    targetCamera.set(focus.x + Math.sin(angle) * 2.3, 1.45, focus.z + Math.cos(angle) * 2.3);
    // Stay inside the ropes so they never fill the frame.
    targetCamera.x = clamp(targetCamera.x, -2.7, 2.7);
    targetCamera.z = clamp(targetCamera.z, -2.7, 2.7);
    camera.position.lerp(targetCamera, 1 - Math.exp(-dt * 3.5));
    camera.lookAt(focus.x, 0.6, focus.z);
    if (!ko.shown && performance.now() - ko.start > ko.delay) {
      ko.shown = true;
      sound.setMusicMode("result");
      if(finalResult?.ko)sound.say(["ko_it_s_over","ko_finished"],90);
      $("result").showModal();
    }
  } else if (active) {
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
      // Over the right shoulder: the old straight-behind view hid the opponent.
      const right = new THREE.Vector3(-forward.z, 0, forward.x);
      targetCamera.set(a.x, 3.0, a.z).addScaledVector(forward, -2.9).addScaledVector(right, 1.45);
      targetLook.set(a.x + (b.x - a.x) * 0.85, 1.2, a.z + (b.z - a.z) * 0.85);
    }
    camera.position.copy(targetCamera);
    camera.lookAt(targetLook);
  } else if (!$("result").open) {
    const a=fighters[self],angle=Math.sin(now*.00012)*.13;
    targetCamera.set(a.x+Math.sin(angle)*3.9,1.7,a.z+Math.cos(angle)*3.9);
    camera.position.lerp(targetCamera,.06);
    camera.lookAt(a.x, .8, a.z);
    actors[1-self].group.visible=false;
  }
  const kick = shake.apply(camera, now / 1000, dt, first && active ? 0.035 : 0.14);
  const punchIn = punchZoom.amount * Math.exp(-Math.max(0, now - punchZoom.start) / 120);
  const fov = (first && active ? 90 : 48) + (first && active ? kick * 0.4 : kick) - punchIn;
  if (Math.abs(camera.fov - fov) > 0.01) {
    camera.fov = fov;
    camera.updateProjectionMatrix();
  }
  eyeFill.visible = active && first;
  eyeFill.position.copy(camera.position).add(new THREE.Vector3(0, 0.18, 0));
  if (now > messageUntil) $("combatMessage").textContent = "";
  if (now > bannerUntil) $("banner").classList.remove("show");
  $("timer").textContent = clockText;
  $("roundLabel").textContent = "ROUND " + round + " / 3";
  const urgent = active && clock <= 10;
  $("timer").classList.toggle("urgent", urgent);
  if (urgent && Math.ceil(clock) !== lastTick) {
    lastTick = Math.ceil(clock);
    sound.tick(clock <= 5);
  }
  const me = fighters[self];
  // Music reacts to your state: underwater when dazed, a bit dull on low HP,
  // louder when the opponent is dazed and the finish is on.
  sound.setState({
    muffle: active ? (me.dizzy > 0 ? 1 : me.hp <= 25 ? 0.3 : 0) : 0,
    wobble: active && me.dizzy > 0,
    hype: active && fighters[1 - self].dizzy > 0,
    urgent,
  });
  $("soundHint").hidden = active || sound.musicPlaying();
  $("soundHint").textContent = t(sound.enabled ? "soundOn" : "soundOff");
  document.body.classList.toggle("dazed", active && me.dizzy > 0);
  document.body.classList.toggle("low-hp", active && me.hp <= 25);
  if (active && me.hp <= 25 && now > heartbeatAt) {
    heartbeatAt = now + 900;
    sound.heartbeat();
  }
  const cards = $("hud").querySelectorAll(".fighter");
  for (let i = 0; i < 2; i++) {
    const f = fighters[i === 0 ? self : 1 - self];
    $("hp" + i).style.width = f.hp + "%";
    $("hpGhost" + i).style.width = f.hp + "%";
    cards[i].classList.toggle("low", f.hp <= 25);
    const [state, label] =
      f.dizzy > 0 ? ["dizzy", "ROCKED"]
      : f.recoil > 0 ? ["open", "OPEN"]
      : f.weakened > 0 ? ["weak", "WEAKENED"]
      : f.stun > 0 ? ["stun", "STUNNED"]
      : guarded(f.pose) ? ["guard", "GUARD"]
      : ["ready", "READY"];
    $("stun" + i).textContent = label;
    $("stun" + i).dataset.state = state;
    if (now - powerShownAt[i] > 1100) $("pow" + i).style.width = "0%";
  }
  renderer.render(scene, camera);
  voiceCaption.update();
  debugRecorder.capture(now);
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
// Project conservative bounds of the deformed native meshes, including gloves
// crossing the near plane. If no edge is free, omit the caption.
const voiceCaption=new VoiceCaption($('voiceCaption'),()=>{
 const boxes=[];
 for(const a of actors){
  if(!a)continue;
  boxes.push(...characterScreenRegions(a,camera,innerWidth,innerHeight));
 }
 for(const selector of ['header','#hud','#guide','footer','#banner','#combatMessage']){
  for(const el of document.querySelectorAll(selector)){
   if(el.hidden || getComputedStyle(el).opacity==='0' || (['banner','combatMessage'].includes(el.id)&&!el.textContent))continue;
   const r=el.getBoundingClientRect();if(r.width&&r.height)boxes.push({x:r.x,y:r.y,width:r.width,height:r.height});
  }
 }
 return boxes;
},()=>!!(active||ko)&&!document.querySelector('dialog[open]'));
sound.onVoice=line=>line?voiceCaption.show(line):voiceCaption.clear();
requestAnimationFrame(frame);
window.cornerDebug = {
  reviewPose: (pose) => {
    cameraOn = true;
    trackingKey="tracking";
    lastPoseTime = performance.now();
    fighters[self].pose = pose;
    fighters[self].poseTimestamp = performance.now();
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
  reviewEffect: (e) =>
    impact(e.pos ?? worldPoint(fighters[e.victim], fighters[e.victim].pose[e.head === false ? 7 : 15]), !!e.blocked, e),
  finish,
  camera,
  scene,
  renderer,
  vfx: { fx, trails, stars },
  journal: () => fighters[self].journal,
  peak:()=>({current:peakRecord,previous:previousPeak}),
  separateBodies,
  presentation: () => ({ vclock, ko, hitstopUntil, slowmoUntil, bruises, effect, hitboxes }),
  frame,
  paused: false,
  snapCamera: false,
  enter,
  exit,
  notify,
  net,
  sparringMotion: () => ({ loaded: !!sparringLibrary, clips: sparringLibrary?.clips.map(c => ({ id: c.id, hand: c.hand, duration: c.duration })) || [] }),
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
const debugRecorder = new BoxingDebugRecorder({
  button: $('debugRecord'), status: $('debugRecordStatus'), notify,
  getVideo: () => $('tracker').contentWindow.cornerTracking?.video || $('preview'),
  getBridge: () => $('tracker').contentWindow.cornerTracking,
  getContext: () => ({ renderer, camera, actors,
    state: { active, online, self, ready, clock, round, smooth, first, cameraOn,
      trackingStatus: $('trackingStatus').textContent, lastPoseAbsoluteMs: performance.timeOrigin + lastPoseTime,
      vclock, hitstopUntil, slowmoUntil, ko, depth: $('depth').checked, artStyle: $('artStyle').value,
      venue: $('venue').value, fxShake: $('fxShake').checked, renderCalls: renderer.info.render.calls },
    fighters: fighters.map(f => ({ avatarId: f.avatarId, x: f.x, z: f.z, yaw: f.yaw, hp: f.hp,
      pose: f.pose.map(p => p.slice()), aux: Object.fromEntries(Object.entries(f.aux || {}).map(([k,v])=>[k,v?.toArray?.() || v])),
      lateralTarget: f.lateralTarget, lateralApplied: f.lateralApplied, radialTarget: f.radialTarget, radialApplied: f.radialApplied,
      stun: f.stun, dizzy: f.dizzy, recoil: f.recoil, weakened: f.weakened, blockHold: f.blockHold, reaction: f.reaction })) }),
});
window.cornerDebug.recorder = debugRecorder;
$("train").addEventListener("click", () => {
  finalResult = null;
});
$("join").addEventListener("click", () => {
  finalResult = null;
});
