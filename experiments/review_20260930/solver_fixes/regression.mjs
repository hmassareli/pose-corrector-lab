// Regressões com Three.js real, rig GLB real e medições de ossos em espaço mundo.
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import * as THREE from '../three.module.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
const lab=path.resolve(here,'../../..');
const V=(...xyz)=>new THREE.Vector3(...xyz);
const degrees=r=>r*180/Math.PI;
const angle=(a,b)=>degrees(a.isQuaternion
 ? a.clone().normalize().angleTo(b.clone().normalize()) : a.angleTo(b));
const worldQ=b=>b.getWorldQuaternion(new THREE.Quaternion());

function solver(file) {
 const source=fs.readFileSync(file,'utf8');
 const ctx=vm.createContext({THREE});
 vm.runInContext(source.replace(/import \* as THREE from "three";/,'').replace(/export /g,'')+`
 globalThis.api={rotateBoneWithAcross,rotateBoneWithWitness,rotateBoneToward,updateAvatarPose,
 buildAvatarRig,createAvatarMotion,computeHandPalmAxes,auxFromSmpl,filtersFor,resetRetargetFilters};`,ctx);
 const api=ctx.api, across=api.rotateBoneWithAcross;
 api.across=(r,name,dir,cross,strength=1,ts=null,fit=false,fade={lo:.05,hi:.2})=>
  source.includes('acuteTwist = false')
   ? across(r.model,r.rig,name,dir,cross,strength,ts,true,fit,fade)
   : across(r.model,r.rig,name,dir,cross,strength,ts,fade);
 return api;
}
function single(name='rightForeArm',dir=V(0,1,0),cross=V(1,0,0)) {
 const model=new THREE.Group(),bone=new THREE.Bone(),child=new THREE.Bone();
 model.add(bone);bone.add(child);child.position.copy(dir);model.updateWorldMatrix(true,true);
 const rest={bone,child,restLocalQuaternion:bone.quaternion.clone(),restLocalPosition:bone.position.clone(),
  restQuaternionInRoot:bone.quaternion.clone(),restDirectionInRoot:dir.clone(),
  restLocalDirection:dir.clone(),restAcrossInRoot:cross.clone(),restWitnessInRoot:cross.clone()};
 return {model,bone,rest,rig:{bones:new Map([[name,rest]])}};
}
function loadRig(S) {
 const bytes=fs.readFileSync(path.join(lab,'assets/boxeador_mixamo_trellis.glb'));
 const gltf=JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString('utf8'));
 const joints=new Set(gltf.skins.flatMap(s=>s.joints));
 const nodes=gltf.nodes.map((n,i)=>{
  const o=joints.has(i)?new THREE.Bone():new THREE.Object3D();o.name=n.name||'';
  if(n.matrix)new THREE.Matrix4().fromArray(n.matrix).decompose(o.position,o.quaternion,o.scale);
  else {if(n.translation)o.position.fromArray(n.translation);if(n.rotation)o.quaternion.fromArray(n.rotation);if(n.scale)o.scale.fromArray(n.scale);}
  return o;
 });
 gltf.nodes.forEach((n,i)=>(n.children||[]).forEach(j=>nodes[i].add(nodes[j])));
 const model=new THREE.Group();gltf.scenes[gltf.scene||0].nodes.forEach(i=>model.add(nodes[i]));
 model.updateWorldMatrix(true,true);return {model,rig:S.buildAvatarRig(model)};
}
function actualDirection(rest) {
 return rest.child.getWorldPosition(V(0,0,0)).sub(rest.bone.getWorldPosition(V(0,0,0))).normalize();
}
const names=['pelvis','left_hip','right_hip','left_knee','right_knee','left_ankle','right_ankle','spine','left_shoulder','right_shoulder','left_elbow','right_elbow','left_wrist','right_wrist','neck','head'];
const idx=Object.fromEntries(names.map((n,i)=>[n,i]));
const pose=[[0,1,0],[-.1,1,0],[.1,1,0],[-.1,.55,0],[.1,.55,0],[-.1,.1,0],[.1,.1,0],[0,1.25,0],[-.2,1.5,0],[.2,1.5,0],[-.45,1.5,0],[.45,1.5,0],[-.45,1.75,.1],[.45,1.75,.1],[0,1.5,0],[0,1.8,0]];
function measure(S) {
 const result={roll90:{},realRig90:{},antiparallelAim:{},witnessAim:0,invalid:{},continuousTurns:{}};
 for(const ts of [null,33]) {
  const r=single(),q=[];
  for(const [i,d] of [89,91].entries()) {
   S.across(r,'rightForeArm',V(0,1,0),V(1,0,0).applyAxisAngle(V(0,1,0),d*Math.PI/180),1,ts==null?null:1000+i*ts);
   q.push(worldQ(r.bone));
  }
  result.roll90[ts==null?'raw':'filtered']=angle(q[0],q[1]);
 }
 for(const name of ['leftForeArm','rightForeArm','leftHand','rightHand']) {
  let r=loadRig(S),rest=r.rig.bones.get(name),axis=actualDirection(rest),q=[];
  const across=rest.restAcrossInRoot.clone().addScaledVector(axis,-rest.restAcrossInRoot.dot(axis)).normalize();
  for(const d of [89,91]) { S.across(r,name,axis,across.clone().applyAxisAngle(axis,d*Math.PI/180));q.push(worldQ(rest.bone)); }
  result.realRig90[name]=angle(q[0],q[1]);
  r=loadRig(S);rest=r.rig.bones.get(name);
  S.across(r,name,axis,across.clone().negate(),1,null,true);
  result.antiparallelAim[name]=angle(axis,actualDirection(rest));
 }
 {
  const dir=V(1,1,1).normalize(),r=single('rightArm',dir,V(1,-1,0).normalize());
  S.rotateBoneWithWitness(r.model,r.rig,'rightArm',dir,r.rest.restWitnessInRoot.clone().negate(),1,null);
  result.witnessAim=angle(dir,actualDirection(r.rest));
 }
 for(const strength of [1,.85]) {
  const r=single('rightHand');let previous=null,max=0,maxAim=0;
  for(let d=0;d<=720;d+=2) {
   S.across(r,'rightHand',V(0,1,0),V(1,0,0).applyAxisAngle(V(0,1,0),d*Math.PI/180),strength);
   const q=worldQ(r.bone);if(previous)max=Math.max(max,angle(previous,q));previous=q;
   maxAim=Math.max(maxAim,angle(V(0,1,0),actualDirection(r.rest)));
  }
  result.continuousTurns[strength]={maxStep:max,maxAim};
 }
 for(const invalid of ['zero','NaN','Infinity','missing']) {
  const r=loadRig(S),motion=S.createAvatarMotion();
  const apply=(p,ts)=>S.updateAvatarPose({...r,motion,pose:p,nameToIndex:idx,plantGround:false,timestampMs:ts});
  apply(pose,1000);const fore=r.rig.bones.get('rightForeArm'),prev=fore.bone.quaternion.clone();
  const p=structuredClone(pose);
  if(invalid==='zero')p[idx.right_wrist]=p[idx.right_elbow].slice();
  else if(invalid==='missing')p[idx.right_wrist]=null;
  else p[idx.right_wrist][0]=invalid==='NaN'?NaN:Infinity;
  apply(p,1033);
  result.invalid[invalid]={jump:angle(prev,fore.bone.quaternion),finite:fore.bone.quaternion.toArray().every(Number.isFinite)};
  apply(pose,1066);
  result.invalid[invalid].recovers=[...r.rig.bones.values()].every(b=>b.bone.quaternion.toArray().every(Number.isFinite));
 }
 return result;
}
const before=solver(path.join(here,'solver_before.js'));
const after=solver(path.join(lab,'viewer/mikapo_mixamo_solver.js'));
const report={before:measure(before),after:measure(after)};
fs.writeFileSync(path.join(here,'regression_results.json'),JSON.stringify(report,null,2));
for(const v of Object.values(report.after.roll90))assert(v<=2.001,'89→91 deve mudar no máximo 2°');
for(const v of Object.values(report.after.realRig90))assert(Math.abs(v-2)<.001,'Rig real deve acompanhar 2°');
for(const v of Object.values(report.after.antiparallelAim))assert(v<.001,'Twist a 180° não pode desviar o membro');
assert(report.after.witnessAim<.001,'Witness deve preservar a direção primária');
for(const r of Object.values(report.after.continuousTurns)) {assert(r.maxStep<=2.001,'Giro contínuo não pode inverter em 90°/180°');assert(r.maxAim<.001);}
for(const r of Object.values(report.after.invalid)) {assert(r.jump<.001,'Medição inválida deve reter rotação');assert(r.finite&&r.recovers);}

