// Cartoon presentation layer: toon materials, outlines, impact FX, trails,
// dazed stars and camera shake. Nothing here changes combat outcomes.
import * as THREE from "three";

export const INK = new THREE.Color("#170f2e");

let gradient = null;
export function toonGradient() {
  if (gradient) return gradient;
  // Three soft bands: shadow, mid, lit. Linear filtering keeps edges clean.
  const data = new Uint8Array([70, 70, 70, 255, 150, 150, 150, 255, 215, 215, 215, 255, 255, 255, 255, 255]);
  gradient = new THREE.DataTexture(data, 4, 1, THREE.RGBAFormat);
  gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
  gradient.needsUpdate = true;
  return gradient;
}
export const toon = (color, extra = {}) =>
  new THREE.MeshToonMaterial({ color, gradientMap: toonGradient(), ...extra });

// Inverted hull outline for static props.
const hullMaterial = new THREE.MeshBasicMaterial({ color: INK, side: THREE.BackSide });
export function outline(mesh, width = 0.025) {
  const hull = new THREE.Mesh(mesh.geometry, hullMaterial);
  mesh.geometry.computeBoundingBox();
  const size = mesh.geometry.boundingBox.getSize(new THREE.Vector3());
  hull.scale.set(1 + (2 * width) / Math.max(size.x, 1e-3), 1 + (2 * width) / Math.max(size.y, 1e-3), 1 + (2 * width) / Math.max(size.z, 1e-3));
  hull.userData.cornerOutline = true;
  mesh.add(hull);
  return hull;
}

// Converts avatar materials to cel shading while keeping their textures.
export function toonifyAvatar(root) {
  root.traverse((node) => {
    if (!node.isMesh || !node.material) return;
    const convert = (m) => {
      if (!m || m.isMeshToonMaterial) return m;
      const t = new THREE.MeshToonMaterial({
        name: m.name,
        color: m.color?.clone() ?? new THREE.Color("#ffffff"),
        map: m.map ?? null,
        normalMap: m.normalMap ?? null,
        emissive: m.emissive?.clone() ?? new THREE.Color("#000000"),
        emissiveMap: m.emissiveMap ?? null,
        alphaMap: m.alphaMap ?? null,
        alphaTest: m.alphaTest ?? 0,
        transparent: m.transparent,
        opacity: m.opacity,
        side: m.side,
        gradientMap: toonGradient(),
      });
      if (m.normalScale) t.normalScale.copy(m.normalScale);
      m.dispose();
      return t;
    };
    node.material = Array.isArray(node.material) ? node.material.map(convert) : convert(node.material);
  });
}

function canvasTexture(size, draw) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  draw(c.getContext("2d"), size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function starPath(ctx, cx, cy, spikes, outer, inner, jitter = 0, seed = 1) {
  ctx.beginPath();
  for (let i = 0; i < spikes * 2; i++) {
    seed = (seed * 16807) % 2147483647;
    const r = (i % 2 ? inner : outer) * (1 - jitter * ((seed % 1000) / 1000));
    const a = (i / (spikes * 2)) * Math.PI * 2 - Math.PI / 2;
    ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
  }
  ctx.closePath();
}
const textures = {};
function tex(name) {
  if (textures[name]) return textures[name];
  const ink = "#170f2e";
  const make = {
    burst: (x, s) => {
      x.lineJoin = "round";
      starPath(x, s / 2, s / 2, 13, s * 0.47, s * 0.27, 0.22, 7);
      x.fillStyle = "#fff6d8";
      x.strokeStyle = ink;
      x.lineWidth = s * 0.035;
      x.fill();
      x.stroke();
      starPath(x, s / 2, s / 2, 11, s * 0.3, s * 0.17, 0.25, 31);
      x.fillStyle = "#ffd23f";
      x.fill();
      starPath(x, s / 2, s / 2, 9, s * 0.16, s * 0.08, 0.2, 77);
      x.fillStyle = "#ff8a3d";
      x.fill();
    },
    block: (x, s) => {
      x.lineWidth = s * 0.06;
      x.strokeStyle = "#bfe6ff";
      x.beginPath();
      x.arc(s / 2, s / 2, s * 0.36, 0, Math.PI * 2);
      x.stroke();
      x.lineWidth = s * 0.025;
      x.strokeStyle = "#ffffff";
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI * 2;
        x.beginPath();
        x.moveTo(s / 2 + Math.cos(a) * s * 0.18, s / 2 + Math.sin(a) * s * 0.18);
        x.lineTo(s / 2 + Math.cos(a) * s * 0.3, s / 2 + Math.sin(a) * s * 0.3);
        x.stroke();
      }
    },
    lines: (x, s) => {
      x.strokeStyle = "#ffffff";
      x.lineCap = "round";
      for (let i = 0; i < 22; i++) {
        const a = (i / 22) * Math.PI * 2 + (i % 3) * 0.05;
        const r0 = s * (0.28 + (i % 4) * 0.025);
        x.lineWidth = s * (0.012 + (i % 3) * 0.006);
        x.beginPath();
        x.moveTo(s / 2 + Math.cos(a) * r0, s / 2 + Math.sin(a) * r0);
        x.lineTo(s / 2 + Math.cos(a) * s * 0.48, s / 2 + Math.sin(a) * s * 0.48);
        x.stroke();
      }
    },
    star: (x, s) => {
      x.lineJoin = "round";
      starPath(x, s / 2, s / 2, 5, s * 0.44, s * 0.2);
      x.fillStyle = "#ffe14d";
      x.strokeStyle = ink;
      x.lineWidth = s * 0.07;
      x.fill();
      x.stroke();
      x.fillStyle = "#fff9d0";
      x.beginPath();
      x.arc(s * 0.43, s * 0.4, s * 0.06, 0, Math.PI * 2);
      x.fill();
    },
    glow: (x, s) => {
      const g = x.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.2, "rgba(255,255,255,.7)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      x.fillStyle = g;
      x.fillRect(0, 0, s, s);
    },
  }[name];
  textures[name] = canvasTexture(name === "glow" ? 64 : 256, make);
  return textures[name];
}

