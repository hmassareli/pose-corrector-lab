// Articulated rigid-body KO. The root is NEVER animated through a fall angle.
import * as THREE from "three";
import * as C from "/static/vendor/cannon-es/cannon-es.js";

const FLOOR = 0.026,
  STEP = 1 / 120;

// Potência do soco que derruba. Exportada para que testes e documentos
// leiam a MESMA fonte versionada em vez de duplicar o número (A06/C02).
export const KO_IMPULSE_BASE = 1500;
export const KO_IMPULSE_PER_POWER = 0.33;
export const KO_IMPULSE_TORSO_RATIO = 0.9;
const cv = (v) => new C.Vec3(v.x, v.y, v.z);
const tv = (v) => new THREE.Vector3(v.x, v.y, v.z);
const tq = (q) => new THREE.Quaternion(q.x, q.y, q.z, q.w);

export function prepareKnockout(actor) {
  const limbBones = new Set();
  for (const name of ["leftArm", "rightArm", "leftUpLeg", "rightUpLeg"])
    actor.rig.bones.get(name)?.bone.traverse((b) => limbBones.add(b));
  const directions = [];
  for (let x = -1; x <= 1; x++)
    for (let y = -1; y <= 1; y++)
      for (let z = -1; z <= 1; z++)
        if (x || y || z)
          directions.push(new THREE.Vector3(x, y, z).normalize());
  actor.knockoutSurface = [];
  actor.root.traverse((mesh) => {
    if (!mesh.isSkinnedMesh) return;
    const { position, skinIndex, skinWeight } = mesh.geometry.attributes;
    if (!skinIndex || !skinWeight) return;
    const groups = new Map(),
      p = new THREE.Vector3();
    for (let i = 0; i < position.count; i++) {
      let dominant = 0;
      for (let k = 1; k < 4; k++)
        if (
          skinWeight.getComponent(i, k) > skinWeight.getComponent(i, dominant)
        )
          dominant = k;
      const id = skinIndex.getComponent(i, dominant);
      let group = groups.get(id);
      if (!group) {
        group = directions.map(() => ({ value: -Infinity, index: 0 }));
        groups.set(id, group);
      }
      p.fromBufferAttribute(position, i);
      for (let k = 0; k < directions.length; k++) {
        const value = p.dot(directions[k]);
        if (value > group[k].value) {
          group[k].value = value;
          group[k].index = i;
        }
      }
    }
    const byBone = [...groups].map(([id, g]) => ({
      bone: mesh.skeleton.bones[id],
      indices: [...new Set(g.map((p) => p.index))],
    }));
    const indices = [...new Set(byBone.flatMap((g) => g.indices))];
    const coreIndices = byBone
      .filter((g) => !limbBones.has(g.bone))
      .flatMap((g) => g.indices);
    actor.knockoutSurface.push({ mesh, indices, coreIndices, byBone });
  });
}

class IgnoreOverlap extends C.Constraint {
  constructor(a, b) {
    super(a, b, { collideConnected: false });
  }
  update() {}
}

// Cone/twist axes are calibrated in a COMMON world frame at handoff. This
// avoids a startup twist impulse from the different native axes of each rig.
function ballJoint(a, b, pivot, angle, twist) {
  const axis = tv(b.position).sub(tv(a.position)).normalize();
  if (axis.lengthSq() < 0.001) axis.set(0, 1, 0);
  const reference = new THREE.Vector3(1, 0, 0);
  if (Math.abs(reference.dot(axis)) > 0.85) reference.set(0, 0, 1);
  reference.addScaledVector(axis, -reference.dot(axis)).normalize();
  const joint = new C.ConeTwistConstraint(a, b, {
    pivotA: a.pointToLocalFrame(cv(pivot)),
    pivotB: b.pointToLocalFrame(cv(pivot)),
    axisA: a.vectorToLocalFrame(cv(axis)),
    axisB: b.vectorToLocalFrame(cv(axis)),
    angle,
    twistAngle: twist,
    maxForce: 100000,
    collideConnected: false,
  });
  const refA = a.vectorToLocalFrame(cv(reference)),
    refB = b.vectorToLocalFrame(cv(reference));
  const original = joint.update.bind(joint);
  joint.update = () => {
    original();
    a.vectorToWorldFrame(refA, joint.twistEquation.axisA);
    b.vectorToWorldFrame(refB, joint.twistEquation.axisB);
  };
  return joint;
}

