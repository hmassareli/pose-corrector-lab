from pathlib import Path
p=Path('viewer/boxing.js')
s=p.read_text(encoding='utf-8')
def change(a,b):
 global s
 if a not in s: raise RuntimeError('Missing migration anchor: '+a[:95])
 s=s.replace(a,b)
change('import { BoxingAudio }','import { t, number, language, setLanguage } from "/static/boxing_i18n.js";\nimport { prepareHands, alignWrists } from "/static/boxing_hands.js";\nimport { BoxingAudio }')
change('  punchPower,\n','  punchPower, punchTier, PUNCH, safeForce, FightJournal,\n')
change('import { FootPlanting, solveTwoBone, prepareFeet, levelFeet, soleBottom }','import { solveTwoBone, prepareFeet, soleBottom, groundSoles }')
change('  addSkinnedOutlines,\n','')
change('  sound = new BoxingAudio();','''  sound = new BoxingAudio();
setLanguage(language);
$("language").value=language;
let trackingKey='noCamera';
let peakRecord=safeForce(Number(localStorage.getItem('cornerPeakN')) || 0);
let previousPeak=peakRecord, fightElapsed=0;
const refreshPeak=()=>{
 $("peakRecord").hidden=peakRecord<=0;
 $("peakValue").textContent=number(peakRecord)+' N';
};
const refreshCameraUI=()=>{
 $("train").disabled=!loaded || !cameraOn || !fighters[self].tracking;
 $("online").disabled=!loaded;
 $("lobbyCamera").classList.toggle('connected',cameraOn);
 $("cameraChipText").textContent=t(cameraOn ? (fighters[self].tracking?'cameraOn':trackingKey) : trackingKey);
 $("trackingStatus").textContent=t(trackingKey);
};
function trackStatus(key){trackingKey=key;refreshCameraUI();}
function rememberPeak(forceN){
 const n=safeForce(forceN);
 if(n>peakRecord){peakRecord=n;localStorage.setItem('cornerPeakN',String(n));refreshPeak();}
}
$("language").onchange=()=>{
 setLanguage($("language").value);refreshPeak();refreshCameraUI();setView();
 if(finalResult)renderResult();
};
$("lobbyCamera").onclick=()=> $("cameraButton").click();
$("bodyKg").value=clamp(Number(localStorage.getItem('cornerBodyKg'))||80,40,180);
PUNCH.bodyKg=Number($("bodyKg").value);
$("bodyKg").onchange=()=>{
 PUNCH.bodyKg=clamp(Number($("bodyKg").value)||80,40,180);
 $("bodyKg").value=PUNCH.bodyKg;localStorage.setItem('cornerBodyKg',String(PUNCH.bodyKg));
 fighters[self].detector=new PunchDetector(PUNCH.bodyKg);
};
$("voiceVolume").value=sound.voiceVolume*100;
$("voiceVolume").oninput=()=>sound.setVoiceVolume(Number($("voiceVolume").value)/100);
$("reducedImpact").checked=sound.reducedImpact;
$("reducedImpact").onchange=()=>sound.setReducedImpact($("reducedImpact").checked);
refreshPeak();''')
change('  stats: { clean: 0, chin: 0, maxCombo: 0, fastest: 0, blocked: 0 },','  stats: { clean: 0, chin: 0, maxCombo: 0, fastest: 0, blocked: 0 },\n  journal: new FightJournal(), lowHpSaid: false,')
change('    feet: new FootPlanting(),','')
change('  a.flatFeet = levelFeet(a);','  prepareHands(a);')
a=s.index('  if (localStorage.getItem("cornerToon") !== "off" && localStorage.getItem("cornerOutline")')
b=s.index('  actors[i] = a;',a);s=s[:a]+s[b:]
change(' || mesh.userData.cornerOutline','')
change('"Prism • técnico"','"PRISM"');change('"Titan • peso pesado"','"TITAN"');change('"Fighter • clássico"','"FIGHTER"')
change('notify("Falha ao carregar personagem");','notify(t("loadError"));')
change('  $("train").disabled = $("online").disabled = false;\n  $("loadStatus").textContent = "Lutadores prontos • webcam + NLF";','  $("loadStatus").replaceChildren();\n  refreshCameraUI();')
change('  $("loadStatus").textContent = "Erro ao carregar lutadores: " + e.message;','  $("loadStatus").textContent = t("loadError");\n  console.error(e);')
change('  finalResult = null;\n  effect = null;','  finalResult = null;\n  previousPeak=peakRecord;fightElapsed=0;\n  sound.resetFight();\n  document.body.classList.remove("ear-plug");\n  effect = null;')
for text in ['      footContacts: null,\n','      footVisible: null,\n','      proceduralFeet: false,\n']:change(text,'')
change('if (actors[i]) { actors[i].feet.reset(); actors[i].groundInitialized=false; }','if (actors[i]) { actors[i].groundOffset=null; actors[i].groundInitialized=false; }')
change('sound.start().catch((e) => ($("trackingStatus").textContent = e.message));','sound.start().catch((e) => console.warn(e));')
change('isOnline ? "OPONENTE" : "SPARRING"','isOnline ? "OPPONENT" : "SPARRING"')
change('isOnline ? "Sair da sala" : "Sair do treino"','t("back")')
change('"DUELO ONLINE"','"ONLINE"');change('"TREINAMENTO"','"TRAINING"')
change('    notify("Ative sua webcam", 1.8);','    sound.start().then(()=>sound.say("pressure_guard_up", 10)).catch(console.warn);')
change('  if (cameraOn) $("cameraButton").click();','')
change('"ARENA DE TREINO"','"TRAINING"')
change('    "Câmera: " + (first ? "primeira" : "terceira") + " pessoa";','    t(first ? "first" : "third");')
change('localStorage.getItem("cornerToon") === "off" ? "classic" : localStorage.getItem("cornerOutline") === "on" ? "outline" : "toon";','localStorage.getItem("cornerToon") === "off" ? "classic" : "toon";')
change('  localStorage.setItem("cornerOutline", $("artStyle").value === "outline" ? "on" : "off");','')
change('"Técnico • guarda rápida"','""');change('"Peso pesado • presença"','""');change('"Clássico • old school"','""')
change('  $("fighterStyle").textContent = style;','')
change('  const p = movement.pose;','''  if(!movement || movement.calibrating){
    f.tracking=false;f.detected=[];trackStatus('calibrating');return;
  }
  const p = movement.pose;''')