// Squirrel Eiserloh "trauma" shake: offset = trauma^2 * smooth noise.
export class CameraShake {
  constructor() {
    this.trauma = 0;
    this.kick = 0;
    this.scale = 1;
  }
  add(amount, kick = 0) {
    this.trauma = Math.min(1, this.trauma + amount * this.scale);
    this.kick = Math.max(this.kick, kick * this.scale);
  }
  apply(camera, t, dt, amplitude) {
    this.trauma = Math.max(0, this.trauma - dt * 1.7);
    this.kick = Math.max(0, this.kick - dt * 20);
    const s = this.trauma * this.trauma;
    if (s > 0.0001) {
      const n = (f, p) => Math.sin(t * f + p) * 0.6 + Math.sin(t * f * 2.31 + p * 1.7) * 0.4;
      camera.position.x += n(37, 1.3) * s * amplitude;
      camera.position.y += n(41, 4.1) * s * amplitude * 0.7;
      camera.position.z += n(33, 2.2) * s * amplitude;
      camera.rotateZ(n(29, 0.4) * s * amplitude * 0.35);
    }
    return this.kick;
  }
}

class Pool {
  constructor(group) {
    this.group = group;
    this.items = [];
  }
  sprite(texture, color, blending = THREE.NormalBlending) {
    const mesh = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: texture, color, transparent: true, depthWrite: false, blending }),
    );
    this.group.add(mesh);
    return mesh;
  }
}

