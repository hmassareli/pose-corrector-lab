import * as THREE from 'three';
import { ConvexHull } from 'three/addons/math/ConvexHull.js';
import { solveTwoBone } from './boxing_feet.js';

const SKIN = .004;
const SOFT_BAND = 0;
const at = bone => bone.getWorldPosition(new THREE.Vector3());

// Sample only once, after the avatar's final scale/calibration. Measurements
// are metres in the bone's rotational frame, not FBX centimetres or rig pivots.
export function sampleBoneSurface(actor, bone) {
  actor.group.updateWorldMatrix(true, true);
  // SkinnedMesh's attached bind inverse is refreshed by updateMatrixWorld,
  // not updateWorldMatrix. Sampling before the first render must match it.
  actor.group.updateMatrixWorld(true);
  const points = [], origin = at(bone), inverse = bone.getWorldQuaternion(new THREE.Quaternion()).invert();
  actor.root.traverse(mesh => {
    if (!mesh.isSkinnedMesh) return;
    const { position, skinIndex, skinWeight } = mesh.geometry.attributes;
    if (!skinIndex || !skinWeight) return;
    const ids = new Set();
    bone.traverse(b => { const id = mesh.skeleton.bones.indexOf(b); if (id >= 0) ids.add(id); });
    mesh.skeleton.update();
    for (let i = 0; i < position.count; i++) {
      let weight = 0;
      for (let c = 0; c < 4; c++) if (ids.has(skinIndex.getComponent(i, c))) weight += skinWeight.getComponent(i, c);
      if (weight < .65) continue;
      const p = new THREE.Vector3().fromBufferAttribute(position, i);
      mesh.applyBoneTransform(i, p); mesh.localToWorld(p);
      points.push(p.sub(origin).applyQuaternion(inverse));
    }
  });
  return points;
}

function headSurface(points) {
  if (points.length < 4) return null;
  // A physics envelope needs tens of faces, not the render mesh's thousands.
  // Keep native support points in 98 directions, then enlarge the hull just
  // enough to contain EVERY sampled skin point, including nose and ears.
  const support = new Set(), directions = new Set();
  for (let x = -2; x <= 2; x++) for (let y = -2; y <= 2; y++) for (let z = -2; z <= 2; z++) {
    if (!x && !y && !z) continue;
    const d = new THREE.Vector3(x, y, z).normalize(), key = d.toArray().map(v => v.toFixed(6)).join(',');
    if (directions.has(key)) continue;
    directions.add(key);
    let best = -Infinity, chosen;
    for (const p of points) { const dot = p.dot(d); if (dot > best) { best = dot; chosen = p; } }
    support.add(chosen);
  }
  const cloud = [...support], center = cloud.reduce((s, p) => s.add(p), new THREE.Vector3()).divideScalar(cloud.length);
  const hull = new ConvexHull().setFromPoints(cloud);
  let expansion = 1;
  for (const f of hull.faces) {
    const extent = f.constant - f.normal.dot(center);
    if (extent < 1e-8) continue;
    for (const p of points) expansion = Math.max(expansion, (f.normal.dot(p) - f.normal.dot(center)) / extent);
  }
  const expand = p => p.clone().sub(center).multiplyScalar(expansion).add(center);
  const faces = hull.faces.map(f => ({ normal: f.normal.clone(), constant: f.constant,
    triangle: new THREE.Triangle(expand(f.edge.head().point), expand(f.edge.next.head().point), expand(f.edge.next.next.head().point)) }));
  for (const f of faces) f.constant = f.normal.dot(center) + (f.constant - f.normal.dot(center)) * expansion;
  const point = new THREE.Vector3();
  return {
    faces, expansion,
    // Signed Euclidean distance to the convex skin envelope. Plane distance
    // alone would create oversized invisible corners around cheeks/forehead.
    distance(p, radius = 0, near = Infinity) {
      let plane = -Infinity, normal;
      for (const f of faces) {
        const d = f.normal.dot(p) - f.constant;
        if (d > plane) { plane = d; normal = f.normal; }
      }
      if (plane <= 0 || plane - radius > near) return { gap: plane - radius, normal: normal.clone() };
      let best = Infinity, closest = new THREE.Vector3();
      for (const f of faces) {
        f.triangle.closestPointToPoint(p, point);
        const d = p.distanceToSquared(point);
        if (d < best) { best = d; closest.copy(point); }
      }
      const distance = Math.sqrt(best);
      return { gap: distance - radius, normal: distance > 1e-8 ? p.clone().sub(closest).divideScalar(distance) : normal.clone() };
    },
  };
}