change('fighters[self].detector.update(p, lastPoseTime)','fighters[self].detector.update(raw, lastPoseTime)')
a=s.index('  f.footContacts = movement.contacts;');b=s.index('\n});',a)
s=s[:a]+'''  trackStatus(movement.framed?'tracking':'showTorso');
  f.tracking=movement.framed;
  refreshCameraUI();'''+s[b:]
change('throw Error("Rastreamento ainda está carregando. Tente novamente.");','throw Error(t("trackerLoading"));')
change('      $("cameraButton").textContent = "Ativar webcam";\n      $("trackingStatus").textContent = "Webcam desligada • luta pausada";','      trackStatus("noCamera");')
change('    actors[self]?.feet.reset();','    if(actors[self]) actors[self].groundOffset=null;')
change('    document.getElementById("trackingStatus").textContent =\n      "Preparando NLF-S • aguarde…";','    trackStatus("starting");')
change('    $("cameraButton").textContent = "Desativar webcam";','    $("cameraButton").textContent = t("webcam");')
change('    $("trackingStatus").textContent =\n      "Aguardando NLF-S • fique inteiro no enquadramento";','    trackStatus("calibrating");')
change('    $("trackingStatus").textContent = "Webcam: " + e.message;','    trackStatus("cameraError");console.warn(e);')
change('  actors[self]?.feet.reset();','  if(actors[self]) actors[self].groundOffset=null;')
change('  notify("Centro e referência da cabeça recalibrados");','  trackStatus("calibrating");')
change('notify("Lutadores prontos", 2)','notify("READY", 2)')
change('notify("Luta pausada", 3)','notify("WAITING", 3)')
# Legacy contacts are never transmitted or used for legs.
import re
s=re.sub(r'^.*f\.footContacts = Array\.isArray.*\n','',s,flags=re.M)
s=re.sub(r'^.*f\.footVisible = Array\.isArray.*\n','',s,flags=re.M)
s=re.sub(r'^.*fighters\[i\]\.footContacts = Array\.isArray.*\n','',s,flags=re.M)
s=re.sub(r'^.*fighters\[i\]\.footVisible = Array\.isArray.*\n','',s,flags=re.M)
change('              speed: clamp(Number(a.speed) || 2.2, COMBAT.minSpeed, 6),','''              speed: clamp(Number(a.speed) || 0, 0, 12),
              forceN: safeForce(Number(a.forceN)),
              journalIndex:f.journal.attempt({hand:a.hand,forceN:safeForce(Number(a.forceN)),speed:Number(a.speed)||0},fightElapsed),
              mocap:true,''')