// A hinge constrains the bend plane. An additional unilateral cone equation
// limits flexion to the anatomical side of extension instead of bending both
// ways. It shares the hinge anchors, without duplicating positional equations.
function bendJoint(a, b, pivot, upper, lower, fallbackAxis, maxBend) {
  let axis = new THREE.Vector3().crossVectors(upper, lower);
  if (axis.length() < 0.06) axis.copy(fallbackAxis);
  axis.normalize();
  const initial = Math.atan2(
    new THREE.Vector3().crossVectors(upper, lower).dot(axis),
    upper.dot(lower),
  );
  const maximum = Math.min(2.95, Math.max(maxBend, initial + 0.08)),
    minimum = Math.min(-0.025, initial - 0.025);
  const mid = (maximum + minimum) / 2;
  const center = upper.clone().applyAxisAngle(axis, mid);
  const joint = new C.HingeConstraint(a, b, {
    pivotA: a.pointToLocalFrame(cv(pivot)),
    pivotB: b.pointToLocalFrame(cv(pivot)),
    axisA: a.vectorToLocalFrame(cv(axis)),
    axisB: b.vectorToLocalFrame(cv(axis)),
    maxForce: 100000,
    collideConnected: false,
  });
  const holder = ballJoint(a, b, pivot, maximum, Math.PI);
  const limit = holder.coneEquation;
  const coneA = a.vectorToLocalFrame(cv(center)),
    coneB = b.vectorToLocalFrame(cv(lower));
  limit.angle = (maximum - minimum) / 2;
  joint.equations.push(limit);
  const original = joint.update.bind(joint);
  joint.update = () => {
    original();
    a.vectorToWorldFrame(coneA, limit.axisA);
    b.vectorToWorldFrame(coneB, limit.axisB);
  };
  joint.bendAxisA = a.vectorToLocalFrame(cv(axis));
  joint.bendMinimum = minimum;
  joint.bendMaximum = maximum;
  return joint;
}