function gloveSphere(points) {
  if (!points.length) return null;
  const center = new THREE.Box3().setFromPoints(points).getCenter(new THREE.Vector3());
  const hull = new ConvexHull().setFromPoints(points), vertices = new Set();
  for (const f of hull.faces) for (const edge of [f.edge, f.edge.next, f.edge.next.next]) vertices.add(edge.head().point);
  return { center, radius: Math.sqrt(Math.max(...points.map(p => p.distanceToSquared(center)))) + .001,
    supportPoints: [...vertices] };
}

// Identity outside the skin: no attraction or precontact repulsion.
export function softContactGap(gap) { return Math.max(SKIN, gap); }

function facePoints(points) {
  if (points.length<20) return points;
  const sorted=points.map(p=>Math.abs(p.x)).sort((a,b)=>a-b);
  const cheek=sorted[Math.floor(sorted.length*.88)];
  // Clip lateral ear tips to cheek width rather than enclosing them in the face.
  return points.map(p=>new THREE.Vector3(THREE.MathUtils.clamp(p.x,-cheek,cheek),p.y,p.z));
}

export class NativeGuardContact {
  constructor(actor) {
    actor.group.updateWorldMatrix(true, true);
    this.headBone = actor.rig.bones.get('head')?.bone;
    this.headPoints = this.headBone ? facePoints(sampleBoneSurface(actor, this.headBone)) : [];
    this.surface = headSurface(this.headPoints);
    this.hands = ['left', 'right'].map(side => {
      const arm = actor.rig.bones.get(side + 'Arm')?.bone;
      const fore = actor.rig.bones.get(side + 'ForeArm')?.bone;
      const hand = actor.rig.bones.get(side + 'Hand')?.bone;
      const points = hand ? sampleBoneSurface(actor, hand) : [];
      return { side, arm, fore, hand, points, sphere: gloveSphere(points), previous: null, time: null };
    });
    this.diagnostics = [];
  }
  reset() { for (const h of this.hands) { h.previous = null; h.time = null; } }
  dimensions() {
    const size = new THREE.Box3().setFromPoints(this.headPoints).getSize(new THREE.Vector3());
    return { headSize: size.toArray(), headSamples: this.headPoints.length, headFaces: this.surface?.faces.length || 0, headEnvelopeExpansion: this.surface?.expansion,
      gloves: this.hands.map(h => ({ side: h.side, radius: h.sphere?.radius, samples: h.points.length, hullVertices: h.sphere?.supportPoints.length })) };
  }
  distance(h, local, headRotation, handRotation) {
    const d = this.surface.distance(local, 0, h.sphere.radius + SOFT_BAND + SKIN);
    if (d.gap - h.sphere.radius > SOFT_BAND + SKIN) return { ...d, gap: d.gap - h.sphere.radius };
    // Use the actual glove's support toward this cheek/forehead, rather than
    // its largest spherical radius in ALL directions (which makes guards float).
    const direction = d.normal.clone().applyQuaternion(headRotation).applyQuaternion(handRotation.clone().invert());
    let support = -Infinity;
    for (const p of h.sphere.supportPoints) support = Math.max(support, -p.dot(direction));
    const radius = support + h.sphere.center.dot(direction) + .001;
    return { ...d, gap: d.gap - radius };
  }
  measure(h) {
    const headOrigin = at(this.headBone), headRotation = this.headBone.getWorldQuaternion(new THREE.Quaternion());
    const handRotation = h.hand.getWorldQuaternion(new THREE.Quaternion());
    const center = h.sphere.center.clone().applyQuaternion(handRotation).add(at(h.hand));
    const local = center.clone().sub(headOrigin).applyQuaternion(headRotation.clone().invert());
    return { local, center, headOrigin, headRotation, handRotation, ...this.distance(h, local, headRotation, handRotation) };
  }
  // Conservative advancement catches a fast hand that crosses the entire
  // head between observations. Contact removes inward motion, allows sliding,
  // and releases immediately when the player withdraws the hand.
  sweep(h, target, now, headRotation, handRotation) {
    if (!h.previous || now - h.time > 250 || now < h.time) return { target, swept: false };
    const start = h.previous.clone(), delta = target.clone().sub(start), length = delta.length();
    if (length < .001) return { target, swept: false };
    let t = 0;
    for (let i = 0; i < 24; i++) {
      const p = start.clone().addScaledVector(delta, t);
      const d = this.distance(h, p, headRotation, handRotation);
      if (d.gap <= SKIN + .0002) {
        const remaining = target.clone().sub(p), inward = remaining.dot(d.normal);
        if (inward < -1e-5) return { target: p.add(remaining.addScaledVector(d.normal, -inward)), swept: true };
        // A tangent/outward departure is free; the endpoint constraint still
        // handles curved surface contact, without sticking to a stale plane.
        return { target, swept: false };
      }
      t += Math.max(.0001, (d.gap - SKIN) / length);
      if (t >= 1) return { target, swept: false };
    }
    return { target, swept: false };
  }
  apply(actor, now = performance.now()) {
    if (!this.surface) return;
    actor.group.updateWorldMatrix(true, true);
    this.diagnostics = [];
    for (const h of this.hands) {
      if (!h.arm || !h.fore || !h.hand || !h.sphere) continue;
      const initial = this.measure(h), wrist = at(h.hand), rotation = h.hand.getWorldQuaternion(new THREE.Quaternion());
      const swept = this.sweep(h, initial.local.clone(), now, initial.headRotation, rotation);
      let local = swept.target;
      const d = this.distance(h, local, initial.headRotation, rotation);
      // Softness belongs to the RAW approach, not the already projected
      // contact point. Reapplying it there would make a held guard creep out.
      const wantedGap = swept.swept
        ? (initial.gap < SKIN + SOFT_BAND ? softContactGap(initial.gap) : SKIN)
        : softContactGap(d.gap);
      const correction = Math.max(0, wantedGap - d.gap);
      if (correction > 0) local = local.clone().addScaledVector(d.normal, correction);
      const targetCenter = local.clone().applyQuaternion(initial.headRotation).add(initial.headOrigin);
      const offset = targetCenter.sub(initial.center);
      if (offset.lengthSq() > 1e-12) {
        const targetWrist = wrist.clone().add(offset);
        // Preserve the native palm orientation while distributing translation
        // over upper arm and elbow, respecting both native segment lengths.
        solveTwoBone(h.arm, h.fore, h.hand, targetWrist, actor.group.getWorldDirection(new THREE.Vector3()));
        if (actor.alignWrists) actor.alignWrists();
        else h.hand.quaternion.copy(h.hand.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(rotation));
        h.hand.updateWorldMatrix(false, true);
      }
      // At full extension, a pure normal projection can lie beyond the arm's
      // reachable sphere. Slide along that sphere instead of stretching the
      // limb or repeatedly asking IK for the same unreachable wrist target.
      for(let iteration=0;iteration<10;iteration++) {
        const current=this.measure(h);
        if(current.gap>=SKIN-.00005)break;
        const shoulder=at(h.arm),elbow=at(h.fore),hand=at(h.hand);
        const reach=shoulder.distanceTo(elbow)+elbow.distanceTo(hand)-.001;
        const radial=hand.clone().sub(shoulder).normalize();
        const normal=current.normal.clone().applyQuaternion(current.headRotation);
        let direction=normal.clone();
        if(hand.distanceTo(shoulder)>reach-.003&&normal.dot(radial)>0)
          direction.addScaledVector(radial,-direction.dot(radial));
        if(direction.lengthSq()<1e-8)break;
        direction.normalize();
        const step=Math.min(.04,(SKIN-current.gap)/Math.max(.12,direction.dot(normal)));
        const target=hand.addScaledVector(direction,step);
        const offset=target.clone().sub(shoulder);
        if(offset.length()>reach)target.copy(shoulder).add(offset.setLength(reach));
        solveTwoBone(h.arm,h.fore,h.hand,target,actor.group.getWorldDirection(new THREE.Vector3()));
        if(actor.alignWrists)actor.alignWrists();
        else h.hand.quaternion.copy(h.hand.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(rotation));
        h.hand.updateWorldMatrix(false,true);
      }
      const final = this.measure(h);
      h.previous = final.local.clone(); h.time = now;
      this.diagnostics.push({ side: h.side, beforeGap: initial.gap, afterGap: final.gap,
        correction: at(h.hand).distanceTo(wrist), swept: swept.swept, contact: initial.gap <= SKIN + SOFT_BAND });
    }
  }
}