# authoritative journal arrives before peer finish
change('        if (f.stats && typeof f.stats === "object")','''        if(Array.isArray(f.journal)){
          fighters[i].journal.entries=f.journal.filter(e=>Number.isFinite(e.t)&&Number.isFinite(e.forceN)).slice(-4000).map(e=>({...e,forceN:safeForce(e.forceN)}));
          fighters[i].journal.maxComboForce=Number(f.journalMeta?.maxComboForce)||0;
          fighters[i].journal.damageReceived=Number(f.journalMeta?.damageReceived)||0;
          fighters[i].journal.receivedPeak=safeForce(Number(f.journalMeta?.receivedPeak));
          if(i===self) for(const row of fighters[i].journal.entries) if(row.landed)rememberPeak(row.forceN);
        }
        fightElapsed=Number(m.elapsed)||fightElapsed;
        if (f.stats && typeof f.stats === "object")''')
change('    $("roomStatus").textContent = s;\n    $("networkStatus").textContent = s.toUpperCase();','''    const key=/erro|error|falha/i.test(s)?'connectionError':/descon|discon/i.test(s)?'disconnected':/conectando|connecting/i.test(s)?'connecting':/aguard|waiting/i.test(s)?'waiting':'joined';
    $("roomStatus").textContent = t(key);
    $("networkStatus").textContent = key==='joined'?'ONLINE':'WAITING';''')
change('"Use ws:// ou wss:// e código com 3–24 letras/números."','t("roomInvalid")')
change('    sound.ko();','''    sound.ko(victim===self);
    sound.say("ko_k_o",100);
    if(victim===self){sound.earPlug(4);if(!sound.reducedImpact)document.body.classList.add('ear-plug');}''')
change('banner("K.O.!",','banner("K.O.",')
change('result.winner === null ? "EMPATE!" : "FIM DE LUTA"','result.winner === null ? "DRAW" : "TIME"')
a=s.index('  $("resultTitle").textContent =',s.index('function finish'))
b=s.index('  if (online && self === 0 && broadcast)',a)
s=s[:a]+'''  renderResult();
'''+s[b:]
change('notify("Erro no avatar do oponente")','notify(t("peerError"))')
change('    clock,\n    round,\n    effect,','    clock,\n    round,\n    elapsed:fightElapsed,\n    effect,')
change('      stats: f.stats,','''      stats: f.stats,
      journal: f.journal.entries,
      journalMeta: {maxComboForce:f.journal.maxComboForce,damageReceived:f.journal.damageReceived,receivedPeak:f.journal.receivedPeak},''')
