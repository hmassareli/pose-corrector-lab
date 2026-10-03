from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("(location.protocol==='https:'?'wss://'+location.host+'/boxing':'ws://127.0.0.1:8790')", "'wss://corner-relay.lnyx9r.easypanel.host'")
s=s.replace("f.stun});if(i!==self)", "f.stun,score:Number(f.score)||0});if(i!==self)")
s=s.replace("if(online&&self===1)return;", "if(online&&self===1){f.attacks=f.attacks.filter(a=>now-a.start<400);return;}")
s=s.replace("function reset(){finalResult=null;", "function reset(){finalResult=null;baseline=null;keys.clear();")
# Avatar ID is state, never arbitrary URL; loader remains constrained to the registry.
s=s.replace("pose:f.pose,aux:f.aux,score:f.score", "pose:f.pose,aux:f.aux,score:f.score,avatarId:f.avatarId")
s=s.replace("type:'input',pose:fighters[self].pose", "type:'input',avatarId:fighters[self].avatarId,pose:fighters[self].pose")
s=s.replace("const f=fighters[1];f.pose=m.pose;", "const f=fighters[1];syncAvatar(1,m.avatarId);f.pose=m.pose;")
s=s.replace("const f=m.fighters[i];if(!validPose", "const f=m.fighters[i];if(i!==self)syncAvatar(i,f.avatarId);if(!validPose")
s=s.replace("function snapshot(){", "const switching=[false,false];function syncAvatar(i,id){if(!['boxer-prism31','boxeador','fighter-web'].includes(id)||fighters[i].avatarId===id||switching[i])return;switching[i]=true;createActor(i,id).catch(e=>notify('Erro no avatar do oponente')).finally(()=>switching[i]=false);}\nfunction snapshot(){")
# Ensure join uses own chosen avatar regardless of host/guest slot.
s=s.replace("self=m.slot;ready=false;reset();enter(true);", "self=m.slot;ready=false;reset();enter(true);syncAvatar(self,$('avatarSelect').value);")
s=s.replace("const fade=active&&!first&&i===self&&Math.hypot(fighters[0].x-fighters[1].x,fighters[0].z-fighters[1].z)<1.6;", "")
p.write_text(s,encoding='utf-8')