export class GloveTrail {
  constructor(scene, samples = 18) {
    this.n = samples;
    this.points = [];
    this.intensity = 0;
    const geometry = new THREE.BufferGeometry();
    this.position = new Float32Array(samples * 2 * 3);
    this.alpha = new Float32Array(samples * 2);
    geometry.setAttribute("position", new THREE.BufferAttribute(this.position, 3));
    geometry.setAttribute("alpha", new THREE.BufferAttribute(this.alpha, 1));
    const index = [];
    for (let i = 0; i < samples - 1; i++) {
      const a = i * 2;
      index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
    geometry.setIndex(index);
    this.color = { value: new THREE.Color("#ffd23f") };
    this.mesh = new THREE.Mesh(
      geometry,
      new THREE.ShaderMaterial({
        uniforms: { color: this.color },
        vertexShader:
          "attribute float alpha;varying float vAlpha;void main(){vAlpha=alpha;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}",
        fragmentShader:
          "uniform vec3 color;varying float vAlpha;void main(){gl_FragColor=vec4(color*(0.75+vAlpha*0.6),vAlpha);}",
        transparent: true,
        depthWrite: false,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
      }),
    );
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 3;
    scene.add(this.mesh);
  }
  reset() {
    this.points = [];
    this.intensity = 0;
    this.mesh.visible = false;
  }
  update(point, target, color, width, camera, dt) {
    this.intensity += (target - this.intensity) * (1 - Math.exp(-dt * (target > this.intensity ? 30 : 7)));
    const last = this.points[0];
    if (last && last.distanceTo(point) > 0.6) this.points = [];
    this.points.unshift(point.clone());
    if (this.points.length > this.n) this.points.length = this.n;
    this.mesh.visible = this.intensity > 0.02 && this.points.length > 2;
    if (!this.mesh.visible) return;
    this.color.value.set(color);
    const view = new THREE.Vector3(),
      side = new THREE.Vector3(),
      tangent = new THREE.Vector3();
    for (let i = 0; i < this.n; i++) {
      const p = this.points[Math.min(i, this.points.length - 1)];
      const q = this.points[Math.min(i + 1, this.points.length - 1)];
      tangent.subVectors(p, q);
      if (tangent.lengthSq() < 1e-8) tangent.set(0, 1, 0);
      view.subVectors(camera.position, p);
      side.crossVectors(tangent, view).normalize();
      const u = i / (this.n - 1),
        w = width * (1 - u) * (1 - u * 0.3);
      const valid = i < this.points.length ? 1 : 0;
      this.position.set([p.x + side.x * w, p.y + side.y * w, p.z + side.z * w], i * 6);
      this.position.set([p.x - side.x * w, p.y - side.y * w, p.z - side.z * w], i * 6 + 3);
      const a = this.intensity * (1 - u) * (1 - u) * valid;
      this.alpha[i * 2] = this.alpha[i * 2 + 1] = a;
    }
    this.mesh.geometry.attributes.position.needsUpdate = true;
    this.mesh.geometry.attributes.alpha.needsUpdate = true;
  }
}

export class ImpactFx {
  constructor(scene) {
    this.group = new THREE.Group();
    this.group.renderOrder = 4;
    scene.add(this.group);
    this.pool = new Pool(this.group);
    this.live = [];
    // Sweat droplets with gravity, shared instanced mesh.
    this.dropCount = 96;
    this.drops = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.012, 6, 4),
      new THREE.MeshBasicMaterial({ color: "#d9f3ff", transparent: true, opacity: 0.9 }),
      this.dropCount,
    );
    this.drops.frustumCulled = false;
    this.dropState = Array.from({ length: this.dropCount }, () => ({ life: 0, p: new THREE.Vector3(), v: new THREE.Vector3(), s: 1 }));
    this.dropCursor = 0;
    this.dummy = new THREE.Object3D();
    scene.add(this.drops);
  }
  spawn(texture, pos, size, life, opts = {}) {
    const mesh = this.pool.sprite(tex(texture), opts.color ?? "#ffffff", opts.blending);
    mesh.position.copy(pos);
    mesh.material.rotation = opts.rotation ?? Math.random() * Math.PI * 2;
    mesh.renderOrder = 5;
    this.live.push({ mesh, age: 0, life, size, grow: opts.grow ?? 1.2, pop: opts.pop ?? 0.08, spin: opts.spin ?? 0, v: opts.velocity ?? null });
  }
  hit(position, kind, power, direction) {
    const pos = new THREE.Vector3(...position);
    if(power<.33 && kind!=='arm' && kind!=='guard'){
      this.spawn('glow',pos,.07+power*.16,.12,{color:'#dce8ee',blending:THREE.AdditiveBlending});
      return;
    }
    if (kind === "arm" || kind === "guard") {
      this.spawn("block", pos, 0.26 + power * 0.08, 0.22, { color: "#cfeaff", grow: 1.5, pop: 0.05 });
      this.spawn("glow", pos, 0.22, 0.12, { color: "#9fd6ff", blending: THREE.AdditiveBlending });
      return;
    }
    const big = kind === "chin" || kind === "finisher" || kind === "ko";
    const size = (big ? 0.48 : 0.3) + power * 0.16;
    this.spawn("burst", pos, size, big ? 0.32 : 0.24, { grow: 1.15, pop: 0.06 });
    this.spawn("lines", pos, size * 1.6, big ? 0.26 : 0.18, { grow: 1.6, pop: 0.03, color: big ? "#ffe9a8" : "#ffffff" });
    this.spawn("glow", pos, size * 0.9, 0.12, { color: big ? "#ffcf6b" : "#ffffff", blending: THREE.AdditiveBlending });
    this.sweat(pos, direction, big ? 18 : kind === "body" ? 5 : 10, power);
  }
  sweat(origin, direction, count, power) {
    const dir = direction ? new THREE.Vector3(...direction).normalize() : new THREE.Vector3(0, 0, 1);
    for (let i = 0; i < count; i++) {
      const d = this.dropState[this.dropCursor];
      this.dropCursor = (this.dropCursor + 1) % this.dropCount;
      d.life = 0.55 + Math.random() * 0.35;
      d.p.copy(origin);
      d.v
        .copy(dir)
        .multiplyScalar(1.2 + power * 1.6 + Math.random() * 0.8)
        .add(new THREE.Vector3((Math.random() - 0.5) * 1.6, 0.6 + Math.random() * 1.3, (Math.random() - 0.5) * 1.6));
      d.s = 0.6 + Math.random() * 0.9;
    }
  }
  update(dt) {
    for (const s of this.live) {
      s.age += dt;
      const u = s.age / s.life;
      const pop = Math.min(1, s.age / s.pop);
      const overshoot = pop < 1 ? pop * (1.25 - 0.25 * pop) : 1 + (s.grow - 1) * Math.min(1, (s.age - s.pop) / (s.life - s.pop));
      s.mesh.scale.setScalar(s.size * overshoot);
      s.mesh.material.opacity = u < 0.55 ? 1 : Math.max(0, 1 - (u - 0.55) / 0.45);
      s.mesh.material.rotation += s.spin * dt;
    }
    for (const s of this.live.filter((x) => x.age >= x.life)) {
      this.group.remove(s.mesh);
      s.mesh.material.dispose();
    }
    this.live = this.live.filter((x) => x.age < x.life);
    let any = false;
    for (let i = 0; i < this.dropCount; i++) {
      const d = this.dropState[i];
      if (d.life > 0) {
        any = true;
        d.life -= dt;
        d.v.y -= 9.8 * 0.8 * dt;
        d.v.multiplyScalar(1 - dt * 0.6);
        d.p.addScaledVector(d.v, dt);
        if (d.p.y < 0.035) {
          d.p.y = 0.035;
          d.v.set(0, 0, 0);
        }
      }
      this.dummy.position.copy(d.p);
      const stretch = Math.min(2.4, 1 + d.v.length() * 0.25);
      this.dummy.scale.set(d.s, d.s * stretch, d.s).multiplyScalar(d.life > 0 ? Math.min(1, d.life * 4) : 0);
      if (d.v.lengthSq() > 1e-4) this.dummy.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d.v.clone().normalize());
      this.dummy.updateMatrix();
      this.drops.setMatrixAt(i, this.dummy.matrix);
    }
    this.drops.visible = any;
    this.drops.instanceMatrix.needsUpdate = true;
  }
  clear() {
    for (const s of this.live) {
      this.group.remove(s.mesh);
      s.mesh.material.dispose();
    }
    this.live = [];
    for (const d of this.dropState) d.life = 0;
  }
}