s=re.sub(r'^.*footContacts: f\.footContacts,?\n','',s,flags=re.M)
s=re.sub(r'^.*footVisible: f\.footVisible,?\n','',s,flags=re.M)
a=s.index('const WORDS =');b=s.index('const hudSide',a);s=s[:a]+s[b:]
a=s.index('function popWord(');b=s.index('function showCombo(',a)
s=s[:a]+'''function popWord(pos,kind,forceN){
 const tier=punchTier(forceN), context={chin:'ON THE CHIN',counter:'COUNTER',finisher:'FINISHER',guard:'BLOCKED',arm:'BLOCKED',body:''}[kind]||'';
 const text=context||tier.label;if(!text)return;
 const v=new THREE.Vector3(...pos).project(camera);
 if(v.z>1||Math.abs(v.x)>1.2||Math.abs(v.y)>1.2)return;
 const layer=$("fxLayer");if(layer.childElementCount>4)layer.firstElementChild.remove();
 const word=document.createElement('span');word.className='pow pow-'+tier.id;
 word.textContent=text;
 if(!context&&forceN>=PUNCH.tierScaleN*.75){const small=document.createElement('small');small.textContent=number(forceN)+' N';word.append(small);}
 word.style.left=clamp(((v.x+1)/2)*innerWidth,80,innerWidth-80)+'px';
 word.style.top=clamp(((1-v.y)/2)*innerHeight,160,innerHeight-80)+'px';
 word.addEventListener('animationend',()=>word.remove());layer.append(word);
}
function showPower(i,forceN){
 const side=hudSide(i),power=punchPower(forceN),tier=punchTier(forceN);
 $("pow"+side).style.width=Math.round(power*100)+'%';
 $("pow"+side).parentElement.dataset.level=tier.id;
 $("powLabel"+side).textContent=tier.label;
 powerShownAt[side]=performance.now();
}
''' + s[b:]
change('if (!(n >= 2))','if (!(n >= 3))')
change('el.innerHTML = "<b>" + n + "</b><span>GOLPES</span>";','''el.innerHTML = "<b>" + n + "</b><span>HITS · "+(n>=7?"UNSTOPPABLE":"COMBO")+"</span>";
  if(i===self){if(n===3)sound.say("combo_combo",20);else if(n===5)sound.say("combo_keep_it_going",20);else if(n===7)sound.say("combo_unstoppable",20);}''')
change('const kind = WORDS[hit?.kind] ? hit.kind : blocked ? "guard" : hit?.head === false ? "body" : "clean";','const kind = hit?.kind || (blocked ? "guard" : hit?.head === false ? "body" : "clean");')
change('  const power = clamp(Number(hit?.power ?? 0.5) || 0, 0, 1);','  const forceN=safeForce(Number(hit?.forceN)||0),tier=punchTier(forceN),power=punchPower(forceN);')
change('  const big = kind === "chin" || kind === "finisher";','  const big = kind === "chin" || kind === "finisher" || tier.id === "devastador";')
change('sound.impact({ kind, power, head: hit?.head !== false });','sound.impact({ kind, power, tier:tier.id, head: hit?.head !== false });')
change('  if (kind === "arm" && attacker !== null && [0, 1].includes(hit?.hand))\n    fighters[attacker].blockHold = { hand: hit.hand, guard: [0, 1].includes(hit.arm) ? hit.arm : hit.hand, start: vclock, point: null };','''  if (attacker !== null && [0,1].includes(hit?.hand))
    fighters[attacker].blockHold={hand:hit.hand,guard:hit.arm,start:performance.now(),point:null,contact:pos.slice(),dir,blocked,victim};
  if(attacker===self&&!blocked&&forceN>=PUNCH.minN)rememberPeak(forceN);''')
