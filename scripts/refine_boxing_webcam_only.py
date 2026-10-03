from pathlib import Path
root=Path(__file__).resolve().parents[1]/'viewer';p=root/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace(" keys=new Set(),sound=", " sound=")
s=s.replace("baseline=null;keys.clear();", "baseline=null;")
a=s.index("window.addEventListener('keydown'");b=s.index('let bridgeReady=false;',a)
s=s[:a]+s[b:]
a=s.index("if(!cameraOn){f.lateral=");b=s.index("f.detected=[];",a)+len("f.detected=[];")
s=s[:a]+"if(!cameraOn||now-lastPoseTime>500){f.lateral=f.radial=0;f.attacks=[];f.detected=[];$('trackingStatus').textContent=cameraOn?'Pose perdida • luta pausada • enquadre o corpo':'Ative a webcam para entrar na luta';return;}if(online&&!fighters[1-self].tracking){$('fightState').textContent='AGUARDANDO WEBCAM';return;}$('fightState').textContent=online?'DUELO ONLINE':'TREINAMENTO';for(const hit of f.detected||[])f.attacks.push({hand:hit.hand,start:now,hit:false,mocap:true});f.detected=[];"+s[b:]
# Remove the old duplicate tail from the replaced keyboard/freshness branches.
s=s.replace("$('trackingStatus').textContent='Pose perdida • golpes suspensos • enquadre o corpo';}else for(const hit of f.detected||[])f.attacks.push({hand:hit.hand,start:now,hit:false,mocap:true});f.detected=[];", "")
s=s.replace("const f=fighters[1];syncAvatar", "const f=fighters[1];f.tracking=!!m.tracking;syncAvatar")
s=s.replace("stun:f.stun,score", "stun:f.stun,tracking:!!f.tracking,score")
s=s.replace("type:'input',avatarId:", "type:'input',tracking:cameraOn&&now-lastPoseTime<500,avatarId:")
s=s.replace("if(!isOnline){self=0;reset();notify('Seu treino começa',1.8);}", "if(!isOnline){self=0;reset();notify('Ative sua webcam',1.8);}if(!cameraOn)$('cameraButton').click();")
s=s.replace("z:clamp(f.z,-2.55,2.55),yaw:f.yaw,hp", "z:clamp(f.z,-2.55,2.55),yaw:f.yaw,tracking:!!f.tracking,hp")
s=s.replace("lastPoseTime=performance.now();const raw", "lastPoseTime=performance.now();fighters[self].tracking=true;const raw")
s=s.replace("cameraOn=false;$('preview').hidden=true", "cameraOn=false;fighters[self].tracking=false;$('preview').hidden=true")
s=s.replace("$('trackingStatus').textContent='Controle por teclado • câmera desligada'", "$('trackingStatus').textContent='Webcam desligada • luta pausada'")
s=s.replace("clock-=dt;for(let", "fighters[self].tracking=true;clock-=dt;for(let")
s=s.replace("aux:f.aux,score:f.score,avatarId", "aux:f.aux,tracking:!!f.tracking,score:f.score,avatarId")
# Automated reviews feed recorded/synthetic poses through this isolated hook, never a player control.
s=s.replace("window.cornerDebug={fighters,actors,frame", "window.cornerDebug={reviewPose:(pose)=>{cameraOn=true;lastPoseTime=performance.now();fighters[self].pose=pose;fighters[self].aux=demoAux(pose);fighters[self].tracking=true;},fighters,actors,frame")
p.write_text(s,encoding='utf-8')
p=root/'boxing.html';s=p.read_text(encoding='utf-8')
s=s.replace('A / D para circular · J / K para golpear · Espaço para defender. Ative a webcam para lutar com seu corpo.', 'Corpo inteiro na câmera. Passos laterais circulam o oponente. Mãos junto ao rosto protegem a guarda. Estenda o braço para golpear.')
s=s.replace('Controle por teclado • câmera desligada','Webcam necessária • aguardando rastreamento').replace(' <kbd>V</kbd>','')
p.write_text(s,encoding='utf-8')
s=(root/'boxing.js').read_text(encoding='utf-8').replace("+' pessoa <kbd>V</kbd>'", "+' pessoa'")
(root/'boxing.js').write_text(s,encoding='utf-8')