// Classic cartoon daze: stars orbiting over the head.
export class DizzyStars {
  constructor(scene) {
    this.group = new THREE.Group();
    this.stars = Array.from({ length: 5 }, (_, i) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex("star"), transparent: true, depthWrite: false }));
      s.renderOrder = 6;
      this.group.add(s);
      return s;
    });
    this.amount = 0;
    this.group.visible = false;
    scene.add(this.group);
  }
  update(head, active, t, dt) {
    this.amount += ((active ? 1 : 0) - this.amount) * (1 - Math.exp(-dt * (active ? 10 : 5)));
    this.group.visible = this.amount > 0.02 && !!head;
    if (!this.group.visible) return;
    this.group.position.copy(head).add(new THREE.Vector3(0, 0.27, 0));
    this.stars.forEach((s, i) => {
      const a = t * 3.4 + (i / this.stars.length) * Math.PI * 2;
      s.position.set(Math.cos(a) * 0.25, Math.sin(a * 2) * 0.03, Math.sin(a) * 0.25);
      const depth = 0.75 + 0.25 * Math.sin(a);
      s.scale.setScalar(0.13 * this.amount * depth);
      s.material.rotation = -t * 4 + i;
      s.material.opacity = this.amount;
    });
  }
}

// Camera flashes popping in the stands; bursts on big moments.
export class CrowdFlashes {
  constructor(scene, seats) {
    this.seats = seats;
    this.sprites = Array.from({ length: 14 }, () => {
      const s = new THREE.Sprite(
        new THREE.SpriteMaterial({ map: tex("glow"), color: "#ffffff", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }),
      );
      s.visible = false;
      scene.add(s);
      return { s, life: 0 };
    });
    this.pending = 0;
  }
  burst(n) {
    this.pending += n;
  }
  update(dt, ambient) {
    if (Math.random() < dt * ambient) this.pending++;
    for (const f of this.sprites) {
      if (f.life > 0) {
        f.life -= dt;
        f.s.material.opacity = Math.max(0, f.life / 0.09);
        f.s.visible = f.life > 0;
      } else if (this.pending > 0 && Math.random() < 0.5) {
        this.pending--;
        const seat = this.seats[Math.floor(Math.random() * this.seats.length)];
        f.s.position.copy(seat).add(new THREE.Vector3(0, 0.5, 0));
        f.s.scale.setScalar(0.5 + Math.random() * 0.4);
        f.life = 0.09;
        f.s.visible = true;
      }
    }
    this.pending = Math.min(this.pending, 20);
  }
}