change('popWord(pos, kind, power)','popWord(pos, kind, forceN)')
change('showPower(attacker, power)','showPower(attacker, forceN)')
a=s.index('  if (hit?.dizzy && victim !== null)');b=s.index('\n}\n// Sparring',a)
s=s[:a]+'''  if(hit?.lowHp){sound.say(victim===self?'pressure_he_s_got_you':'hit_he_s_hurt',70);}
  if(hit?.dizzy && victim!==null){
    banner('ROCKED','dizzy',1400);
    sound.say(victim===self?['pressure_you_re_hurt','pressure_stay_up','pressure_hold_it']: 'hit_he_s_rocked',80);
  }else if(kind==='arm'||kind==='guard')notify('BLOCKED',.7);
  else if(kind==='chin')notify('ON THE CHIN',.9);
  else if(kind==='counter')notify('COUNTER',.9);
  else if(kind==='finisher')notify('FINISHER',.9);
  else if(hit?.weakened)notify(victim===self?'LIVER SHOT · WEAKENED':'LIVER SHOT',1);
  if(attacker===self&&!blocked){
    if(kind==='chin')sound.say('hit_clean',60);
    else if(kind==='finisher')sound.say('hit_finish_it',60);
    else if(kind==='counter')sound.say(['counter_counter','counter_caught_him'],60);
    else if(tier.id==='forte')sound.say('hit_good',40);
    else if(tier.id==='pesado')sound.say('hit_heavy',40);
    else if(tier.id==='devastador')sound.say('hit_brutal',40);
  }
''' + s[b:]
# Bot animation remains mocap; attacks are detected/measured by the same physics.
s=re.sub(r'^.*bot\.attacks\.push.*\n','',s,flags=re.M)
change('  bot.footContacts = [true, true];\n  bot.footVisible = [false, false];\n  bot.proceduralFeet = true;','  bot.detected=bot.detector.update(bot.pose.map(p=>worldPoint(bot,p)),now);')
a=s.index('    $("trackingStatus").textContent = cameraOn',s.index('function simulate'));b=s.index('    return;',a)
s=s[:a]+'''    trackStatus(!cameraOn?'noCamera':trackingKey==='calibrating'?'calibrating':'trackingLost');
'''+s[b:]
change('"AGUARDANDO WEBCAM"','"WAITING FOR CAMERA"')
change('"ROUND " + round + " • LUTE!"','"ROUND " + round')
change('      speed: hit.speed,\n      previous:', '      speed: hit.speed,\n      forceN:hit.forceN, stroke:hit,\n      journalIndex:f.journal.attempt(hit,fightElapsed),\n      previous:')
change('sound.whoosh(punchPower(hit.speed));','sound.whoosh(punchPower(hit.forceN));')
change('showPower(self, punchPower(hit.speed));','showPower(self, hit.forceN);')
change('    updateBot(fighters[1], fighters[0], now, dt);','''    updateBot(fighters[1], fighters[0], now, dt);
    const bot=fighters[1];
    for(const hit of bot.detected||[])bot.attacks.push({hand:hit.hand,start:now,hit:false,mocap:true,speed:hit.speed,forceN:hit.forceN,stroke:hit,journalIndex:bot.journal.attempt(hit,fightElapsed)});
    bot.detected=[];''')
change('  clock -= dt;','  clock -= dt;fightElapsed+=dt;')
change('      if (atk.mocap && i === self)\n        atk.speed = Math.max(atk.speed || 0, a.detector.speed[atk.hand] || 0);','''      if(atk.stroke){atk.forceN=atk.stroke.forceN;atk.speed=atk.stroke.speed;}
      if(atk.forceN<PUNCH.minN)continue;
      if(atk.journalIndex===undefined)atk.journalIndex=a.journal.attempt(atk,fightElapsed);''')
change('      const open = b.dizzy > 0 || b.recoil > 0;','')
change('      const res = mesh\n        ? resolvePunchBox(previous, current, hitboxes[1 - i], { arms: !open })\n        : resolvePunch(previous, current, b.pose, (p) => worldPoint(b, p), { arms: !open });','''      // Fight collision exclusively uses the visible gloves/forearms, even\n      // during dizziness. If a rendered avatar is absent, suspend collision.\n      const res=mesh?resolvePunchBox(previous,current,hitboxes[1-i]):null;''')
change('      const speed = clamp(atk.speed || 2.2, COMBAT.minSpeed, 6),\n        power = punchPower(speed);\n      const guard = res.target === "head" && !open && guarded(b.pose);','      const speed=clamp(atk.speed||0,0,12),forceN=safeForce(atk.forceN),power=punchPower(forceN);\n      const guard=false;')
change('      const damage = punchDamage({\n        speed,','      const damage = punchDamage({\n        forceN,')
change('      b.hp = Math.max(0, b.hp - damage);','''      const beforeHp=b.hp;
      b.hp = Math.max(0, b.hp - damage);
      const lowHp=beforeHp>25&&b.hp<=25&&!b.lowHpSaid;
      if(lowHp)b.lowHpSaid=true;
      b.journal.damageReceived+=damage;b.journal.receivedPeak=Math.max(b.journal.receivedPeak,forceN);''')
