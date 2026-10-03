import * as THREE from 'three';

const cache=new WeakMap(),point=new THREE.Vector3(),box=new THREE.Box3();
const matrix=new THREE.Matrix4(),view=new THREE.Matrix4(),clip=new THREE.Vector4();
const skinCache=new WeakMap();let skinStamp=0;
const edges=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];
function corners(bounds){return Array.from({length:8},(_,i)=>new THREE.Vector3(i&1?bounds.max.x:bounds.min.x,i&2?bounds.max.y:bounds.min.y,i&4?bounds.max.z:bounds.min.z));}
function prepare(actor,firstPerson){
 const entries=[];
 actor.group.traverse(mesh=>{
  if(!mesh.isMesh||!mesh.geometry.attributes.position)return;
  if(!mesh.isSkinnedMesh){mesh.geometry.computeBoundingBox();entries.push({mesh,parts:[{corners:corners(mesh.geometry.boundingBox)}]});return;}
  const {position,skinIndex,skinWeight}=mesh.geometry.attributes,index=mesh.geometry.index;
  const headBones=[actor.rig.bones.get('head')?.bone,actor.rig.bones.get('neck')?.bone];
  const transforms=mesh.skeleton.boneInverses.map(inverse=>new THREE.Matrix4().multiplyMatrices(inverse,mesh.bindMatrix));
  mesh.geometry.computeBoundingBox();
  const cell=mesh.geometry.boundingBox.getSize(new THREE.Vector3()).y/24;
  const groups=new Map(),count=index?index.count:position.count;
  // Group whole triangles by their participating skin bones. In each group,
  // the union of bone-local boxes contains ALL weighted vertex components.
  // Their posed view-space AABB encloses every weighted vertex/triangle,
  // even when different components lie on opposite sides of the near plane.
  for(let i=0;i<count;i+=3){
   const ids=[0,1,2].map(k=>index?index.getX(i+k):i+k),bones=new Set();let retained=!firstPerson;
   for(const id of ids){let headWeight=0;
    for(let j=0;j<4;j++){const weight=skinWeight.getComponent(id,j);if(weight<=0)continue;
     const bone=skinIndex.getComponent(id,j);bones.add(bone);if(headBones.includes(mesh.skeleton.bones[bone]))headWeight+=weight;
    }
    if(headWeight<=.08)retained=true;
   }
   // This exactly respects the head-weight discard used by the first-person
   // shader, conservatively retaining all vertices of boundary triangles.
   if(!retained)continue;
   let key=[...bones].sort((a,b)=>a-b).join(',');
   // Nearby first-person triangles need smaller envelopes than a whole limb;
   // otherwise a near-clipped shoulder box can conservatively fill the screen.
   if(firstPerson){point.set(0,0,0);for(const id of ids)point.add(new THREE.Vector3().fromBufferAttribute(position,id));point.multiplyScalar(1/(3*cell));key+=':'+Math.floor(point.x)+','+Math.floor(point.y)+','+Math.floor(point.z);}
   let group=groups.get(key);
   if(!group){group=new Map([...bones].map(bone=>[bone,new THREE.Box3()]));group.vertices=new Set();groups.set(key,group);}
   for(const id of ids){const p=new THREE.Vector3().fromBufferAttribute(position,id);
    group.vertices.add(id);
    for(let j=0;j<4;j++)if(skinWeight.getComponent(id,j)>0){const bone=skinIndex.getComponent(id,j);group.get(bone).expandByPoint(point.copy(p).applyMatrix4(transforms[bone]));}
   }
  }
  for(const group of groups.values())entries.push({mesh,vertices:[...group.vertices],parts:[...group].map(([bone,bounds])=>({bone:mesh.skeleton.bones[bone],corners:corners(bounds)}))});
 });
 const variants=cache.get(actor)||{};variants[firstPerson?'first':'normal']=entries;cache.set(actor,variants);return entries;
}
export function characterScreenRegions(actor,camera,width,height){
 if(!actor.group.visible)return [];
 const firstPerson=actor.clip?.active.value>0.5,regions=[],skins=new Map(),stamp=++skinStamp;
 for(const entry of cache.get(actor)?.[firstPerson?'first':'normal']||prepare(actor,firstPerson)){
  let visible=true;for(let node=entry.mesh;node;node=node.parent)if(!node.visible){visible=false;break;}
  if(!visible)continue;
  box.makeEmpty();
  for(const part of entry.parts){
   matrix.copy(entry.mesh.matrixWorld);if(part.bone)matrix.multiply(entry.mesh.bindMatrixInverse).multiply(part.bone.matrixWorld);
   view.multiplyMatrices(camera.matrixWorldInverse,matrix);
   for(const p of part.corners)box.expandByPoint(point.copy(p).applyMatrix4(view));
  }
  // A conservative component envelope close to the eye can be much wider than
  // the weighted skin itself. Refine only these near-plane groups using exact
  // skinned vertices; retain whole boundary triangles for the clip shader.
  if(entry.vertices&&box.max.z>=-camera.near){
   box.makeEmpty();const mesh=entry.mesh;
   let skin=skins.get(mesh);
   if(!skin){
    const attributes=mesh.geometry.attributes;
    skin=skinCache.get(mesh);
    if(!skin){const count=attributes.position.count;skin={coordinates:new Float64Array(count*3),stamps:new Float64Array(count)};skinCache.set(mesh,skin);}
    const base=new THREE.Matrix4().multiplyMatrices(camera.matrixWorldInverse,mesh.matrixWorld).multiply(mesh.bindMatrixInverse);
    skin.matrices=mesh.skeleton.bones.map((bone,i)=>new THREE.Matrix4().copy(base).multiply(bone.matrixWorld).multiply(mesh.skeleton.boneInverses[i]).multiply(mesh.bindMatrix).elements);
    skin.attributes=attributes;skins.set(mesh,skin);
   }
   const {position,skinIndex,skinWeight}=skin.attributes,xyz=skin.coordinates;
   for(const id of entry.vertices){
    const at=id*3;
    if(skin.stamps[id]!==stamp){
     const x=position.getX(id),y=position.getY(id),z=position.getZ(id);let sx=0,sy=0,sz=0;
     for(let j=0;j<4;j++){const weight=skinWeight.getComponent(id,j);if(weight<=0)continue;
      const m=skin.matrices[skinIndex.getComponent(id,j)];
      sx+=weight*(m[0]*x+m[4]*y+m[8]*z+m[12]);
      sy+=weight*(m[1]*x+m[5]*y+m[9]*z+m[13]);
      sz+=weight*(m[2]*x+m[6]*y+m[10]*z+m[14]);
     }
     xyz[at]=sx;xyz[at+1]=sy;xyz[at+2]=sz;skin.stamps[id]=stamp;
    }
    box.expandByPoint(point.set(xyz[at],xyz[at+1],xyz[at+2]));
   }
  }
  let left=Infinity,right=-Infinity,top=Infinity,bottom=-Infinity;
  const include=p=>{const x=(p.x/p.w+1)*width/2,y=(1-p.y/p.w)*height/2;left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);};
  const points=corners(box).map(p=>new THREE.Vector4(p.x,p.y,p.z,1).applyMatrix4(camera.projectionMatrix));
  for(const p of points)if(p.z+p.w>=0&&p.w>0)include(p);
  for(const [a,b] of edges){const p=points[a],q=points[b],da=p.z+p.w,db=q.z+q.w;
   if((da<0)!==(db<0)){clip.copy(p).lerp(q,da/(da-db));if(clip.w>0)include(clip);}
  }
  const x=Math.max(0,left-12),y=Math.max(0,top-12),endX=Math.min(width,right+12),endY=Math.min(height,bottom+12);
  if(endX>x&&endY>y)regions.push({x,y,width:endX-x,height:endY-y});
 }
 return regions;
}
export function prepareCaptionBounds(actor){prepare(actor,false);prepare(actor,true);}
// Aggregate envelope is useful for diagnostics; placement uses individual
// regions so the gap between two first-person gloves remains available.
export function characterScreenBounds(actor,camera,width,height){
 const regions=characterScreenRegions(actor,camera,width,height);if(!regions.length)return null;
 const x=Math.min(...regions.map(r=>r.x)),y=Math.min(...regions.map(r=>r.y));
 return {x,y,width:Math.max(...regions.map(r=>r.x+r.width))-x,height:Math.max(...regions.map(r=>r.y+r.height))-y};
}
