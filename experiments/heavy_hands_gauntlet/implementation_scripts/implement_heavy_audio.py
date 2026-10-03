from pathlib import Path
p=Path('viewer/boxing_audio.js');s=p.read_text(encoding='utf-8')
def change(a,b):
 global s
 assert a in s,a[:90]
 s=s.replace(a,b)
s="export const VOICE_FX={tail:1.4,preDelay:.035,wet:.2,doubleDelay:.018,doubleDetune:-12,doubleGain:.316,bassDb:3,highCut:9000,gap:3.2};\n"+s
change('    this.buffers = {};','''    this.voiceVolume=Number(localStorage.getItem('cornerVoice')??.85);
    this.reducedImpact=localStorage.getItem('cornerReducedImpact')==='on';
    this.voiceLog=[];this.voiceNext=0;this.voicePending=null;
    this.earUntil=0;
    this.buffers = {};''')
change('      this.noise = noise;','''      this.noise = noise;
      this.worldFilter=this.ctx.createBiquadFilter();
      this.worldFilter.type='lowpass';this.worldFilter.frequency.value=18000;this.worldFilter.Q.value=.7;
      this.worldGain=this.ctx.createGain();this.worldGain.gain.value=1;
      this.worldFilter.connect(this.worldGain);this.worldGain.connect(this.master);
      this.voiceBus=this.ctx.createGain();this.voiceBus.gain.value=this.voiceVolume;
      this.voiceBass=this.ctx.createBiquadFilter();this.voiceBass.type='lowshelf';this.voiceBass.frequency.value=120;this.voiceBass.gain.value=VOICE_FX.bassDb;
      this.voiceBass.connect(this.voiceBus);
      this.voiceDelay=this.ctx.createDelay(.2);this.voiceDelay.delayTime.value=VOICE_FX.preDelay;
      this.voiceReverb=this.ctx.createConvolver();
      const impulse=this.ctx.createBuffer(2,Math.ceil(this.ctx.sampleRate*VOICE_FX.tail),this.ctx.sampleRate);
      let seed=7331;
      for(let c=0;c<2;c++)for(let i=0;i<impulse.length;i++){seed=(seed*16807)%2147483647;impulse.getChannelData(c)[i]=(seed/1073741823-1)*Math.exp(-i/(this.ctx.sampleRate*.26));}
      this.voiceReverb.buffer=impulse;
      this.voiceTailCut=this.ctx.createBiquadFilter();this.voiceTailCut.type='lowpass';this.voiceTailCut.frequency.value=VOICE_FX.highCut;
      this.voiceWet=this.ctx.createGain();this.voiceWet.gain.value=VOICE_FX.wet;
      this.voiceBass.connect(this.voiceDelay);this.voiceDelay.connect(this.voiceReverb);this.voiceReverb.connect(this.voiceTailCut);this.voiceTailCut.connect(this.voiceWet);this.voiceWet.connect(this.voiceBus);
      this.voiceBus.connect(this.worldFilter);''')
change('this.musicGain.connect(this.master)','this.musicGain.connect(this.worldFilter)')
change('this.crowdGain.connect(this.master)','this.crowdGain.connect(this.worldFilter)')
change('filter.connect(this.master)','filter.connect(this.worldFilter)')
change('} else gain.connect(this.master);','} else gain.connect(this.worldFilter);')
# envelope/tone allow bypass for tinnitus/heartbeat only
change('envelope(node, peak, attack, decay, at = this.ctx.currentTime)','envelope(node, peak, attack, decay, at = this.ctx.currentTime, bypass = false)')
change('    gain.connect(this.master);','    gain.connect(bypass ? this.master : this.worldFilter);')
# noiseBurst replacement accidentally bypass undefined; its chain must always world
a=s.index('  noiseBurst(');b=s.index('  tone(',a)
chunk=s[a:b].replace('gain.connect(bypass ? this.master : this.worldFilter);','gain.connect(this.worldFilter);')
s=s[:a]+chunk+s[b:]
change('tone(type, from, to, peak, attack, decay, at = this.ctx.currentTime)','tone(type, from, to, peak, attack, decay, at = this.ctx.currentTime, bypass = false)')
change('this.envelope(osc, peak, attack, decay, at);','return this.envelope(osc, peak, attack, decay, at, bypass);')
change('["punch1", "punch2", "punch3", "bell", "crowd"]','["punch1", "punch2", "punch3", "punch_heavy", "punch_super", "bell", "crowd"]')
change('throw Error("Som indisponível: " + name)','throw Error("Audio unavailable: " + name)')
change('    await this.loading;','''    await this.loading;
    if(!this.voiceLoading)this.voiceLoading=fetch('/assets/boxing_audio/victor_clips/manifest.json').then(r=>r.json()).then(m=>Promise.all(m.clips.map(async c=>{
      const response=await fetch('/assets/boxing_audio/victor_clips/'+c.file);
      if(response.ok)this.buffers[c.name]=await this.ctx.decodeAudioData(await response.arrayBuffer());
    })));
    await this.voiceLoading;''')