change('      if (!online && i === self) onBotHit(b, blocked);','''      a.journal.land(atk.journalIndex,{forceN,target:res.target,combo:a.combo,blocked,speed});
      if(!blocked&&i===self)rememberPeak(forceN);
      if(!blocked){
        const away=new THREE.Vector3(b.x-a.x,0,b.z-a.z).normalize();
        b.push ??= {x:0,z:0};
        const kick=Math.min(.65,.12+forceN/3000)*(kind==='finisher'?1.4:1);
        b.push.x+=away.x*kick;b.push.z+=away.z*kick;
      }
      if (!online && i === self) onBotHit(b, blocked);''')
change('        damage,\n        victim:','        damage,\n        forceN,\n        lowHp,\n        victim:')
change('reason: "Nocaute"','reason: "knockout"')
change('      round++;\n      clock = 90;','      round++;\n      for(const f of fighters)f.lowHpSaid=false;\n      clock = 90;')
change('reason: "Decisão por pontos"','reason: "decision"')
# Body separation after each movement, not by arbitrary pelvis distance.
change('    for (const atk of a.attacks) {','''    if(a.push){a.x=clamp(a.x+a.push.x*dt,-2.55,2.55);a.z=clamp(a.z+a.push.z*dt,-2.55,2.55);a.push.x*=Math.exp(-dt*9);a.push.z*=Math.exp(-dt*9);}
    separateBodies();
    for (const atk of a.attacks) {''')
# contact hold is in wall time (110ms + 80ms release); exact point from rendered collision.
a=s.index('function applyBlockHold(i)');b=s.index('// Direction-only arm',a)
s=s[:a]+'''function applyBlockHold(i){
 const f=fighters[i],hold=f.blockHold,a=actors[i];
 if(!hold||!a)return;
 const age=(performance.now()-hold.start)/1000;
 if(age>.19){f.blockHold=null;return;}
 const side=hold.hand?'right':'left',bone=n=>a.rig.bones.get(side+n)?.bone;
 const arm=bone('Arm'),fore=bone('ForeArm'),hand=bone('Hand');
 if(!arm||!fore||!hand)return;
 const live=hand.getWorldPosition(new THREE.Vector3());
 if(!hold.point){
   const dir=new THREE.Vector3(...(hold.dir||[0,0,1])).normalize();
   const offset=new THREE.Vector3(...hold.contact).sub(live).clampLength(0,.14);
   hold.point=live.clone().add(offset).addScaledVector(dir,-.025);
   hold.back=arm.getWorldPosition(new THREE.Vector3()).sub(hold.point).normalize();
 }
 const target=hold.point.clone();
 const release=clamp((age-.11)/.08,0,1);
 target.lerp(live,release*release*(3-2*release));
 solveTwoBone(arm,fore,hand,target,a.group.getWorldDirection(new THREE.Vector3()));
 alignWrists(a);
}
''' + s[b:]
change('    const rotation = s.hand.getWorldQuaternion(new THREE.Quaternion());','')
change('    s.hand.quaternion.copy(s.hand.parent.getWorldQuaternion(new THREE.Quaternion()).invert().multiply(rotation));','')
change('  });\n}\nfunction renderActor','  });\n  alignWrists(a);\n}\nfunction renderActor')
change('    plantGround: !f.footContacts || !a.groundInitialized,','    plantGround: true,')
a=s.index('  if (f.footContacts && !a.groundInitialized)');b=s.index("  debugRecorder.stage(i, 'retarget'",a);s=s[:a]+s[b:]
change('    a.feet.apply(a,f,now);','    groundSoles(a,dt);')
change('  a.guardContact.apply(a, now);','  a.guardContact.apply(a, now);\n  alignWrists(a);')
a=s.index('    if (n.userData.cornerOutline) {');b=s.index('    n.castShadow',a);s=s[:a]+s[b:]
change('"CORNER ★ WEBCAM BOXING"','"HEAVY HANDS"')
change('  if (lobby && innerWidth > 900) camera.setViewOffset(innerWidth, innerHeight, -innerWidth * 0.16, 0, innerWidth, innerHeight);','  if (lobby && camera.view?.enabled) camera.clearViewOffset();')
change('      sound.setMusicMode("result");','      sound.setMusicMode("result");\n      if(finalResult?.ko)sound.say(["ko_it_s_over","ko_finished"],90);')
change('    const angle = 0.8 + now * 0.000045;\n    targetCamera.set(Math.cos(angle) * 10.4, 4.1, Math.sin(angle) * 10.4);\n    camera.position.lerp(targetCamera, 0.025);\n    camera.lookAt(0, 0.8, 0);','''    const a=fighters[self],angle=Math.sin(now*.00012)*.13;
    targetCamera.set(a.x+Math.sin(angle)*3.9,1.7,a.z+Math.cos(angle)*3.9);
    camera.position.lerp(targetCamera,.06);
    camera.lookAt(a.x, .8, a.z);
    actors[1-self].group.visible=false;''')
