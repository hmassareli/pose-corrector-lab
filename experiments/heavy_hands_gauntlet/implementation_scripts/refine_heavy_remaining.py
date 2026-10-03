from pathlib import Path
p=Path('viewer/boxing.js');s=p.read_text(encoding='utf-8')
s=s.replace('punchPower, punchTier, PUNCH, safeForce, FightJournal,','punchPower, punchTier, PUNCH, safeForce, FightJournal, capsulePenetration,')
a=s.index('function separateBodies(){');b=s.index('const switching =',a)
s=s[:a]+'''function separateBodies(){
 if(!hitboxes[0]||!hitboxes[1])return;
 const sync=()=>fighters.forEach((f,i)=>{
  const actor=actors[i],box=hitboxes[i];if(!actor||!box)return;
  const dx=f.x-actor.group.position.x,dz=f.z-actor.group.position.z;
  const shift=p=>{p[0]+=dx;p[2]+=dz;};
  shift(box.head.c);shift(box.chin.c);shift(box.body.a);shift(box.body.b);
  box.arms.forEach(c=>{shift(c.a);shift(c.b);});box.gloves.forEach(shift);
  actor.group.position.x=f.x;actor.group.position.z=f.z;actor.group.updateMatrixWorld(true);
 });
 sync();
 const [a,b]=fighters;
 const bodies=hitboxes.map(box=>({...box.body,r:box.body.r-GLOVE_RADIUS+.003}));
 const contact=capsulePenetration(...bodies);
 const pelvisD=Math.hypot(b.x-a.x,b.z-a.z);
 const depth=Math.max(contact.depth,COMBAT.minDistance-pelvisD);
 if(depth<=0)return;
 let dx=contact.normal[0],dz=contact.normal[2],horizontal=Math.hypot(dx,dz);
 if(horizontal<.01){dx=b.x-a.x;dz=b.z-a.z;horizontal=Math.hypot(dx,dz);}
 if(horizontal<.01){dx=Math.sin(a.yaw);dz=Math.cos(a.yaw);horizontal=1;}
 dx/=horizontal;dz/=horizontal;
 // If one root meets a rope boundary, spend the remaining correction on the
 // other fighter. Clamping half of the overlap must not leave bodies crossed.
 const oldAX=a.x,oldAZ=a.z,oldBX=b.x,oldBZ=b.z;
 const move=(f,sign,amount)=>{const x=f.x,z=f.z;f.x=clamp(x+dx*sign*amount,-2.55,2.55);f.z=clamp(z+dz*sign*amount,-2.55,2.55);return (f.x-x)*dx*sign+(f.z-z)*dz*sign;};
 const needed=depth/Math.max(.2,horizontal)+.001;
 const movedA=move(a,-1,needed/2),movedB=move(b,1,needed-movedA);
 if(movedA+movedB<needed)move(a,-1,needed-movedA-movedB);
 sync();
}
''' + s[b:]
p.write_text(s,encoding='utf-8')
p=Path('viewer/boxing_debug_recording.js');s=p.read_text(encoding='utf-8')
s="import { t } from '/static/boxing_i18n.js';\n"+s
replacements={
"'Parar e salvar gravação de debug'":"t('saving')","'Gravar debug: webcam, jogo e esqueletos'":"t('record')",
"'Ative a webcam antes de gravar o debug.'":"t('noCamera')","'Este navegador não oferece gravação de vídeo. Use Chrome ou Edge.'":"t('recordError')",
"'Preparando…'":"t('starting')","'Não foi possível gravar: '+error.message":"t('recordError')",
"'Falha ao iniciar'":"t('recordError')","'Gravação parcial'":"t('recordError')","'Debug salvo'":"t('recordSaved')",
"'Gravação parcial: '+error":"t('recordError')","'Debug salvo: '+this.name":"t('recordSaved')+': '+this.name",
"'Falha ao salvar'":"t('recordError')","'Falha ao salvar debug: '+error.message":"t('recordError')",
"'CORNER DEBUG'":"'HEAVY HANDS DEBUG'","CORNER — gravação":"HEAVY HANDS — gravação"
}
for a,b in replacements.items():s=s.replace(a,b)
# Diagnostic files retain detailed engineering explanations; visible labels are localized.
p.write_text(s,encoding='utf-8')