export class KnockoutRagdoll {
  constructor(actor, fighter, away) {
    this.actor = actor;
    this.time = 0;
    this.accumulator = 0;
    this.settled = false;
    actor.group.updateWorldMatrix(true, true);
    this.groupPosition = actor.group.position.clone();
    this.groupQuaternion = actor.group.quaternion.clone();
    this.rootPosition = actor.root.position.clone();
    this.rootQuaternion = actor.root.quaternion.clone();
    this.pose = [];
    actor.root.traverse((b) => {
      if (b.isBone)
        this.pose.push({
          bone: b,
          position: b.position.clone(),
          quaternion: b.quaternion.clone(),
        });
    });
    const world = (this.world = new C.World({
      gravity: new C.Vec3(0, -9.81, 0),
      allowSleep: true,
    }));
    world.solver.iterations = 35;
    world.solver.tolerance = 1e-7;
    world.defaultContactMaterial.friction = 0.65;
    world.defaultContactMaterial.restitution = 0;
    world.defaultContactMaterial.contactEquationStiffness = 1e8;
    world.defaultContactMaterial.contactEquationRelaxation = 5;
    const ground = new C.Body({
      mass: 0,
      collisionFilterGroup: 1,
      collisionFilterMask: 2,
    });
    ground.addShape(new C.Plane());
    ground.quaternion.setFromEuler(-Math.PI / 2, 0, 0);
    ground.position.y = FLOOR;
    world.addBody(ground);
    // Physical perimeter: no visual clamping or root teleport at the ropes.
    for (const [x, z, yaw] of [
      [3.1, 0, -Math.PI / 2],
      [-3.1, 0, Math.PI / 2],
      [0, 3.1, Math.PI],
      [0, -3.1, 0],
    ]) {
      const wall = new C.Body({
        mass: 0,
        collisionFilterGroup: 1,
        collisionFilterMask: 2,
      });
      wall.addShape(new C.Plane());
      wall.position.set(x, 0, z);
      wall.quaternion.setFromEuler(0, yaw, 0);
      world.addBody(wall);
    }
    const specs = [
      ["hips", 14],
      ["spine", 3],
      ["spine1", 7],
      ["spine2", 16],
      ["neck", 1],
      ["head", 5],
      ...["left", "right"].flatMap((s) => [
        [s + "Arm", 2],
        [s + "ForeArm", 1.4],
        [s + "Hand", 0.8],
        [s + "UpLeg", 8],
        [s + "Leg", 4],
        [s + "Foot", 1.2],
      ]),
    ];
    this.parts = new Map();
    this.joints = [];
    const owners = new Map();
    for (const [name] of specs) {
      const bone = actor.rig.bones.get(name)?.bone;
      if (bone) owners.set(bone, name);
    }
    const samples = new Map(specs.map(([name]) => [name, []]));
    const point = new THREE.Vector3();
    for (const entry of actor.knockoutSurface || []) {
      entry.mesh.skeleton.update();
      for (const group of entry.byBone) {
        let ancestor = group.bone;
        while (ancestor && !owners.has(ancestor)) ancestor = ancestor.parent;
        const list = samples.get(owners.get(ancestor));
        if (!list) continue;
        for (const id of group.indices) {
          point.fromBufferAttribute(
            entry.mesh.geometry.attributes.position,
            id,
          );
          entry.mesh.applyBoneTransform(id, point);
          entry.mesh.localToWorld(point);
          list.push(point.clone());
        }
      }
    }
    for (const [name, mass] of specs) {
      const bone = actor.rig.bones.get(name)?.bone;
      if (!bone) continue;
      const origin = bone.getWorldPosition(new THREE.Vector3()),
        rotation = bone.getWorldQuaternion(new THREE.Quaternion());
      const inverse = rotation.clone().invert(),
        bounds = new THREE.Box3();
      for (const p of samples.get(name))
        bounds.expandByPoint(p.clone().sub(origin).applyQuaternion(inverse));
      if (bounds.isEmpty())
        bounds.set(
          new THREE.Vector3(-0.035, -0.035, -0.035),
          new THREE.Vector3(0.035, 0.035, 0.035),
        );
      const center = bounds.getCenter(new THREE.Vector3()),
        half = bounds
          .getSize(new THREE.Vector3())
          .multiplyScalar(0.5)
          .addScalar(0.008);
      half.max(new THREE.Vector3(0.025, 0.025, 0.025));
      const position = center.clone().applyQuaternion(rotation).add(origin);
      const body = new C.Body({
        mass,
        position: cv(position),
        quaternion: new C.Quaternion(
          rotation.x,
          rotation.y,
          rotation.z,
          rotation.w,
        ),
        linearDamping: 0.24,
        angularDamping: 0.65,
        sleepSpeedLimit: 0.1,
        sleepTimeLimit: 0.7,
        collisionFilterGroup: 2,
        collisionFilterMask: 3,
      });
      body.addShape(new C.Box(cv(half)));
      world.addBody(body);
      this.parts.set(name, {
        name,
        bone,
        body,
        origin,
        anchor: cv(center.clone().negate()),
        half,
      });
    }
    this.initialHips = this.parts.get("hips").origin.clone();
    const pos = (name) => this.parts.get(name).origin;
    const forward = new THREE.Vector3(
      Math.sin(fighter.yaw),
      0,
      Math.cos(fighter.yaw),
    );
    const right = new THREE.Vector3()
      .crossVectors(new THREE.Vector3(0, 1, 0), forward)
      .normalize();
    const connect = (
      parent,
      child,
      angle,
      twist,
      hinge = false,
      end = null,
    ) => {
      const a = this.parts.get(parent),
        b = this.parts.get(child);
      if (!a || !b) return;
      const upper = pos(child).clone().sub(pos(parent)).normalize();
      const lower = end ? pos(end).clone().sub(pos(child)).normalize() : upper;
      const joint = hinge
        ? bendJoint(a.body, b.body, pos(child), upper, lower, right, angle)
        : ballJoint(a.body, b.body, pos(child), angle, twist);
      joint.name = child;
      joint.parentName = parent;
      for (const eq of joint.equations) eq.setSpookParams(1e8, 5, STEP);
      this.joints.push(joint);
      world.addConstraint(joint);
    };
    connect("hips", "spine", 0.48, 0.28);
    connect("spine", "spine1", 0.4, 0.24);
    connect("spine1", "spine2", 0.38, 0.24);
    connect("spine2", "neck", 0.55, 0.4);
    connect("neck", "head", 0.5, 0.45);
    for (const s of ["left", "right"]) {
      connect("spine2", s + "Arm", 1.8, 1.05);
      connect(s + "Arm", s + "ForeArm", 2.55, 0, true, s + "Hand");
      connect(s + "ForeArm", s + "Hand", 0.5, 0.4);
      connect("hips", s + "UpLeg", 1.65, 0.5);
      connect(s + "UpLeg", s + "Leg", 2.45, 0, true, s + "Foot");
      connect(s + "Leg", s + "Foot", 0.5, 0.25);
    }
    // Connected parts never collide. Also exclude meshes overlapping at the
    // captured pose: resolving their initial penetration would inject energy.
    const parts = [...this.parts.values()];
    for (let i = 0; i < parts.length; i++)
      for (let k = i + 1; k < parts.length; k++) {
        const a = parts[i].body,
          b = parts[k].body;
        a.updateAABB();
        b.updateAABB();
        if (a.aabb.overlaps(b.aabb))
          world.addConstraint(new IgnoreOverlap(a, b));
      }
    // Apply the main impact impulse at the head, plus a small coupled impulse
    // at the upper torso. The neck, spine and hips then receive the force
    // through the articulated constraints. Setting velocity on every body
    // would make the fighter slide as a rigid block and bypass that transfer.
    // `reaction.dir` is the glove sweep in world space. Some replay packets
    // used the opposite convention in the past, so orient it against the
    // victim-to-attacker vector before applying it.
    const fallback = new THREE.Vector3(...away);
    fallback.y = 0;
    if (!Number.isFinite(fallback.lengthSq()) || fallback.lengthSq() < 1e-8)
      fallback.copy(forward);
    fallback.normalize();
    const punch = new THREE.Vector3(...(fighter.reaction?.dir || []));
    punch.y = 0;
    if (!Number.isFinite(punch.lengthSq()) || punch.lengthSq() < 1e-8)
      punch.copy(fallback);
    else {
      punch.normalize();
      if (punch.dot(fallback) < 0) punch.negate();
      // Preserve the punch direction, with a small away-from-attacker bias
      // so a perfectly sideways hook still has believable forward travel.
      punch.lerp(fallback, 0.18).normalize();
    }
    const power = THREE.MathUtils.clamp(fighter.reaction?.power ?? 0.5, 0, 1);
    const head = this.parts.get("head");
    const contact =
      fighter.reaction?.head !== false ? fighter.reaction?.pos : null;
    const hitPoint = new THREE.Vector3(...(contact || []));
    if (!Number.isFinite(hitPoint.lengthSq()) || hitPoint.lengthSq() < 1e-8)
      hitPoint.copy(head.body.position);
    const hitOffset = hitPoint.clone().sub(head.body.position);
    if (hitOffset.length() > 0.16)
      hitPoint
        .copy(head.body.position)
        .add(hitOffset.normalize().multiplyScalar(0.16));
    // Cannon uses N*s for impulses. This is a small increase over the
    // previous head-only shove; the torso share improves weight transfer
    // without launching the whole ragdoll.
    const impulseMagnitude = KO_IMPULSE_BASE + power * KO_IMPULSE_PER_POWER;
    const impulse = punch.clone().multiplyScalar(impulseMagnitude);
    head.body.applyImpulse(cv(impulse), cv(hitPoint));
    head.body.wakeUp();
    const torso = this.parts.get("spine2") || this.parts.get("spine1");
    const torsoImpulseMagnitude = impulseMagnitude * KO_IMPULSE_TORSO_RATIO;
    const torsoImpulse = punch.clone().multiplyScalar(torsoImpulseMagnitude);
    torso.body.applyImpulse(cv(torsoImpulse), cv(torso.body.position));
    torso.body.wakeUp();
    this.pushDirection = punch.clone();
    this.pushImpulse = impulseMagnitude;
    this.pushTorsoImpulse = torsoImpulseMagnitude;
    this.pushPoint = hitPoint.clone();
    this.knees = this.joints.filter((j) => /^(left|right)Leg$/.test(j.name));
    this.ordered = parts.sort((a, b) => {
      const depth = (bone) => {
        let d = 0;
        for (let p = bone; p; p = p.parent) d++;
        return d;
      };
      return depth(a.bone) - depth(b.bone);
    });
    this.quietTime = 0;
  }
  restore() {
    const a = this.actor;
    a.root.position.copy(this.rootPosition);
    a.root.quaternion.copy(this.rootQuaternion);
    a.group.position.copy(this.groupPosition);
    a.group.quaternion.copy(this.groupQuaternion);
    for (const p of this.pose) {
      p.bone.position.copy(p.position);
      p.bone.quaternion.copy(p.quaternion);
    }
  }
  step() {
    // A small finite flexion torque breaks the perfectly straight/balanced
    // virtual knee. It acts as an equal/opposite internal pair, not a launch.
    if (this.time < 0.28)
      for (const knee of this.knees) {
        const axis = knee.bodyA.vectorToWorldFrame(knee.bendAxisA);
        axis.scale(knee.name === "leftLeg" ? 2.8 : 2.0, axis);
        knee.bodyB.torque.vadd(axis, knee.bodyB.torque);
        knee.bodyA.torque.vsub(axis, knee.bodyA.torque);
      }
    this.world.step(STEP);
    this.time += STEP;
    let maxSpeed = 0;
    for (const { body } of this.parts.values()) {
      const speed = body.velocity.length(),
        spin = body.angularVelocity.length();
      if (speed > 6) body.velocity.scale(6 / speed, body.velocity);
      if (spin > 9) body.angularVelocity.scale(9 / spin, body.angularVelocity);
      maxSpeed = Math.max(maxSpeed, speed, spin * 0.15);
    }
    this.quietTime = maxSpeed < 0.14 ? this.quietTime + STEP : 0;
    if (this.time > 2 && this.quietTime > 0.6) {
      this.settled = true;
      for (const { body } of this.parts.values()) body.sleep();
    }
  }
  present() {
    this.restore();
    const a = this.actor,
      hips = this.parts.get("hips");
    const pelvis = tv(hips.body.pointToWorldFrame(hips.anchor));
    a.group.position.add(pelvis.sub(this.initialHips));
    a.group.updateMatrixWorld(true);
    for (const { bone, body } of this.ordered) {
      const parent = bone.parent
        .getWorldQuaternion(new THREE.Quaternion())
        .invert();
      bone.quaternion.copy(parent.multiply(tq(body.quaternion)));
      bone.updateWorldMatrix(false, true);
    }
    a.group.updateMatrixWorld(true);
  }
  update(seconds, dt) {
    if (!this.settled) {
      this.accumulator += Math.min(
        0.05,
        Math.max(0, Number.isFinite(dt) ? dt : 0),
      );
      while (this.accumulator >= STEP) {
        this.step();
        this.accumulator -= STEP;
      }
    }
    this.present();
  }
  focus() {
    return tv(this.parts.get("hips").body.position).lerp(
      tv(this.parts.get("head").body.position),
      0.35,
    );
  }
  diagnostics() {
    let anchorError = 0;
    for (const j of this.joints)
      anchorError = Math.max(
        anchorError,
        j.bodyA
          .pointToWorldFrame(j.pivotA)
          .distanceTo(j.bodyB.pointToWorldFrame(j.pivotB)),
      );
    return {
      time: this.time,
      anchorError,
      settled: this.settled,
      bodies: this.parts.size,
      pushDirection: this.pushDirection?.toArray() || null,
      pushImpulse: this.pushImpulse || 0,
      pushTorsoImpulse: this.pushTorsoImpulse || 0,
      pushPoint: this.pushPoint?.toArray() || null,
      parts: Object.fromEntries(
        [...this.parts].map(([name, p]) => [
          name,
          {
            position: [p.body.position.x, p.body.position.y, p.body.position.z],
            speed: p.body.velocity.length(),
            spin: p.body.angularVelocity.length(),
          },
        ]),
      ),
    };
  }
  reset() {
    this.restore();
    this.world.bodies.slice().forEach((b) => this.world.removeBody(b));
  }
}