change('  const cinematic = ko && !$("result").open;','  actors.forEach(a=>{if(a)a.group.visible=true;});\n  const cinematic = ko && !$("result").open;')
change('sound.enabled ? "♪ Clique para ligar a música" : "♪ Som desligado • ligar"','t(sound.enabled ? "soundOn" : "soundOff")')
change('["dizzy", "TONTO!"]','["dizzy", "ROCKED"]');change('["open", "GUARDA ABERTA"]','["open", "OPEN"]');change('["weak", "SEM FÔLEGO"]','["weak", "WEAKENED"]');change('["stun", "ATORDOADO"]','["stun", "STUNNED"]');change('["guard", "GUARDA ALTA"]','["guard", "GUARD"]');change('["ready", "EM COMBATE"]','["ready", "READY"]')
change('return { hand: a.hand, speed: a.speed || 0 };','return { hand: a.hand, speed: a.speed || 0,forceN:a.forceN || 0 };')
s=re.sub(r'^.*footContacts: fighters\[self\]\.footContacts,?\n','',s,flags=re.M)
s=re.sub(r'^.*footVisible: fighters\[self\]\.footVisible,?\n','',s,flags=re.M)
change('    cameraOn = true;\n    lastPoseTime = performance.now();','    cameraOn = true;\n    trackingKey="tracking";\n    lastPoseTime = performance.now();')

