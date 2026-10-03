// Fight-night arena: graphite surfaces, electric corners and warm championship gold.
import * as THREE from "three";
import { toon, INK } from "/static/boxing_fx.js";

export const VENUES = {
  night: {
    label: "Night",
    sky: ["#03050a", "#091324", "#17324c"],
    fog: "#080e1b",
    hemi: ["#e5efff", "#151c29", 1.15],
    exposure: 1.0,
    canvas: "#142631",
  },
  dawn: {
    label: "Dawn",
    sky: ["#081222", "#753222", "#e86a21"],
    fog: "#33241f",
    hemi: ["#fff1dc", "#202635", 1.2],
    exposure: 1.08,
    canvas: "#2a3438",
  },
};

function canvas(w, h, draw) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  draw(c.getContext("2d"), w, h);
  return { texture: t, ctx: c.getContext("2d"), canvas: c };
}
function stroked(ctx, text, x, y, fill, stroke, width) {
  ctx.lineJoin = "round";
  ctx.lineWidth = width;
  ctx.strokeStyle = stroke;
  if (width > 0) ctx.strokeText(text, x, y);
  ctx.fillStyle = fill;
  ctx.fillText(text, x, y);
}
function ringCanvasTexture(base) {
  return canvas(1024, 1024, (x, s) => {
    x.fillStyle = base;
    x.fillRect(0, 0, s, s);
    let seed = 11;
    for (let y = 0; y < s; y += 3)
      for (let i = 0; i < s; i += 3) {
        seed = (seed * 16807) % 2147483647;
        x.fillStyle = "rgba(40,30,90," + (seed % 100) / 6000 + ")";
        x.fillRect(i, y, 2, 2);
      }
    // Corner triangles: blue (player) and red (opponent) corners.
    const corner = (cx, cy, dx, dy, color) => {
      x.beginPath();
      x.moveTo(cx, cy);
      x.lineTo(cx + dx * 150, cy);
      x.lineTo(cx, cy + dy * 150);
      x.closePath();
      x.fillStyle = color;
      x.fill();
      x.lineWidth = 6;
      x.strokeStyle = INK.getStyle();
      x.stroke();
    };
    corner(40, 40, 1, 1, "#009dff");
    corner(s - 40, s - 40, -1, -1, "#ef233c");
    x.lineWidth = 8;
    x.strokeStyle = "#131d2c";
    x.strokeRect(40, 40, s - 80, s - 80);
    x.lineWidth = 3;
    x.strokeRect(58, 58, s - 116, s - 116);
    // Center badge.
    x.save();
    x.translate(s / 2, s / 2);
    x.beginPath();
    x.arc(0, 0, 205, 0, Math.PI * 2);
    x.fillStyle = "rgba(4,10,18,.22)";
    x.fill();
    x.lineWidth = 3;
    x.strokeStyle = "rgba(119,165,190,.34)";
    x.stroke();
    x.rotate(-Math.PI / 2);
    x.textAlign = "center";
    x.font = "900 86px 'Barlow Condensed', Impact, sans-serif";
    stroked(x, "HEAVY HANDS", 0, 40, "rgba(255,178,26,.95)", "rgba(4,10,18,.75)", 2);
    x.font = "800 30px Inter, sans-serif";
    x.fillStyle = "rgba(161,188,206,.7)";
    x.fillText("", 0, 96);
    x.restore();
  });
}
function bannerTexture(text, bg, fg) {
  return canvas(1024, 160, (x, w, h) => {
    x.fillStyle = bg;
    x.fillRect(0, 0, w, h);
    x.fillStyle = "rgba(255,178,26,.035)";
    for (let i = -h; i < w; i += 46) {
      x.beginPath();
      x.moveTo(i, h);
      x.lineTo(i + 22, h);
      x.lineTo(i + 22 + h, 0);
      x.lineTo(i + h, 0);
      x.fill();
    }
    x.textAlign = "center";
    x.font = "900 86px 'Barlow Condensed', Impact, sans-serif";
    stroked(x, text, w / 2, 110, fg, INK.getStyle(), 3);
  }).texture;
}