change('    this.bell();\n    if (!this.crowd)','    if (!this.crowd)')
change('    if (!this.live()) return;\n    this.tone("sine", 3900','    if (!this.live() || this.reducedImpact) return;\n    this.tone("sine", 3900')
change('    this.hurt = Math.max(this.hurt, amount);','    if(this.reducedImpact)return;\n    this.hurt = Math.max(this.hurt, amount);')
change('impact({ kind = "clean", power = 0.5, head = true } = {})','impact({ kind = "clean", power = 0.5, head = true, tier = "solido" } = {})')
change('    this.play("punch" + (1 + Math.floor(Math.random() * 3)), blocked ? 0.3 : 0.45 + power * 0.25, blocked, blocked ? 0.85 : 1);','''    const sample=!blocked&&tier==='devastador'?'punch_super':!blocked&&tier==='pesado'?'punch_heavy':'punch'+(1+Math.floor(Math.random()*3));
    this.lastImpactSample=sample;
    this.play(sample,blocked?.22:.24+power*.46,blocked,blocked?.85:1);
    if(tier==='devastador')this.duck=Math.max(this.duck,.35);''')
change('  heartbeat() {','  heartbeat(bypass = false) {')
change('0.28, 0.01, 0.12, now);','0.28, 0.01, 0.12, now, bypass);')
change('0.2, 0.01, 0.12, now + 0.2);','0.2, 0.01, 0.12, now + 0.2, bypass);')
change('  ko() {\n    this.roar(1);\n    for (let i = 0; i < 3; i++) this.play("bell", 0.5, false, 1, i * 0.32);','''  ko(loser = false) {
    this.roar(loser?.05:1);
    for (let i=0;i<(loser?1:3);i++)this.play("bell",loser?.18:.5,loser,1,i*.32);
    if(loser&&this.live())this.tone('sine',55,45,.4,.008,.4,this.ctx.currentTime+.8);''')
change('      const rate = s.wobble ?','      const rate = (s.wobble || this.ctx.currentTime<this.earUntil) ?')
change('      this.musicFilter.frequency.setTargetAtTime(18000 * Math.pow(350 / 18000, muffle), now, muffle > 0.5 ? 0.08 : 0.3);','''      this.musicFilter.frequency.setTargetAtTime(18000,now,.1);
      if(now>=this.earUntil) {
        const audibleMuffle=this.reducedImpact?0:muffle;
        this.worldFilter.frequency.setTargetAtTime(18000*Math.pow(350/18000,audibleMuffle),now,audibleMuffle>.5?.025:.3);
      }''')