// Frame corporal inválido: preserve também posição, referência e estado do filtro.
for(const key of ['left_shoulder','right_shoulder','left_hip','right_hip']) {
 const r=loadRig(after),motion=after.createAvatarMotion();
 const apply=p=>after.updateAvatarPose({...r,motion,pose:p,nameToIndex:idx,plantGround:false,timestampMs:1000});
 apply(pose);const qs=[...r.rig.bones.values()].map(b=>b.bone.quaternion.clone()),root=r.model.position.clone();
 const bad=structuredClone(pose);bad[idx[key]][1]=NaN;apply(bad);
 [...r.rig.bones.values()].forEach((b,i)=>assert(angle(qs[i],b.bone.quaternion)<.001));assert(root.equals(r.model.position));
}
// Uma palma inválida não envenena o filtro e não modifica a entrada.
{
 const r=single(),ts=1000;after.across(r,'rightForeArm',V(0,1,0),V(1,0,0),1,ts);
 const filter=after.filtersFor(r.rig).byName.get('rightForeArm'),prior=filter.prev.clone();
 assert.equal(after.rotateBoneToward(r.model,r.rig,'rightForeArm',V(NaN,1,0),1,1033),false);
 assert(filter.prev.equals(prior));
 assert.equal(after.computeHandPalmAxes({right_wrist:V(0,0,0),right_index:V(NaN,.1,0),right_pinky:V(.03,.1,0)},'right'),null);
}
// Reter o antebraço inválido não pode girar a mão que recebeu aux válido.
{
 const aux={kind:'smpl',right_wrist:V(.45,1.75,.1),right_index:V(.42,1.84,.16),right_pinky:V(.48,1.84,.16)};
 const control=loadRig(after),bad=loadRig(after);
 for(const r of [control,bad])r.motion=after.createAvatarMotion();
 const apply=(r,p)=>after.updateAvatarPose({...r,pose:p,nameToIndex:idx,aux,fitPalm:true,plantGround:false});
 for(const r of [control,bad])apply(r,pose);
 const p=structuredClone(pose);p[idx.right_wrist]=p[idx.right_elbow].slice();
 apply(control,pose);apply(bad,p);
 assert(angle(worldQ(control.rig.bones.get('rightHand').bone),worldQ(bad.rig.bones.get('rightHand').bone))<.001);
}
// Sem across, conserve o roll observado; não volte ao repouso.
{
 const r=single();const dir=V(0,1,0),across=V(1,0,0).applyAxisAngle(dir,1.2);
 after.across(r,'rightForeArm',dir,across);const q=worldQ(r.bone);
 after.across(r,'rightForeArm',dir,V(NaN,0,0));assert(angle(q,worldQ(r.bone))<.001);
}
// Aux parcial, incluindo coluna/collar ausentes, não deve interromper o frame.
{
 const r=loadRig(after),motion=after.createAvatarMotion();
 const aux={kind:'smpl',left_shoulder:V(-.2,1.5,0),right_shoulder:V(.2,1.5,0),
  neck:V(0,1.5,0),head:V(0,1.8,0),spine3:V(0,1.4,0),left_eye:V(-.03,1.8,.1),right_eye:V(.03,1.8,.1)};
 after.updateAvatarPose({...r,motion,pose,nameToIndex:idx,aux,plantGround:false,timestampMs:1000});
 assert([...r.rig.bones.values()].every(b=>b.bone.quaternion.toArray().every(Number.isFinite)));
}
console.log(JSON.stringify(report,null,2));
console.log('PASS: saltos, dois giros completos, eixo antiparalelo, rig real, dados inválidos, hierarquia e recuperação.');

