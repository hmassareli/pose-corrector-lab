from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
anchor="function reviveAux(aux)"
idx=s.index(anchor)
demo="""function demoAux(p){const aux={kind:'smpl'};for(const [name,i] of Object.entries(JOINTS))aux[name]=new THREE.Vector3(...p[i]);for(const [name,v] of Object.entries({spine1:[0,1.05,0],spine2:[0,1.2,0],spine3:[0,1.4,0],left_collar:[-.075,1.43,0],right_collar:[.075,1.43,0],left_eye:[-.035,1.74,.075],right_eye:[.035,1.74,.075],left_foot:[-.19,.05,.24],right_foot:[.19,.05,.09]}))aux[name]=new THREE.Vector3(...v);return aux;}\n"""
s=s[:idx]+demo+s[idx:]
s=s.replace("'fighter-web'}));", "'boxeador'}));")
s=s.replace("motion:a.motion,allowFeet:true,plantGround:true", "motion:a.motion,aux:demoAux(neutralPose()),allowFeet:true,plantGround:true")
s=s.replace("if(keys.has('Space'))f.pose=neutralPose();", "if(keys.has('Space'))f.pose=neutralPose();f.aux=demoAux(f.pose);")
s=s.replace("bot.pose[13][1]-=.28;}", "bot.pose[13][1]-=.28;}bot.aux=demoAux(bot.pose);")
s=s.replace("pose:neutralPose(),lateral:0", "pose:neutralPose(),aux:demoAux(neutralPose()),lateral:0")
s=s.replace("pose:neutralPose(),lateral:0", "pose:neutralPose(),aux:demoAux(neutralPose()),lateral:0")
s=s.replace("const p=worldPoint(f,f.pose[12+h]);a.gloves[h].position.set(...p);", "const hand=a.rig.bones.get(h?'rightHand':'leftHand')?.bone;const p=hand?hand.getWorldPosition(new THREE.Vector3()):new THREE.Vector3(...worldPoint(f,f.pose[12+h]));a.gloves[h].position.copy(p);a.gloves[h].scale.set(1.35,1.25,1.65);")
# Explicit first-person gloves are camera-relative; hit tests still use unfiltered tracked joints.
s=s.replace("renderer.render(scene,camera);if(window.cornerDebug", "if(active&&first&&actors[self]){for(let h=0;h<2;h++){const f=fighters[self],extension=clamp(f.pose[12+h][2]-.3,0,.65),local=new THREE.Vector3(h?.24:-.24,-.25,-.58-extension*.35);actors[self].gloves[h].position.copy(local.applyQuaternion(camera.quaternion).add(camera.position));actors[self].gloves[h].quaternion.copy(camera.quaternion);actors[self].gloves[h].scale.set(1.4,1.3,1.65);}}renderer.render(scene,camera);if(window.cornerDebug")
p.write_text(s,encoding='utf-8')
# Put feedback above play silhouettes, with compact fight-callout styling.
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.css';s=p.read_text(encoding='utf-8')
s += "\n#combatMessage{top:222px;font:700 24px Barlow Condensed;letter-spacing:2px;color:#f4cf90}@media(max-height:720px){#combatMessage{top:205px;font-size:20px}}\n"
p.write_text(s,encoding='utf-8')