change('0.055 + this.excitement * 0.16,','(this.ctx.currentTime<this.earUntil?.018:.055) + this.excitement * .16,')
change('  stop() {\n    this.active = false;','  stop() {\n    this.resetFight();\n    this.active = false;')
a=s.index('  // Streamed')
s=s[:a]+'''  setVoiceVolume(v){this.voiceVolume=Math.max(0,Math.min(1,v));localStorage.setItem('cornerVoice',String(this.voiceVolume));if(this.voiceBus)this.voiceBus.gain.setTargetAtTime(this.voiceVolume,this.ctx.currentTime,.03);}
  setReducedImpact(v){this.reducedImpact=v;localStorage.setItem('cornerReducedImpact',v?'on':'off');if(v)this.clearEarPlug();}
  clearEarPlug(){
    if(!this.ctx)return;
    const now=this.ctx.currentTime;this.earUntil=0;
    this.worldFilter.frequency.cancelScheduledValues(now);this.worldFilter.frequency.setValueAtTime(18000,now);
    this.worldGain.gain.cancelScheduledValues(now);this.worldGain.gain.setValueAtTime(1,now);
    for(const node of this.earNodes||[])try{node.stop();}catch{}
    this.earNodes=[];this.setVoiceVolume(this.voiceVolume);
  }
  earPlug(seconds=4){
    if(!this.live()||this.reducedImpact)return false;
    const now=this.ctx.currentTime,duration=Math.min(4,Math.max(1,seconds));this.earUntil=now+duration;
    const frequency=this.worldFilter.frequency,gain=this.worldGain.gain;
    frequency.cancelScheduledValues(now);frequency.setValueAtTime(18000,now);frequency.exponentialRampToValueAtTime(300,now+.08);
    frequency.setValueAtTime(300,now+1);frequency.exponentialRampToValueAtTime(18000,now+duration);
    gain.cancelScheduledValues(now);gain.setValueAtTime(1,now);gain.exponentialRampToValueAtTime(.126,now+.06);
    gain.setValueAtTime(.126,now+1);gain.exponentialRampToValueAtTime(1,now+duration);
    this.voiceBus.gain.setValueAtTime(this.voiceVolume*2,now);this.voiceBus.gain.setValueAtTime(this.voiceVolume,now+duration);
    // The ringing/heart bypass the world bus; <= -30 dB, less than four seconds.
    const ring=this.ctx.createOscillator(),amp=this.ctx.createGain(),lfo=this.ctx.createOscillator(),mod=this.ctx.createGain();
    ring.frequency.value=3900;amp.gain.setValueAtTime(.0001,now);amp.gain.exponentialRampToValueAtTime(.025,now+.03);amp.gain.exponentialRampToValueAtTime(.0001,now+Math.min(3.6,duration));
    lfo.frequency.value=6;mod.gain.value=.0015;lfo.connect(mod);mod.connect(amp.gain);ring.connect(amp);amp.connect(this.master);
    ring.start(now);lfo.start(now);ring.stop(now+Math.min(3.7,duration));lfo.stop(now+Math.min(3.7,duration));this.earNodes=[ring,lfo];
    ring.onended=()=>{ring.disconnect();amp.disconnect();lfo.disconnect();mod.disconnect();};
    for(let i=0;i<3;i++){const at=now+i;this.tone('sine',62,40,.2,.01,.12,at,true);this.tone('sine',58,38,.12,.01,.12,at+.2,true);}
    return true;
  }
  resetFight(){
    clearTimeout(this.voiceTimer);this.voicePending=null;this.voiceNext=0;
    for(const node of this.voiceNodes||[])try{node.stop();}catch{}
    this.voiceNodes=[];this.clearEarPlug();this.hurt=0;this.duck=0;
  }
  say(clip,priority=40){
    if(!this.live())return false;
    if(Array.isArray(clip))clip=clip[Math.floor(Math.random()*clip.length)];
    if(!this.buffers[clip])return false;
    const now=this.ctx.currentTime;
    if(now<this.voiceNext && priority<70)return false;
    if(!this.voicePending||priority>this.voicePending.priority)this.voicePending={clip,priority,time:now};
    clearTimeout(this.voiceTimer);
    const wait=priority>=100?0:Math.max(0,this.voiceNext-now)*1000;
    this.voiceTimer=setTimeout(()=>this.flushVoice(),wait+12);
    return true;
  }
  flushVoice(){
    const pending=this.voicePending;this.voicePending=null;if(!pending||!this.live())return;
    const now=this.ctx.currentTime;
    if(now<this.voiceNext&&pending.priority<100)return;
    for(const node of this.voiceNodes||[])try{node.stop();}catch{}
    const src=this.ctx.createBufferSource(),double=this.ctx.createBufferSource(),delay=this.ctx.createDelay(.1),gain=this.ctx.createGain();
    src.buffer=double.buffer=this.buffers[pending.clip];double.detune.value=VOICE_FX.doubleDetune;
    delay.delayTime.value=VOICE_FX.doubleDelay;gain.gain.value=VOICE_FX.doubleGain;
    src.connect(this.voiceBass);double.connect(delay);delay.connect(gain);gain.connect(this.voiceBass);
    src.start(now);double.start(now);this.voiceNodes=[src,double];
    src.onended=()=>{src.disconnect();};double.onended=()=>{double.disconnect();delay.disconnect();gain.disconnect();};
    this.voiceNext=now+Math.max(VOICE_FX.gap,src.buffer.duration+VOICE_FX.tail);
    this.voiceLog.push({clip:pending.clip,priority:pending.priority,time:now});
    this.duck=Math.max(this.duck,.29);
  }
''' + s[a:]
p.write_text(s,encoding='utf-8')
print('World audio bus, Victor and knockout hearing implemented.')

