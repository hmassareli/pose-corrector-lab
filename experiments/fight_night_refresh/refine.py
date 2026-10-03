from pathlib import Path
root=Path('pose_corrector_lab')
for name in ['boxing.html','boxing_i18n.js']:
 s=(root/'experiments/fight_night_refresh/before'/name).read_text(encoding='utf-8-sig')
 s=s.replace('<option value="toon" data-i18n="cartoon">Cartoon</option>','<option value="modern" data-i18n="modern">Fight night</option>')
 s=s.replace("cartoon:'Cartoon'","modern:'Fight night'").replace("cartoon:'Desenho'","modern:'Noite de luta'")
 (root/'viewer'/name).write_text(s,encoding='utf-8')
p=root/'viewer/boxing_arena.js';s=p.read_text(encoding='utf-8')
s=s.replace('canvas: "#25425c"','canvas: "#142631"').replace('canvas: "#3b494e"','canvas: "#2a3438"')
s=s.replace('5.5, -4.5, 60','5.5, -4.5, 35').replace('rgba(4,10,18,.75)", 14','rgba(4,10,18,.75)", 2')
s=s.replace('new THREE.CapsuleGeometry(0.15, 0.26, 3, 8)','new THREE.CylinderGeometry(0.155, 0.115, 0.40, 8)')
s=s.replace('  const crowd = [];','''  const arms = new THREE.InstancedMesh(new THREE.CapsuleGeometry(.048, .22, 2, 6), toon('#ffffff'), count * 2);
  const legs = new THREE.InstancedMesh(new THREE.CapsuleGeometry(.056, .24, 2, 6), toon('#0c1420'), count * 2);
  const crowd = [];''')
s=s.replace('["#132133", "#213851", "#075db1", "#bd1730", "#283442", "#d28d16", "#182332", "#29414a"]','["#101a26", "#1b2b3a", "#074b91", "#9e132a", "#202a35", "#966315", "#141e2b", "#243239", "#152333", "#252630", "#192027", "#202d38"]')
s=s.replace('    heads.setColorAt(i, new THREE.Color(skin[i % skin.length]));','''    heads.setColorAt(i, new THREE.Color(skin[i % skin.length]));
    const shirt = new THREE.Color(shirts[(i * 7 + Math.floor(i / 11)) % shirts.length]);
    arms.setColorAt(i * 2, shirt); arms.setColorAt(i * 2 + 1, shirt);''')
s=s.replace('  arena.add(bodies, heads);','  arms.instanceMatrix.setUsage(THREE.DynamicDrawUsage);\n  legs.instanceMatrix.setUsage(THREE.DynamicDrawUsage);\n  arena.add(bodies, heads, arms, legs);')
s=s.replace('      heads.setMatrixAt(i, dummy.matrix);','''      heads.setMatrixAt(i, dummy.matrix);
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
      }''')
s=s.replace('    bodies.instanceMatrix.needsUpdate = heads.instanceMatrix.needsUpdate = true;','    bodies.instanceMatrix.needsUpdate = heads.instanceMatrix.needsUpdate = arms.instanceMatrix.needsUpdate = legs.instanceMatrix.needsUpdate = true;')
p.write_text(s,encoding='utf-8')
