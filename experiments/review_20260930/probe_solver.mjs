// Auditoria: executa o solver atual sem modificar o codigo de producao.
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as THREE from './three.module.mjs';
const here = path.dirname(fileURLToPath(import.meta.url));
const lab = path.resolve(here, '../..');
const source = fs.readFileSync(path.join(lab, 'viewer/mikapo_mixamo_solver.js'), 'utf8');
const ctx = vm.createContext({ THREE });
vm.runInContext(source.replace(/import \* as THREE from "three";/, '').replace(/export /g, '') + `
globalThis.api = { rotateBoneWithAcross, rotateBoneToward, applyHeadFromAux,
  computeHandPalmAxes, QuaternionOneEuroFilter, updateAvatarPose, buildAvatarRig,
  createAvatarMotion, updateJointTranslations, plantAvatarOnGround, filtersFor,
  applyFitTwists, setHandRetargetOpts, rotateBoneWithWitness, auxFromSmpl };`, ctx);
const S = ctx.api;
const V = (x,y,z) => new THREE.Vector3(x,y,z);
const deg = r => r * 180 / Math.PI;
const angle = (a,b) => deg(a.angleTo(b));
const worldQ = b => b.getWorldQuaternion(new THREE.Quaternion());
function single(name='rightForeArm', dir=V(0,1,0), across=V(1,0,0)) {
  const model = new THREE.Group();
  const bone = new THREE.Bone(); model.add(bone);
  const rest = { bone, restLocalQuaternion: bone.quaternion.clone(),
    restLocalPosition: bone.position.clone(), restQuaternionInRoot: bone.quaternion.clone(),
    restDirectionInRoot: dir.clone(), restLocalDirection: dir.clone(), restAcrossInRoot: across.clone() };
  return { model, bone, rest, rig: { bones: new Map([[name,rest]]) } };
}
function loadRig() {
  const bytes = fs.readFileSync(path.join(lab,'assets/boxeador_mixamo_trellis.glb'));
  const gltf = JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString('utf8'));
  const jointSet = new Set(gltf.skins.flatMap(s => s.joints));
  const nodes = gltf.nodes.map((n,i) => {
    const o = jointSet.has(i) ? new THREE.Bone() : new THREE.Object3D();
    o.name=n.name || '';
    if(n.matrix) new THREE.Matrix4().fromArray(n.matrix).decompose(o.position,o.quaternion,o.scale);
    else { if(n.translation)o.position.fromArray(n.translation); if(n.rotation)o.quaternion.fromArray(n.rotation); if(n.scale)o.scale.fromArray(n.scale); }
    return o;
  });
  gltf.nodes.forEach((n,i) => (n.children || []).forEach(j => nodes[i].add(nodes[j])));
  const model = new THREE.Group();
  gltf.scenes[gltf.scene || 0].nodes.forEach(i => model.add(nodes[i]));
  model.updateWorldMatrix(true,true);
  return { model, rig:S.buildAvatarRig(model) };
}
const report = { solver_sha256: (await import('node:crypto')).createHash('sha256').update(source).digest('hex'), three:'0.160.0' };
// A entrada varia 2 graus, sem ruido, com direcao constante.
report.acute_flip = {};
for (const fit of [false,true]) {
  const r=single(); const qs=[];
  for(const d of [89,91]) {
    const across=V(1,0,0).applyAxisAngle(V(0,1,0),d*Math.PI/180);
    S.rotateBoneWithAcross(r.model,r.rig,'rightForeArm',V(0,1,0),across,1,null,true,fit,{lo:0.05,hi:0.2});
    qs.push(worldQ(r.bone));
  }
  report.acute_flip[fit?'fitPalm_true':'live_default']={input_delta_deg:2,output_delta_deg:angle(qs[0],qs[1])};
}
{
  const r=single(),qs=[];
  for(const [i,d]of [89,91].entries()) {
    S.rotateBoneWithAcross(r.model,r.rig,'rightForeArm',V(0,1,0),V(1,0,0).applyAxisAngle(V(0,1,0),d*Math.PI/180),1,1000+i*1000/30,true,false,{lo:.05,hi:.2});
    qs.push(worldQ(r.bone));
  }
  report.acute_flip.live_filtered={input_delta_deg:2,output_delta_deg:angle(qs[0],qs[1])};
}
report.real_asset_flip={};
for(const name of ['leftForeArm','rightForeArm','leftHand','rightHand']) {
  const r=loadRig(), rest=r.rig.bones.get(name), qs=[];
  const axis=rest.restDirectionInRoot.clone().normalize();
  const across=rest.restAcrossInRoot.clone().addScaledVector(axis,-rest.restAcrossInRoot.dot(axis)).normalize();
  for(const d of [89,91]) {
    S.rotateBoneWithAcross(r.model,r.rig,name,axis,across.clone().applyAxisAngle(axis,d*Math.PI/180),1,null,true,false,{lo:0.05,hi:0.2});
    qs.push(worldQ(rest.bone));
  }
  report.real_asset_flip[name]=angle(qs[0],qs[1]);
}
report.antiparallel_across = {};
{
  const dir=V(1,1,1).normalize(),across=V(1,-1,0).normalize(),r=single('rightForeArm',dir,across);
  S.rotateBoneWithAcross(r.model,r.rig,'rightForeArm',dir,across.clone().negate(),1,null,true,true,{lo:.05,hi:.2});
  report.antiparallel_across.synthetic_aim_error_deg=angle(dir,dir.clone().applyQuaternion(worldQ(r.bone)));
}
for(const name of ['leftForeArm','rightForeArm','leftHand','rightHand']) {
  const r=loadRig(),rest=r.rig.bones.get(name),axis=rest.restDirectionInRoot.clone().normalize();
  const across=rest.restAcrossInRoot.clone().addScaledVector(axis,-rest.restAcrossInRoot.dot(axis)).normalize();
  S.rotateBoneWithAcross(r.model,r.rig,name,axis,across.clone().negate(),1,null,true,true,{lo:.05,hi:.2});
  report.antiparallel_across[name+'_aim_error_deg']=angle(axis,rest.restLocalDirection.clone().applyQuaternion(worldQ(rest.bone)));
}
// Ao normalizar, separacao index/pinky perde seu condicionamento metrico.
report.palm_span_invariance=[];
for(const span of [0.06,0.0011]) {
  const aux={right_wrist:V(0,0,0),right_index:V(-span/2,0.1,0),right_pinky:V(span/2,0.1,0)};
  const axes=S.computeHandPalmAxes(aux,'right');
  report.palm_span_invariance.push({span_m:span,across:axes.across?.toArray()});
}
// Frente da face e eixo longitudinal do cranio sao quantidades diferentes.
{
  const r=single('head');
  const aux={kind:'pose33',left_ear:V(0.08,1.7,0),right_ear:V(-0.08,1.7,0),left_eye:V(0.03,1.7,0.08),right_eye:V(-0.03,1.7,0.08),nose:V(0,1.7,0.1)};
  S.applyHeadFromAux(r.model,r.rig,aux,null);
  report.pose33_head={upright_head_axis_error_deg:angle(V(0,1,0),V(0,1,0).applyQuaternion(worldQ(r.bone)))};
}
// Uma medida ausente/degenerada nao mantem a orientacao anterior.
const names=['pelvis','left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle','spine','left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist','neck','head'];
const idx=Object.fromEntries(names.map((n,i)=>[n,i]));
const pose=[[0,1,0],[-.1,1,0],[.1,1,0],[-.1,.55,0],[.1,.55,0],[-.1,.1,0],[.1,.1,0],[0,1.25,0],[-.2,1.5,0],[.2,1.5,0],[-.45,1.5,0],[.45,1.5,0],[-.45,1.75,.1],[.45,1.75,.1],[0,1.5,0],[0,1.8,0]];
{
  const r=loadRig(), motion=S.createAvatarMotion();
  const apply=p=>S.updateAvatarPose({...r,motion,pose:p,nameToIndex:idx,plantGround:false,timestampMs:null});
  apply(pose);
  const fore=r.rig.bones.get('rightForeArm'), q1=fore.bone.quaternion.clone();
  const p=structuredClone(pose);p[idx.right_wrist]=p[idx.right_elbow].slice(); apply(p);
  report.degenerate_forearm={local_jump_deg:angle(q1,fore.bone.quaternion),returned_to_rest_deg:angle(fore.bone.quaternion,fore.restLocalQuaternion)};
  const bad=structuredClone(pose);bad[idx.right_wrist][0]=NaN; apply(bad);
  report.nonfinite={forearm_quaternion_is_finite:fore.bone.quaternion.toArray().every(Number.isFinite)};
}
// Translacoes dependem da primeira pose e ignoram escala na conversao local.
report.translation=[];
for(const scale of [1,0.01]) {
  const model=new THREE.Group();model.scale.setScalar(scale);
  const bones=new Map();
  for(const [name,x] of [['leftArm',-.2/scale],['rightArm',.2/scale]]) {
    const bone=new THREE.Bone();bone.position.set(x,1.5/scale,0);model.add(bone);
    bones.set(name,{bone,restLocalPosition:bone.position.clone()});
  }
  const rig={bones},motion=S.createAvatarMotion();model.updateWorldMatrix(true,true);
  S.updateJointTranslations(model,rig,pose,idx,.4,motion,'shoulder');
  const before=bones.get('rightArm').bone.getWorldPosition(V(0,0,0));
  const yawPose=pose.map(p=>V(...p).applyAxisAngle(V(0,1,0),Math.PI/2).toArray());
  S.updateJointTranslations(model,rig,yawPose,idx,.4,motion,'shoulder');
  const after=bones.get('rightArm').bone.getWorldPosition(V(0,0,0));
  report.translation.push({root_scale:scale,extra_shoulder_translation_for_pure_yaw_m:before.distanceTo(after),local_offset: bones.get('rightArm').bone.position.clone().sub(bones.get('rightArm').restLocalPosition).toArray()});
}
{
  const r=loadRig();S.plantAvatarOnGround(r.model,r.rig,0);
  const y=r.model.position.y;r.model.position.y+=.5;S.plantAvatarOnGround(r.model,r.rig,0);
  report.ground_plant={requested_root_lift_m:.5,result_root_lift_m:r.model.position.y-y};
}
// applyFitTwists escreve o mesmo filtro pela segunda vez com o mesmo timestamp.
{
  const r=single();
  S.rotateBoneToward(r.model,r.rig,'rightForeArm',V(0,1,0),1,0);
  S.rotateBoneToward(r.model,r.rig,'rightForeArm',V(1,0,0),1,33);
  const f=S.filtersFor(r.rig).byName.get('rightForeArm');
  const pre=f.fz.prevDeriv;
  S.applyFitTwists(r.model,r.rig,{rightForeArm:30},[[0,0,0],[1,0,0]],{right_elbow:0,right_wrist:1},null,33);
  report.double_filter_write={derivative_before:pre,derivative_after:f.fz.prevDeriv};
}
// Uma torcao do antebraco apos resolver Hand tambem rotaciona o filho.
{
  const r=single(), hand=new THREE.Bone();r.bone.add(hand);hand.position.set(0,1,0);r.model.updateWorldMatrix(true,true);
  const a=worldQ(hand);
  S.applyFitTwists(r.model,r.rig,{rightForeArm:30},[[0,0,0],[0,1,0]],{right_elbow:0,right_wrist:1},null,null);
  report.fit_twist_child={hand_world_change_after_hand_solve_deg:angle(a,worldQ(hand))};
}
fs.writeFileSync(path.join(here,'solver_probe_results.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
// Reexecucao da mesma sequencia com o rig real. Sem renderizar a malha.
function percentile(values,p) { const a=values.filter(Number.isFinite).sort((a,b)=>a-b);return a.length?a[Math.floor((a.length-1)*p)]:null; }
const sequenceReport={};
for(const filename of ['top_frames.json','abl_live.json','raw_x55_frames.json']) {
  const inputPath=filename==='raw_x55_frames.json'?path.join(here,filename):path.join(lab,'experiments/bake_top',filename);
  if(!fs.existsSync(inputPath))continue;
  const frames=JSON.parse(fs.readFileSync(inputPath,'utf8'));
  const modes=[{filtered:false,mirrored:false},{filtered:true,mirrored:false}];
  if(filename==='raw_x55_frames.json')modes.push({filtered:true,mirrored:true});
  for(const {filtered,mirrored} of modes) {
    const r=loadRig(),motion=S.createAvatarMotion(),jumps={leftHand:[],rightHand:[],leftForeArm:[],rightForeArm:[]},last={};
    let overheadFrames=0,validFrames=0;
    for(let t=0;t<frames.length;t++) {
      const f=frames[t];if(f.ok===false)continue;
      const p=f.joints.map(p=>[p[0],-p[1],-p[2]]);
      const aux=S.auxFromSmpl(f.aux_smpl,true);
      if(mirrored) {
        for(const point of p)point[0]*=-1;
        for(const key of names.filter(n=>n.startsWith('left_'))) {
          const a=idx[key],b=idx[key.replace('left_','right_')];[p[a],p[b]]=[p[b],p[a]];
        }
        for(const v of Object.values(aux))if(v?.isVector3)v.x*=-1;
        for(const key of Object.keys(aux).filter(n=>n.startsWith('left_'))) {
          const other=key.replace('left_','right_');[aux[key],aux[other]]=[aux[other],aux[key]];
        }
      }
      S.updateAvatarPose({...r,pose:p,motion,nameToIndex:idx,aux,plantGround:true,allowFeet:true,timestampMs:filtered?1000+t*1000/30:null,fitPalm:f.aux_smpl.fitPalm===true});
      validFrames++;
      if(p[idx.left_wrist][1]>p[idx.head][1]||p[idx.right_wrist][1]>p[idx.head][1])overheadFrames++;
      for(const b of Object.keys(jumps)) {
        const q=worldQ(r.rig.bones.get(b).bone);
        if(last[b])jumps[b].push({t,deg:angle(last[b],q)});
        last[b]=q;
      }
    }
    const summary={validFrames,overheadFrames,bones:{}};
    for(const [b,rows] of Object.entries(jumps)) {
      const vals=rows.map(r=>r.deg);
      summary.bones[b]={p50_deg:percentile(vals,.5),p95_deg:percentile(vals,.95),max_deg:Math.max(...vals),jumps_gt90:vals.filter(v=>v>90).length,worst_frames:rows.sort((a,b)=>b.deg-a.deg).slice(0,5)};
    }
    sequenceReport[filename+(filtered?'_filtered':'_unfiltered')+(mirrored?'_mirrored':'')]=summary;
  }
}
fs.writeFileSync(path.join(here,'sequence_probe_results.json'),JSON.stringify(sequenceReport,null,2));
for(const [name,r]of Object.entries(sequenceReport))console.log(name,JSON.stringify({frames:r.validFrames,overhead:r.overheadFrames,hand_jumps_gt90:r.bones.leftHand.jumps_gt90+r.bones.rightHand.jumps_gt90,hand_max_deg:Math.max(r.bones.leftHand.max_deg,r.bones.rightHand.max_deg)}));