if(process.argv.includes('--sequences')) {
 const stats=values=>{
  const a=values.filter(Number.isFinite).sort((a,b)=>a-b);
  return {p50:a[Math.floor((a.length-1)*.5)],p95:a[Math.floor((a.length-1)*.95)],max:a.at(-1)};
 };
 const sequences={};
 for(const [label,S] of [['before',before],['after',after]]) {
  sequences[label]={};
  for(const file of ['top_frames.json','raw_x55_frames.json']) {
   const input=file==='raw_x55_frames.json'?path.join(here,'..',file):path.join(lab,'experiments/bake_top',file);
   const frames=JSON.parse(fs.readFileSync(input,'utf8'));
   const r=loadRig(S),motion=S.createAvatarMotion(),jumps={},aim={},last={};let finite=true;
   for(let t=0;t<frames.length;t++) {
    const f=frames[t],p=f.joints.map(v=>[v[0],-v[1],-v[2]]);
    S.updateAvatarPose({...r,motion,pose:p,nameToIndex:idx,aux:S.auxFromSmpl(f.aux_smpl,true),
     timestampMs:1000+t*1000/30,allowFeet:true,fitPalm:f.aux_smpl?.fitPalm===true});
    finite&&=[...r.rig.bones.values()].every(b=>b.bone.quaternion.toArray().every(Number.isFinite));
    for(const side of ['left','right']) {
     for(const part of ['Hand','ForeArm']) {
      const name=side+part,q=worldQ(r.rig.bones.get(name).bone);
      if(last[name])(jumps[name]??=[]).push(angle(last[name],q));last[name]=q;
     }
     const target=V(...p[idx[side+'_wrist']]).sub(V(...p[idx[side+'_elbow']]));
     (aim[side]??=[]).push(angle(target,actualDirection(r.rig.bones.get(side+'ForeArm'))));
    }
   }
   sequences[label][file]={frames:frames.length,finite,aim:Object.fromEntries(Object.entries(aim).map(([k,v])=>[k,stats(v)])),
    jumps:Object.fromEntries(Object.entries(jumps).map(([k,v])=>[k,{...stats(v),over90:v.filter(x=>x>90).length}]))};
   assert(finite);
  }
 }
 fs.writeFileSync(path.join(here,'sequence_results.json'),JSON.stringify(sequences,null,2));
 console.log(JSON.stringify(sequences,null,2));
}
