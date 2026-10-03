from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js'
s=p.read_text(encoding='utf-8')
def replace(a,b):
    global s
    if a not in s: raise RuntimeError('Missing replacement: '+a[:70])
    s=s.replace(a,b)
replace("resetRetargetFilters} from", "resetRetargetFilters,auxFromSmpl,auxFromPose33} from")
replace("let finalResult=null;", "let finalResult=null;")
replace("function reset(){clock=90;", "function reset(){finalResult=null;clock=90;")
replace("const oldReset=reset; // result lifecycle resets explicitly on new session.\n", "")
replace("fighters[self].aux=e.data.aux;fighters[self].headForward=e.data.headForward;fighters[self].footDirections=e.data.footDirections;", "fighters[self].aux=reviveAux(e.data.aux);fighters[self].headForward=reviveVector(e.data.headForward);fighters[self].footDirections=e.data.footDirections?{left:reviveVector(e.data.footDirections.left),right:reviveVector(e.data.footDirections.right)}:null;")
replace("f.aux=m.aux;", "f.aux=reviveAux(m.aux);")
replace("fighters[i].aux=f.aux;", "fighters[i].aux=reviveAux(f.aux);")
replace("const $=id=>document.getElementById(id), keys=new Set();", "const $=id=>document.getElementById(id), keys=new Set();\nfunction reviveVector(p){if(!p)return null;const v=[p.x??p[0],p.y??p[1],p.z??p[2]];return v.every(Number.isFinite)?new THREE.Vector3(...v):null;}\nfunction reviveAux(aux){if(!aux||typeof aux!=='object')return null;const out={kind:aux.kind};for(const [k,v] of Object.entries(aux)){if(k==='kind')continue;const p=reviveVector(v);if(p)out[k]=p;}return out;}")
replace("a.group.rotation.y=f.yaw;", "a.group.rotation.y=f.yaw;a.group.rotation.z=f.stun>0?Math.sin(now*.026)*.025:0;")
replace("targetCamera.set(a.x,2.65,a.z).addScaledVector(forward,-3.6);targetLook.set((a.x+b.x)/2,.92,(a.z+b.z)/2);", "const side=new THREE.Vector3(forward.z,0,-forward.x);targetCamera.set(a.x,2.85,a.z).addScaledVector(forward,-4.2).addScaledVector(side,.95);targetLook.set((a.x+b.x)/2,1.05,(a.z+b.z)/2).addScaledVector(side,.18);")
replace("if(first){targetCamera.set(a.x,1.68,a.z).addScaledVector(forward,.05);targetLook.set(b.x,1.48,b.z);}", "if(first){const eye=actors[self]?.rig.bones.get('head')?.bone.getWorldPosition(new THREE.Vector3());targetCamera.copy(eye||new THREE.Vector3(a.x,1.68,a.z)).addScaledVector(forward,.12);targetLook.set(b.x,1.55,b.z);}")
replace("f.pose=demoPose(now/1000,a?.hand??-1,k);if(keys.has('Space'))", "f.pose=demoPose(now/1000,a?.hand??-1,k);if(!keys.has('Space')){const idle=1-k;f.pose[12][1]-=.32*idle;f.pose[13][1]-=.32*idle;}if(keys.has('Space'))")
replace("bot.pose=demoPose(now/1000,a?.hand??-1,a?Math.sin(clamp((now-a.start)/260,0,1)*Math.PI):0);", "bot.pose=demoPose(now/1000,a?.hand??-1,a?Math.sin(clamp((now-a.start)/260,0,1)*Math.PI):0);if(Math.sin(now/1600)>.2){bot.pose[12][1]-=.28;bot.pose[13][1]-=.28;}")
replace("clock-=dt;for(let", "clock-=dt;for(let")
# Hide loading actions until assets are available; init controls should not pretend success.
replace("let self=0,", "$('train').disabled=$('online').disabled=true;\nlet self=0,")
replace("loaded=true;$('loadStatus')", "loaded=true;$('train').disabled=$('online').disabled=false;$('loadStatus')")
p.write_text(s,encoding='utf-8')
