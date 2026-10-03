from pathlib import Path
p=Path('viewer/boxing.js');s=p.read_text(encoding='utf-8')
s=s.replace('  const movement = f.footwork.update(raw, lastPoseTime, hasCameraPosition ? e.data.cameraInfo : null);','''  const captureTime=Number(e.data.nlfDebug?.capture?.absoluteMs)-performance.timeOrigin;
  const sampleTime=Number.isFinite(captureTime)&&captureTime<=lastPoseTime+10&&lastPoseTime-captureTime<1500?captureTime:lastPoseTime;
  const movement = f.footwork.update(raw, sampleTime, hasCameraPosition ? e.data.cameraInfo : null);''')
s=s.replace('fighters[self].detector.update(raw, lastPoseTime)','fighters[self].detector.update(raw, sampleTime)')
s=s.replace('const limbs = ["left", "right"].map((side) => ({ elbow: P(side + "ForeArm"), wrist: P(side + "Hand") }));','''const limbs = ["left", "right"].map((side,h) => {
    const bone=a.rig.bones.get(side+"Hand")?.bone,glove=a.guardContact.hands[h]?.sphere;
    return {elbow:P(side+"ForeArm"),wrist:P(side+"Hand"),gloveCenter:glove&&bone?glove.center.clone().applyQuaternion(bone.getWorldQuaternion(new THREE.Quaternion())).add(P(side+"Hand")):P(side+"Hand"),
      gloveRadius:glove?.radius || .08};
  });''')
s=s.replace('    arms: limbs.map((l) => ({ a: l.elbow.toArray(), b: along(l, 0.35), r: 0.04 + GLOVE_RADIUS * 0.6 })),\n    gloves: limbs.map((l) => along(l, 0.25)),','''    arms: limbs.flatMap((l,h)=>[
      {a:l.elbow.toArray(),b:l.wrist.toArray(),r:.045+GLOVE_RADIUS,hand:h},
      {a:l.gloveCenter.toArray(),b:l.gloveCenter.toArray(),r:l.gloveRadius+GLOVE_RADIUS,hand:h}
    ]),
    gloves:limbs.map(l=>l.gloveCenter.toArray()),''')
a=s.index('  if (fall > 0) {');b=s.index('  } else {',a)
s=s[:a]+'''  if (fall > 0) {
    const elapsed=Math.max(0,(vclock-ko.vstart-120)/1000);
    const dir=new THREE.Vector3(...(f.reaction?.dir || [f.x-fighters[1-i].x,0,f.z-fighters[1-i].z]));
    dir.y=0;if(dir.lengthSq()<1e-6)dir.set(0,0,i?1:-1);dir.normalize();
    const force=f.reaction?.power || .5;
    const angle=Math.min(1.48,.5*9.81*elapsed*elapsed);
    const tiltAxis=new THREE.Vector3(0,1,0).cross(dir).normalize();
    const tilt=new THREE.Quaternion().setFromAxisAngle(tiltAxis,angle);
    a.group.quaternion.copy(tilt.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),f.yaw)));
    a.group.position.addScaledVector(dir,Math.min(.7,elapsed*(.65+force*.45)));
    a.group.position.y+=Math.max(0,.55*elapsed-.5*9.81*elapsed*elapsed);
    a.group.updateMatrixWorld(true);
    // The fall is grounded against shoe AND face samples, so neither settles
    // below the mat after the impact-directed rotation.
    const head=a.rig.bones.get('head').bone;
    const low=Math.min(...['leftFoot','rightFoot'].map(n=>soleBottom(a,a.rig.bones.get(n).bone)),
      ...(a.headSurface?.points || []).map(p=>head.localToWorld(p.clone()).y));
    if(Number.isFinite(low))a.group.position.y+=.026-low;
    a.group.updateMatrixWorld(true);
''' + s[b:]
p.write_text(s,encoding='utf-8')
p=Path('viewer/boxing_core.mjs');s=p.read_text()
s=s.replace('box.arms.forEach((f, h) => {','box.arms.forEach((f, h) => {')
s=s.replace('(arm = h), (s = as);','(arm = f.hand ?? h), (s = as);')
p.write_text(s)