change('  presentation: () => ({','  journal: () => fighters[self].journal,\n  peak:()=>({current:peakRecord,previous:previousPeak}),\n  separateBodies,\n  presentation: () => ({')
# Render result from the same authoritative journal used by gameplay.
insert=s.index('const switching =')
s=s[:insert]+'''function renderResult(){
 const result=finalResult;if(!result)return;
 const j=fighters[self].journal,summary=j.summary(fightElapsed);
 $("resultTitle").textContent=t(result.winner===null?'draw':result.winner===self?'victory':'defeat');
 $("result").dataset.outcome=result.winner===null?'draw':result.winner===self?'win':'loss';
 $("resultText").textContent=t(result.ko?'knockout':'decision');
 const dash='–',n=(v,unit=' N',digits=0)=>v===null?dash:number(v,digits)+unit;
 const newPeak=summary.peak!==null&&summary.peak>previousPeak;
 const cards=[
  [n(summary.peak),'peak',summary.peak!==null?'≈ '+number(summary.peak/9.81)+' kgf':''],
  [summary.total===null?dash:number(summary.total/1000,1)+' kN','total',''],
  [n(summary.average),'average',''],
  [summary.accuracy===null?dash:number(summary.accuracy*100)+'%','accuracy',summary.attempts?summary.hits+' '+t('of')+' '+summary.attempts:'']
 ];
 $("resultStats").innerHTML=cards.map(([value,key,detail],i)=>'<div title="'+t('forceTip')+'" class="'+(i===0&&newPeak?'new-peak':'')+'"><b>'+value+'</b><span>'+t(key)+'</span><em>'+detail+(i===0&&newPeak?' · NEW PEAK':'')+'</em></div>').join('');
 const support=[['headPeak',n(summary.headPeak)],['bodyPeak',n(summary.bodyPeak)],['combo',summary.maxCombo+' HITS · '+n(summary.maxComboForce)],['fastest',n(summary.fastest,' m/s',1)],['chin',fighters[self].stats.chin],['blocks',fighters[self].stats.blocked],['perMinute',number(summary.perMinute,1)],['damageReceived',number(summary.damageReceived,1)],['receivedPeak',n(summary.receivedPeak)]];
 for(const id of ['forte','pesado','devastador'])support.push([PUNCH.tiers.find(t=>t.id===id).label,summary.tiers[id]]);
 if(newPeak)support.push(['previousPeak',previousPeak>0?n(previousPeak):dash]);
 $("resultSupport").innerHTML='<div class="stat-support">'+support.map(([key,value])=>'<span>'+t(key)+'<b>'+value+'</b></span>').join('')+'</div>';
 const max=Math.max(1,...j.entries.map(e=>e.forceN)),duration=Math.max(1,fightElapsed,...j.entries.map(e=>e.t));
 $("resultTimeline").replaceChildren();
 const peakIndex=j.entries.findIndex(e=>e.landed&&e.forceN===summary.peak);
 j.entries.forEach((e,i)=>{
  const bar=document.createElement('span');bar.className='bar'+(!e.landed?' miss':'')+(newPeak&&i===peakIndex?' peak':'');
  bar.dataset.tier=e.tier;bar.style.height=Math.max(2,e.forceN/max*85)+'%';bar.style.left=Math.min(99,e.t/duration*99)+'%';bar.style.width=Math.max(.3,Math.min(2,60/Math.max(1,j.entries.length)))+'%';
  bar.title=number(e.t,1)+' s · '+n(e.forceN)+' · '+t(e.blocked?'blocked':e.landed?'hit':'miss');
  $("resultTimeline").append(bar);
 });
}
function separateBodies(){
 if(!hitboxes[0]||!hitboxes[1])return;
 const a=fighters[0],b=fighters[1];
 // Chest/pelvis capsules are measured in render space, excluding glove radius.
 const center=i=>hitboxes[i].body.a.map((v,k)=>(v+hitboxes[i].body.b[k])/2);
 const ca=center(0),cb=center(1),dx=cb[0]-ca[0],dz=cb[2]-ca[2],d=Math.hypot(dx,dz);
 const required=Math.max(COMBAT.minDistance,hitboxes[0].body.r+hitboxes[1].body.r-2*GLOVE_RADIUS+.006);
 const overlap=required-d;if(overlap<=0)return;
 const ux=d>.001?dx/d:Math.sin(a.yaw),uz=d>.001?dz/d:Math.cos(a.yaw);
 a.x=clamp(a.x-ux*overlap/2,-2.55,2.55);a.z=clamp(a.z-uz*overlap/2,-2.55,2.55);
 b.x=clamp(b.x+ux*overlap/2,-2.55,2.55);b.z=clamp(b.z+uz*overlap/2,-2.55,2.55);
 // Move current volumes with roots so subsequent ticks never use stale centers.
 [a,b].forEach((f,i)=>{
  const actor=actors[i];if(!actor)return;
  const shiftX=f.x-actor.group.position.x,shiftZ=f.z-actor.group.position.z;
  const shift=p=>{p[0]+=shiftX;p[2]+=shiftZ;};
  const box=hitboxes[i];shift(box.head.c);shift(box.chin.c);shift(box.body.a);shift(box.body.b);
  box.arms.forEach(c=>{shift(c.a);shift(c.b);});box.gloves.forEach(shift);
  actor.group.position.x=f.x;actor.group.position.z=f.z;actor.group.updateMatrixWorld(true);
 });
}
''' + s[insert:]
p.write_text(s,encoding='utf-8')
print('Game integration migrated.')