export function buildArena(scene) {
  const arena = new THREE.Group();
  scene.add(arena);
  const add = (mesh, line = 0) => {
    mesh.castShadow = mesh.receiveShadow = true;
    // No inverted hull: clean silhouettes and one draw per prop.
    arena.add(mesh);
    return mesh;
  };
  const box = (w, h, d, x, y, z, m, line = 0.02) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
    mesh.position.set(x, y, z);
    return add(mesh, line);
  };

  // Gradient dome behind everything, the "arena darkness" with a hot horizon.
  const skyUniforms = {
    top: { value: new THREE.Color() },
    mid: { value: new THREE.Color() },
    horizon: { value: new THREE.Color() },
  };
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(38, 32, 16),
    new THREE.ShaderMaterial({
      side: THREE.BackSide,
      depthWrite: false,
      uniforms: skyUniforms,
      vertexShader: "varying vec3 vDir;void main(){vDir=normalize(position);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}",
      fragmentShader:
        "uniform vec3 top;uniform vec3 mid;uniform vec3 horizon;varying vec3 vDir;void main(){float h=vDir.y;vec3 c=mix(mid,top,smoothstep(0.05,0.6,h));c=mix(horizon,c,smoothstep(-0.04,0.22,h));c=mix(c,top*0.4,smoothstep(-0.05,-0.5,h));gl_FragColor=vec4(c,1.0);\n#include <colorspace_fragment>\n}",
    }),
  );
  sky.renderOrder = -10;
  arena.add(sky);

  const hemi = new THREE.HemisphereLight("#ffffff", "#000000", 1);
  scene.add(hemi);
  const spot = (color, x, y, z, power, shadow = false) => {
    const l = new THREE.SpotLight(color, power, 30, 0.62, 0.55, 1.2);
    l.position.set(x, y, z);
    l.target.position.set(0, 0.9, 0);
    l.castShadow = shadow;
    if (shadow) {
      l.shadow.mapSize.set(2048, 2048);
      l.shadow.normalBias = 0.02;
      l.shadow.bias = -0.0004;
      l.shadow.radius = 2;
    }
    scene.add(l, l.target);
    return l;
  };
  const keyLight = spot("#fff1d6", -3.2, 8.5, 2.6, 85, true);
  spot("#ff243f", 5.5, 5.5, -4.5, 35);
  spot("#008dff", -5.5, 5.5, -4.5, 35);
  spot("#ffffff", 2.5, 8, 4.5, 24);

  // Volumetric-looking cones from the overhead rig (additive, no lighting cost).
  const coneMaterial = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    uniforms: { tint: { value: new THREE.Color("#fff3d1") } },
    vertexShader: "varying float vY;varying vec3 vN;varying vec3 vV;void main(){vY=position.y+0.5;vN=normalize(normalMatrix*normal);vec4 mv=modelViewMatrix*vec4(position,1.0);vV=normalize(-mv.xyz);gl_Position=projectionMatrix*mv;}",
    fragmentShader: "uniform vec3 tint;varying float vY;varying vec3 vN;varying vec3 vV;void main(){float edge=pow(abs(dot(vN,vV)),1.6);gl_FragColor=vec4(tint*pow(vY,1.8)*edge*0.075,1.0);}",
  });
  const lightCones = [];
  for (const [x, z] of [[-2.4, -2.4], [2.4, -2.4], [-2.4, 2.4], [2.4, 2.4]]) {
    const cone = new THREE.Mesh(new THREE.ConeGeometry(1.5, 1, 28, 1, true), coneMaterial);
    const top = new THREE.Vector3(x * 1.25, 8.6, z * 1.25), bottom = new THREE.Vector3(x * 0.25, 0, z * 0.25);
    cone.scale.y = top.distanceTo(bottom);
    cone.position.copy(top).add(bottom).multiplyScalar(0.5);
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), top.clone().sub(bottom).normalize());
    cone.renderOrder = 2;
    arena.add(cone);
    lightCones.push(cone);
  }

  // Floor and stepped stands.
  const floorMat = toon("#080d16");
  box(46, 0.1, 46, 0, -0.75, 0, floorMat, 0);
  const standMat = toon("#111b28");
  for (let row = 0; row < 3; row++)
    for (const s of [-1, 1]) {
      const d = 5.2 + row * 0.95, h = 0.45 + row * 0.24;
      box(13 + row * 2, h, 0.95, 0, -0.7 + h / 2, s * d, standMat, 0.012);
      box(0.95, h, 13 + row * 2, s * d, -0.7 + h / 2, 0, standMat, 0.012);
    }

  // Ring: apron, canvas, posts, pads and sagging ropes.
  const apronMat = toon("#121c2b");
  box(6.9, 0.6, 6.9, 0, -0.37, 0, apronMat, 0.025);
  const venueCanvas = { texture: null };
  const canvasMat = toon("#ffffff", { roughness: .92, metalness: 0 });
  const top = new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.08, 6.6), [
    apronMat, apronMat, canvasMat, apronMat, apronMat, apronMat,
  ]);
  top.position.y = -0.014;
  add(top, 0.018);
  const postMat = toon("#657b8c"), blueMat = toon("#009dff"), redMat = toon("#ef233c"), whiteMat = toon("#d5e3ee");
  for (const x of [-3.12, 3.12])
    for (const z of [-3.12, 3.12]) {
      const post = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.085, 1.66, 14), postMat);
      post.position.set(x, 0.8, z);
      add(post, 0.018);
      const color = x < 0 && z < 0 ? blueMat : x > 0 && z > 0 ? redMat : whiteMat;
      const pad = new THREE.Mesh(new THREE.CapsuleGeometry(0.15, 0.62, 4, 12), color);
      pad.position.set(x, 0.92, z);
      add(pad, 0.02);
    }
  const ropeColors = ["#009dff", "#d5e3ee", "#d5e3ee", "#ef233c"];
  const rope = (a, b, color) => {
    const sag = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5).add(new THREE.Vector3(0, -0.05, 0));
    const curve = new THREE.QuadraticBezierCurve3(a, sag, b);
    const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 24, 0.032, 8), toon(color));
    mesh.castShadow = true;

    arena.add(mesh);
  };
  for (let j = 0; j < 4; j++) {
    const y = 0.45 + j * 0.31;
    for (const s of [-1, 1]) {
      rope(new THREE.Vector3(-3.1, y, s * 3.12), new THREE.Vector3(3.1, y, s * 3.12), ropeColors[j]);
      rope(new THREE.Vector3(s * 3.12, y, -3.1), new THREE.Vector3(s * 3.12, y, 3.1), ropeColors[j]);
    }
  }
  // Apron banners on all four sides.
  const apronBanner = bannerTexture("HEAVY HANDS", "#121c2b", "#ffb21a");
  for (let k = 0; k < 4; k++) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(5.6, 0.48), new THREE.MeshBasicMaterial({ map: apronBanner }));
    const a = (k * Math.PI) / 2;
    p.position.set(Math.sin(a) * 3.462, -0.37, Math.cos(a) * 3.462);
    p.rotation.y = a;
    arena.add(p);
  }
  const trimMaterials = ["#009dff", "#ef233c"].map(color => new THREE.MeshBasicMaterial({ color, toneMapped: false }));
  for (const side of [-1, 1]) {
    box(6.75, .018, .018, 0, -.12, side * 3.458, trimMaterials[side < 0 ? 0 : 1], 0);
    box(.018, .018, 6.75, side * 3.458, -.12, 0, trimMaterials[side < 0 ? 0 : 1], 0);
  }
  // Corner stools and buckets.
  for (const [x, z, m] of [[-3.75, -3.75, blueMat], [3.75, 3.75, redMat]]) {
    const seat = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 0.07, 18), m);
    seat.position.set(x, -0.02, z);
    add(seat, 0.015);
    for (let l = 0; l < 3; l++) {
      const a = (l / 3) * Math.PI * 2;
      const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.66, 6), postMat);
      leg.position.set(x + Math.cos(a) * 0.15, -0.37, z + Math.sin(a) * 0.15);
      add(leg, 0.01);
    }
    const bucket = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.12, 0.3, 14), toon("#ffb21a"));
    bucket.position.set(x + Math.sign(x) * 0.45, -0.55, z - Math.sign(z) * 0.1);
    add(bucket, 0.015);
  }
  // Overhead truss with lamp heads.
  const trussMat = toon("#283543");
  const lampMat = new THREE.MeshBasicMaterial({ color: "#fff3c4" });
  for (const s of [-1, 1]) {
    box(10.4, 0.16, 0.16, 0, 9, s * 5.1, trussMat, 0);
    box(0.16, 0.16, 10.4, s * 5.1, 9, 0, trussMat, 0);
    for (const u of [-3.6, -1.2, 1.2, 3.6]) {
      const lamp = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.22, 0.28, 12), trussMat);
      lamp.position.set(u, 8.82, s * 5.1);
      arena.add(lamp);
      const lens = new THREE.Mesh(new THREE.CircleGeometry(0.19, 16), lampMat);
      lens.rotation.x = Math.PI / 2;
      lens.position.set(u, 8.67, s * 5.1);
      arena.add(lens);
    }
  }

  // Curated spectator palette: dark apparel with saturated team accents.
  const count = 204;
  let activeCount = count, crowdInterval = 1 / 30;
  const bodies = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.155, 0.115, 0.40, 8), toon("#ffffff"), count);
  const heads = new THREE.InstancedMesh(new THREE.SphereGeometry(0.11, 10, 8), toon("#ffffff"), count);
  const arms = new THREE.InstancedMesh(new THREE.CapsuleGeometry(.048, .22, 2, 6), toon('#ffffff'), count * 2);
  const legs = new THREE.InstancedMesh(new THREE.CapsuleGeometry(.056, .24, 2, 6), toon('#0c1420'), count * 2);
  const crowd = [];
  const dummy = new THREE.Object3D();
  const shirts = ["#101a26", "#1b2b3a", "#074b91", "#9e132a", "#202a35", "#966315", "#141e2b", "#243239", "#152333", "#252630", "#192027", "#202d38"];
  const skin = ["#f1c7a5", "#d9a27c", "#a86e4c", "#7a4a2f", "#ffdcc0"];
  for (let i = 0; i < count; i++) {
    const side = i % 4,
      row = Math.floor(i / 68),
      col = Math.floor(i / 4) % 17,
      u = (col - 8) * 0.66 + (row % 2) * 0.33,
      v = 5.2 + row * 0.95;
    const pos = new THREE.Vector3(side < 2 ? u : side === 2 ? v : -v, -0.25 + row * 0.24 + 0.28, side < 2 ? (side === 0 ? v : -v) : u);
    const yaw = Math.atan2(-pos.x, -pos.z);
    crowd.push({ pos, yaw, phase: Math.random() * 10, rate: 5 + Math.random() * 4, energy: 0.4 + Math.random() * 0.6 });
    bodies.setColorAt(i, new THREE.Color(shirts[(i * 7 + Math.floor(i / 11)) % shirts.length]));
    heads.setColorAt(i, new THREE.Color(skin[i % skin.length]));
    const shirt = new THREE.Color(shirts[(i * 7 + Math.floor(i / 11)) % shirts.length]);
    arms.setColorAt(i * 2, shirt); arms.setColorAt(i * 2 + 1, shirt);
    dummy.position.copy(pos);
    dummy.rotation.set(0, yaw, 0);
    dummy.updateMatrix();
    bodies.setMatrixAt(i, dummy.matrix);
  }
  bodies.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  heads.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  arms.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  legs.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  arena.add(bodies, heads, arms, legs);
  const seats = crowd.map((c) => c.pos);

  // Wall scoreboards: one shared canvas, four screens.
  const board = canvas(512, 256, () => {});
  const boardMat = new THREE.MeshBasicMaterial({ map: board.texture, toneMapped: false });
  for (let k = 0; k < 4; k++) {
    const a = (k * Math.PI) / 2;
    const frame = new THREE.Mesh(new THREE.BoxGeometry(3.3, 1.75, 0.2), toon("#131d2c"));
    frame.position.set(Math.sin(a) * -9.2, 4.2, Math.cos(a) * -9.2);
    frame.rotation.y = a;
    add(frame, 0.04);
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(3.05, 1.52), boardMat);
    screen.position.set(0, 0, 0.11);
    frame.add(screen);
  }
  let boardKey = "";
  function drawBoard(state) {
    const key = JSON.stringify(state);
    if (key === boardKey) return;
    boardKey = key;
    const x = board.ctx, w = 512, h = 256;
    const g = x.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, "#131d2c");
    g.addColorStop(1, "#070b12");
    x.fillStyle = g;
    x.fillRect(0, 0, w, h);
    x.textAlign = "center";
    x.font = "900 34px 'Barlow Condensed', Impact, sans-serif";
    stroked(x, state.title, w / 2, 48, "#ffb21a", INK.getStyle(), 0);
    x.font = "900 74px 'Barlow Condensed', Impact, sans-serif";
    stroked(x, state.timer, w / 2, 140, "#ffffff", INK.getStyle(), 0);
    for (let i = 0; i < 2; i++) {
      const bx = i ? 280 : 32, color = i ? "#ef233c" : "#009dff";
      x.fillStyle = "#080d16";
      x.fillRect(bx, 176, 200, 30);
      x.fillStyle = color;
      const width = (196 * Math.max(0, state.hp[i])) / 100;
      x.fillRect(i ? bx + 2 + 196 - width : bx + 2, 178, width, 26);
      x.lineWidth = 4;
      x.strokeStyle = INK.getStyle();
      x.strokeRect(bx, 176, 200, 30);
      x.font = "800 20px Inter, sans-serif";
      x.fillStyle = "#fff";
      x.textAlign = i ? "right" : "left";
      x.fillText(state.names[i], i ? bx + 200 : bx, 236);
    }
    board.texture.needsUpdate = true;
  }

  function setVenue(name, renderer) {
    const v = VENUES[name] || VENUES.night;
    skyUniforms.top.value.set(v.sky[0]);
    skyUniforms.mid.value.set(v.sky[1]);
    skyUniforms.horizon.value.set(v.sky[2]);
    scene.background = new THREE.Color(v.fog);
    scene.fog = new THREE.FogExp2(v.fog, 0.028);
    hemi.color.set(v.hemi[0]);
    hemi.groundColor.set(v.hemi[1]);
    hemi.intensity = v.hemi[2];
    renderer.toneMappingExposure = v.exposure;
    venueCanvas.texture?.dispose();
    venueCanvas.texture = ringCanvasTexture(v.canvas).texture;
    canvasMat.map = venueCanvas.texture;
    canvasMat.needsUpdate = true;
  }
  sky.material.fog = false;
  coneMaterial.fog = false;

  let lastCrowdUpdate = -Infinity;
  function update(t, excitement) {
    if (t - lastCrowdUpdate < crowdInterval && t >= lastCrowdUpdate) return;
    lastCrowdUpdate = t;
    // Seated sway at rest; standing jumps when the crowd erupts.
    for (let i = 0; i < activeCount; i++) {
      const c = crowd[i];
      const hype = Math.max(0, excitement * 1.4 - (1 - c.energy) * 0.5);
      const bounce = Math.abs(Math.sin(t * c.rate + c.phase)) * (0.02 + hype * 0.16);
      dummy.position.copy(c.pos);
      dummy.position.y += bounce;
      dummy.rotation.set(0, c.yaw, Math.sin(t * 1.3 + c.phase) * 0.05);
      dummy.updateMatrix();
      bodies.setMatrixAt(i, dummy.matrix);
      dummy.position.y += 0.33;
      dummy.updateMatrix();
      heads.setMatrixAt(i, dummy.matrix);
      for (let side = 0; side < 2; side++) {
        const sign = side ? 1 : -1;
        dummy.position.copy(c.pos);
        dummy.position.x += Math.cos(c.yaw) * sign * .185;
        dummy.position.z -= Math.sin(c.yaw) * sign * .185;
        dummy.position.y += bounce - .025 + hype * .12;
        dummy.rotation.set(0, c.yaw, sign * (.12 + hype * .6));
        dummy.updateMatrix(); arms.setMatrixAt(i * 2 + side, dummy.matrix);
        dummy.position.copy(c.pos);
        dummy.position.x += Math.cos(c.yaw) * sign * .07;
        dummy.position.z -= Math.sin(c.yaw) * sign * .07;
        dummy.position.y += bounce - .32;
        dummy.rotation.set(0, c.yaw, 0);
        dummy.updateMatrix(); legs.setMatrixAt(i * 2 + side, dummy.matrix);
      }
    }
    bodies.instanceMatrix.needsUpdate = heads.instanceMatrix.needsUpdate = arms.instanceMatrix.needsUpdate = legs.instanceMatrix.needsUpdate = true;
  }
  function setQuality(level) {
    activeCount = level === 'low' ? 68 : level === 'balanced' ? 136 : count;
    crowdInterval = level === 'low' ? 1 / 20 : 1 / 30;
    seats.length = activeCount;
    for (let i = 0; i < activeCount; i++) seats[i] = crowd[i].pos;
    bodies.count = heads.count = activeCount; arms.count = legs.count = activeCount * 2;
    lightCones.forEach(c => c.visible = level !== 'low');
    const shadowSize = level === 'high' ? 2048 : 1024;
    if (keyLight.shadow.mapSize.x !== shadowSize) {
      keyLight.shadow.map?.dispose(); keyLight.shadow.map = null;
      keyLight.shadow.mapSize.set(shadowSize, shadowSize);
    }
    lastCrowdUpdate = -Infinity;
  }
  return { setVenue, setQuality, update, drawBoard, seats };
}
