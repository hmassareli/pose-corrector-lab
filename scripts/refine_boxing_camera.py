from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("const side=new THREE.Vector3(forward.z,0,-forward.x);targetCamera.set(a.x,2.85,a.z).addScaledVector(forward,-4.2).addScaledVector(side,.95);targetLook.set((a.x+b.x)/2,1.05,(a.z+b.z)/2).addScaledVector(side,.18);", "targetCamera.set(a.x,4.1,a.z).addScaledVector(forward,-4.1);targetLook.set((a.x+b.x)/2,.9,(a.z+b.z)/2);")
s=s.replace("targetLook.set(b.x,1.55,b.z);", "const opponentEye=actors[1-self]?.rig.bones.get('head')?.bone.getWorldPosition(new THREE.Vector3());targetLook.copy(opponentEye||new THREE.Vector3(b.x,1.72,b.z));")
s=s.replace("function setView(){first=$('view').value==='first';", "function setView(){first=$('view').value==='first';camera.fov=first?75:48;camera.updateProjectionMatrix();")
# Neutral solved height differs across asset anatomy. Calibrate once, never rescale crouches.
needle="actors[i]=a;if(previous)"
replacement="updateAvatarPose({model:root,rig:a.rig,pose:neutralPose(),nameToIndex:JOINTS,motion:a.motion,allowFeet:true,plantGround:true,groundY:0});root.updateWorldMatrix(true,true);const headY=a.rig.bones.get('head').bone.getWorldPosition(new THREE.Vector3()).y;const feetY=Math.min(...['leftFoot','rightFoot'].map(n=>a.rig.bones.get(n).bone.getWorldPosition(new THREE.Vector3()).y));root.scale.multiplyScalar(1.72/Math.max(.5,headY-feetY));a.rig=buildAvatarRig(root);a.motion=createAvatarMotion();actors[i]=a;if(previous)"
assert needle in s;s=s.replace(needle,replacement)
# Render only the remote boxer in first person; self gloves remain, eye tracks actual head.
# Camera transitions use wall time; initial view immediately places camera, avoiding lobby swing.
s=s.replace("document.body.classList.add('fighting');", "document.body.classList.add('fighting');if(window.cornerDebug)window.cornerDebug.snapCamera=true;")
s=s.replace("renderer.render(scene,camera);if(!window.cornerDebug?.paused)", "renderer.render(scene,camera);if(window.cornerDebug&&!window.cornerDebug.paused)window.cornerDebug.snapCamera=false;if(!window.cornerDebug?.paused)")
p.write_text(s,encoding='utf-8')
