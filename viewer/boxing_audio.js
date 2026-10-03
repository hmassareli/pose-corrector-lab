export const VOICE_FX={tail:1.4,preDelay:.035,wet:.2,doubleDelay:.018,doubleDetune:-12,doubleGain:.316,bassDb:3,highCut:9000,gap:3.2};
// Recorded/licensed samples only. Attribution: /assets/boxing_audio/CREDITS.md.
export class BoxingAudio {
  constructor() {
    this.enabled = localStorage.getItem("cornerAudio") !== "off";
    this.volume = Number(localStorage.getItem("cornerVolume") ?? 0.5);
    this.voiceVolume=Number(localStorage.getItem('cornerVoice')??.85);
    this.reducedImpact=localStorage.getItem('cornerReducedImpact')==='on';
    this.voiceLog=[];this.voiceNext=0;this.voicePending=null;
    this.voiceClips={};this.onVoice=null;
    this.earUntil=0;
    this.buffers = {};
    this.onsets = {};
    this.excitement = 0;
    this.active = false;
    this.musicVolume = Number(localStorage.getItem("cornerMusic") ?? 0.7);
    this.musicMode = "lobby";
    this.state = { muffle: 0, wobble: false, hype: false };
    this.hurt = 0;
    this.duck = 0;
    this.clock = 0;
  }
  ensureContext() {
    this.ctx ??= new AudioContext({ latencyHint: "interactive" });
    if (!this.master) {
      this.master = this.ctx.createGain();
      // Layered hits stack loudly; the limiter keeps peaks punchy without clipping.
      const limiter = this.ctx.createDynamicsCompressor();
      limiter.threshold.value = -14;
      limiter.knee.value = 8;
      limiter.ratio.value = 6;
      limiter.attack.value = 0.002;
      limiter.release.value = 0.18;
      this.master.connect(limiter);
      limiter.connect(this.ctx.destination);
      const noise = this.ctx.createBuffer(1, this.ctx.sampleRate, this.ctx.sampleRate);
      const data = noise.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
      this.noise = noise;
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
      this.voiceBus.connect(this.worldFilter);
    }
    this.setVolume(this.volume);
    return this.ctx.resume();
  }
  setVoiceVolume(v){this.voiceVolume=Math.max(0,Math.min(1,v));localStorage.setItem('cornerVoice',String(this.voiceVolume));if(this.voiceBus)this.voiceBus.gain.setTargetAtTime(this.voiceVolume,this.ctx.currentTime,.03);if(!this.voiceVolume)this.onVoice?.(null);}
  setReducedImpact(v){this.reducedImpact=v;localStorage.setItem('cornerReducedImpact',v?'on':'off');if(v)this.clearEarPlug();}
  clearEarPlug(){
    if(!this.ctx)return;
    const now=this.ctx.currentTime;this.earUntil=0;
    this.worldFilter.frequency.cancelScheduledValues(now);this.worldFilter.frequency.setValueAtTime(18000,now);
    this.worldGain.gain.cancelScheduledValues(now);this.worldGain.gain.setValueAtTime(1,now);
    for(const node of this.earNodes||[])try{node.stop();}catch{}
    this.earNodes=[];this.setVoiceVolume(this.voiceVolume);
    this.voiceBus.gain.cancelScheduledValues(now);
    this.voiceBus.gain.setValueAtTime(this.voiceVolume,now);
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
    for(let i=0;i<3;i++){const at=now+i;
      this.earNodes.push(this.tone('sine',62,40,.2,.01,.12,at,true).source);
      this.earNodes.push(this.tone('sine',58,38,.12,.01,.12,at+.2,true).source);
    }
    return true;
  }
  resetFight(){
    this.onVoice?.(null);
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
    if(this.voiceVolume>0 && this.volume>0)this.onVoice?.({clip:pending.clip,text:this.voiceClips[pending.clip]?.text,duration:src.buffer.duration,priority:pending.priority,time:now});
    this.duck=Math.max(this.duck,.29);
  }
  // Streamed (not decoded) so a 3.5 min track costs no memory up front.
  // Not awaited: before a user gesture resume() stays pending, which would block play().
  startMusic() {
    if (!this.enabled) return false;
    this.ensureContext().catch(() => {});
    if (!this.music) {
      const el = new Audio("/assets/boxing_audio/raw_phonk_boxing.m4a");
      el.loop = true;
      el.preservesPitch = false;
      const source = this.ctx.createMediaElementSource(el);
      this.musicFilter = this.ctx.createBiquadFilter();
      this.musicFilter.type = "lowpass";
      this.musicFilter.frequency.value = 18000;
      this.musicFilter.Q.value = 0.9;
      this.musicGain = this.ctx.createGain();
      this.musicGain.gain.value = 0;
      source.connect(this.musicFilter);
      this.musicFilter.connect(this.musicGain);
      this.musicGain.connect(this.worldFilter);
      this.music = el;
    }
    if (this.music.paused) this.music.play().catch(() => {});
    return this.musicPlaying();
  }
  musicPlaying() {
    return !!this.music && !this.music.paused && this.ctx?.state === "running";
  }
  setMusicVolume(v) {
    this.musicVolume = Math.max(0, Math.min(1, v));
    localStorage.setItem("cornerMusic", this.musicVolume);
  }
  // lobby: loud; fight: bed under the action; ko: dipped for the bells.
  setMusicMode(mode) {
    this.musicMode = mode;
  }
  setState(state) {
    this.state = state;
  }
  // Taking a clean hit briefly muffles the world, harder on the chin.
  hurtMuffle(amount) {
    if(this.reducedImpact)return;
    this.hurt = Math.max(this.hurt, amount);
    this.duck = Math.max(this.duck, amount * 0.6);
  }
  ring() {
    if (!this.live() || this.reducedImpact) return;
    this.tone("sine", 3900, 3700, 0.035, 0.02, 1.6);
  }
  async start() {
    this.active = true;
    await this.ensureContext();
    this.startMusic();
    if (!this.loading)
      this.loading = Promise.all(
        ["punch1", "punch2", "punch3", "punch_heavy", "punch_super", "bell", "crowd"].map(async (name) => {
          const res = await fetch("/assets/boxing_audio/" + name + ".wav");
          if (!res.ok) throw Error("Audio unavailable: " + name);
          this.buffers[name] = await this.ctx.decodeAudioData(
            await res.arrayBuffer(),
          );
          if (name.startsWith("punch")) {
            const buffer = this.buffers[name];
            let peak = 0,
              first = buffer.length;
            for (let ch = 0; ch < buffer.numberOfChannels; ch++)
              for (const v of buffer.getChannelData(ch))
                peak = Math.max(peak, Math.abs(v));
            for (let ch = 0; ch < buffer.numberOfChannels; ch++) {
              const samples = buffer.getChannelData(ch);
              for (let i = 0; i < first; i++)
                if (Math.abs(samples[i]) > peak * 0.01) {
                  first = i;
                  break;
                }
            }
            this.onsets[name] = Math.max(0, first / buffer.sampleRate - 0.003);
          }
        }),
      );
    await this.loading;
    if(!this.voiceLoading)this.voiceLoading=fetch('/assets/boxing_audio/victor_clips/manifest.json').then(r=>r.json()).then(m=>Promise.all(m.clips.map(async c=>{
      this.voiceClips[c.name]=c;
      const response=await fetch('/assets/boxing_audio/victor_clips/'+c.file);
      if(response.ok)this.buffers[c.name]=await this.ctx.decodeAudioData(await response.arrayBuffer());
    })));
    await this.voiceLoading;
    if (!this.active) return;
    if (!this.crowd) {
      const source = this.ctx.createBufferSource();
      source.buffer = this.buffers.crowd;
      source.loop = true;
      this.crowdGain = this.ctx.createGain();
      this.crowdGain.gain.value = 0.055;
      this.crowdFilter = this.ctx.createBiquadFilter();
      this.crowdFilter.type = "lowpass";
      this.crowdFilter.frequency.value = 1400;
      source.connect(this.crowdFilter);
      this.crowdFilter.connect(this.crowdGain);
      this.crowdGain.connect(this.worldFilter);
      source.start();
      this.crowd = source;
    }
  }
  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
    if(!this.volume)this.onVoice?.(null);
    localStorage.setItem("cornerVolume", this.volume);
    if (this.master)
      this.master.gain.setTargetAtTime(
        this.enabled ? this.volume : 0,
        this.ctx.currentTime,
        0.03,
      );
  }
  setEnabled(v) {
    this.enabled = v;
    if(!v)this.onVoice?.(null);
    localStorage.setItem("cornerAudio", v ? "on" : "off");
    if (!v) this.music?.pause();
    else if (this.ctx) this.startMusic();
    this.setVolume(this.volume);
  }
  play(name, volume = 1, blocked = false, rate = 1, delay = 0) {
    if (!this.enabled || !this.ctx || !this.buffers[name]) return;
    const src = this.ctx.createBufferSource(),
      gain = this.ctx.createGain();
    src.buffer = this.buffers[name];
    src.playbackRate.value = rate * (0.96 + Math.random() * 0.08);
    gain.gain.value = volume;
    src.connect(gain);
    if (blocked) {
      const filter = this.ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 1100;
      gain.connect(filter);
      filter.connect(this.worldFilter);
    } else gain.connect(this.worldFilter);
    src.start(this.ctx.currentTime + delay, this.onsets[name] || 0);
    src.onended = () => {
      src.disconnect();
      gain.disconnect();
    };
  }
  live() {
    return this.enabled && this.ctx && this.master && this.noise;
  }
  // Short envelope helper: every synthesized layer is a one-shot node chain.
  envelope(node, peak, attack, decay, at = this.ctx.currentTime, bypass = false) {
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), at + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
    node.connect(gain);
    gain.source=node;
    gain.connect(bypass ? this.master : this.worldFilter);
    node.start(at);
    node.stop(at + attack + decay + 0.05);
    node.onended = () => {
      node.disconnect();
      gain.disconnect();
    };
    return gain;
  }
  noiseBurst(type, from, to, q, peak, attack, decay, at = this.ctx.currentTime) {
    const src = this.ctx.createBufferSource(),
      filter = this.ctx.createBiquadFilter();
    src.buffer = this.noise;
    src.loop = true;
    filter.type = type;
    filter.Q.value = q;
    filter.frequency.setValueAtTime(from, at);
    filter.frequency.exponentialRampToValueAtTime(to, at + attack + decay);
    src.connect(filter);
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(peak, at + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
    filter.connect(gain);
    gain.connect(this.worldFilter);
    src.start(at, Math.random() * 0.5);
    src.stop(at + attack + decay + 0.05);
    src.onended = () => {
      src.disconnect();
      filter.disconnect();
      gain.disconnect();
    };
  }
  tone(type, from, to, peak, attack, decay, at = this.ctx.currentTime, bypass = false) {
    const osc = this.ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(from, at);
    osc.frequency.exponentialRampToValueAtTime(to, at + attack + decay);
    return this.envelope(osc, peak, attack, decay, at, bypass);
  }
  // Air cut by the glove: immediate feedback even when the punch misses.
  whoosh(power) {
    if (!this.live()) return;
    this.noiseBurst("bandpass", 500, 2600 + power * 1800, 1.4, 0.05 + power * 0.16, 0.05, 0.13);
  }
  impact({ kind = "clean", power = 0.5, head = true, tier = "solido" } = {}) {
    if (!this.live()) return;
    const now = this.ctx.currentTime;
    const blocked = kind === "arm" || kind === "guard";
    const sample=!blocked&&tier==='devastador'?'punch_super':!blocked&&tier==='pesado'?'punch_heavy':'punch'+(1+Math.floor(Math.random()*3));
    this.lastImpactSample=sample;
    this.play(sample,blocked?.22:tier==='toque'?.06:.24+power*.46,blocked,blocked?.85:1);
    if(tier==='devastador')this.duck=Math.max(this.duck,.35);
    if (blocked) {
      this.tone("sine", 210, 90, 0.22, 0.004, 0.09);
      this.noiseBurst("lowpass", 900, 300, 0.7, 0.12, 0.002, 0.06);
      this.excitement = Math.min(1, this.excitement + 0.04);
      return;
    }
    // Sub thump scales with punch speed: the "weight" of the hit.
    this.tone("sine", 120 + power * 30, 42, 0.35 + power * 0.45, 0.003, 0.16 + power * 0.1);
    this.noiseBurst("highpass", 2400, 1800, 0.8, 0.08 + power * 0.08, 0.001, 0.035);
    if (kind === "chin" || kind === "finisher") {
      this.noiseBurst("highpass", 3800, 2600, 1.2, 0.3, 0.001, 0.05, now + 0.004);
      this.tone("square", 1900, 520, 0.07, 0.002, 0.07);
      this.tone("sine", 70, 30, 0.6, 0.004, 0.35, now + 0.01);
    }
    if (!head) this.tone("sine", 85, 38, 0.3, 0.004, 0.2, now + 0.008);
    const lift = { chin: 0.5, finisher: 0.6, counter: 0.35, body: 0.2 }[kind] ?? 0.22;
    this.excitement = Math.min(1, this.excitement + lift * (0.6 + power * 0.6));
  }
  hit(blocked) {
    this.impact({ kind: blocked ? "guard" : "clean", power: 0.5 });
  }
  combo(n) {
    if (!this.live() || n < 2) return;
    const f = 660 * Math.pow(2, Math.min(n - 2, 7) / 12);
    this.tone("triangle", f, f * 1.01, 0.07, 0.004, 0.16);
    this.tone("sine", f * 2, f * 2, 0.03, 0.004, 0.12);
  }
  // Cartoon birds circling a dazed fighter.
  chirps(seconds) {
    if (!this.live()) return;
    const now = this.ctx.currentTime;
    for (let t = 0.12; t < seconds - 0.1; t += 0.22 + Math.random() * 0.2) {
      const base = 2300 + Math.random() * 700;
      this.tone("sine", base, base * 1.45, 0.035, 0.01, 0.07, now + t);
      this.tone("sine", base * 1.3, base * 1.05, 0.025, 0.01, 0.06, now + t + 0.09);
    }
  }
  heartbeat(bypass = false) {
    if (!this.live()) return;
    const now = this.ctx.currentTime;
    this.tone("sine", 62, 40, 0.28, 0.01, 0.12, now, bypass);
    this.tone("sine", 58, 38, 0.2, 0.01, 0.12, now + 0.2, bypass);
  }
  tick(urgent) {
    if (!this.live()) return;
    this.tone("square", urgent ? 1250 : 900, urgent ? 1150 : 850, 0.04, 0.002, 0.04);
  }
  roar(amount) {
    this.excitement = Math.min(1, this.excitement + amount);
  }
  ko(loser = false) {
    this.roar(loser?.05:1);
    for (let i=0;i<(loser?1:3);i++)this.play("bell",loser?.18:.5,loser,1,i*.32);
    if(loser&&this.live())this.tone('sine',55,45,.4,.008,.4,this.ctx.currentTime+.8);
    if (this.live()) this.tone("sine", 55, 28, 0.7, 0.005, 0.9);
  }
  bell() {
    this.play("bell", 0.55);
  }
  update(dt) {
    this.excitement = Math.max(0, this.excitement - dt * 0.08);
    this.clock += dt;
    this.hurt = Math.max(0, this.hurt - dt * 1.8);
    this.duck = Math.max(0, this.duck - dt * 1.5);
    if (this.music && this.ctx) {
      const now = this.ctx.currentTime, s = this.state;
      // Fight bed sits only a little under the menu level, then follows the match.
      const fight = 0.44 + (s.hype ? 0.1 : 0) + this.excitement * 0.08 - (s.muffle > 0.5 ? 0.06 : 0);
      const base = { lobby: 0.62, fight, ko: 0.18, result: 0.5 }[this.musicMode] ?? fight;
      this.musicGain.gain.setTargetAtTime(base * this.musicVolume * (1 - this.duck), now, 0.25);
      // Stunned = underwater: low-pass sweeps from full range down to ~350 Hz.
      const muffle = Math.min(1, Math.max(s.muffle, this.hurt));
      this.musicFilter.frequency.setTargetAtTime(18000,now,.1);
      if(now>=this.earUntil) {
        const audibleMuffle=this.reducedImpact?0:muffle;
        this.worldFilter.frequency.setTargetAtTime(18000*Math.pow(350/18000,audibleMuffle),now,audibleMuffle>.5?.025:.3);
      }
      // Dizzy: tape-warble pitch sag. Last seconds of a round: slight push in tempo.
      const rate = (s.wobble || this.ctx.currentTime<this.earUntil) ? 0.93 + Math.sin(this.clock * 3.1) * 0.025 : s.urgent ? 1.04 : 1;
      if (Math.abs(this.music.playbackRate - rate) > 0.004) this.music.playbackRate = rate;
    }
    if (this.crowdGain) {
      this.crowdGain.gain.setTargetAtTime(
        (this.ctx.currentTime<this.earUntil?.018:.055) + this.excitement * .16,
        this.ctx.currentTime,
        0.25,
      );
      // A roaring crowd is brighter, not only louder.
      this.crowdFilter.frequency.setTargetAtTime(
        1400 + this.excitement * 6500,
        this.ctx.currentTime,
        0.3,
      );
    }
  }
  stop() {
    this.resetFight();
    this.active = false;
    try {
      this.crowd?.stop();
    } catch {}
    this.crowd = null;
  }
}
