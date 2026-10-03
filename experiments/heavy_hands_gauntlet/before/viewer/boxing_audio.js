// Recorded/licensed samples only. Attribution: /assets/boxing_audio/CREDITS.md.
export class BoxingAudio {
  constructor() {
    this.enabled = localStorage.getItem("cornerAudio") !== "off";
    this.volume = Number(localStorage.getItem("cornerVolume") ?? 0.5);
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
    }
    this.setVolume(this.volume);
    return this.ctx.resume();
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
      this.musicGain.connect(this.master);
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
    this.hurt = Math.max(this.hurt, amount);
    this.duck = Math.max(this.duck, amount * 0.6);
  }
  ring() {
    if (!this.live()) return;
    this.tone("sine", 3900, 3700, 0.035, 0.02, 1.6);
  }
  async start() {
    this.active = true;
    await this.ensureContext();
    this.startMusic();
    if (!this.loading)
      this.loading = Promise.all(
        ["punch1", "punch2", "punch3", "bell", "crowd"].map(async (name) => {
          const res = await fetch("/assets/boxing_audio/" + name + ".wav");
          if (!res.ok) throw Error("Som indisponível: " + name);
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
    if (!this.active) return;
    this.bell();
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
      this.crowdGain.connect(this.master);
      source.start();
      this.crowd = source;
    }
  }
  setVolume(v) {
    this.volume = Math.max(0, Math.min(1, v));
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
      filter.connect(this.master);
    } else gain.connect(this.master);
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
  envelope(node, peak, attack, decay, at = this.ctx.currentTime) {
    const gain = this.ctx.createGain();
    gain.gain.setValueAtTime(0.0001, at);
    gain.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), at + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
    node.connect(gain);
    gain.connect(this.master);
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
    gain.connect(this.master);
    src.start(at, Math.random() * 0.5);
    src.stop(at + attack + decay + 0.05);
    src.onended = () => {
      src.disconnect();
      filter.disconnect();
      gain.disconnect();
    };
  }
  tone(type, from, to, peak, attack, decay, at = this.ctx.currentTime) {
    const osc = this.ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(from, at);
    osc.frequency.exponentialRampToValueAtTime(to, at + attack + decay);
    this.envelope(osc, peak, attack, decay, at);
  }
  // Air cut by the glove: immediate feedback even when the punch misses.
  whoosh(power) {
    if (!this.live()) return;
    this.noiseBurst("bandpass", 500, 2600 + power * 1800, 1.4, 0.05 + power * 0.16, 0.05, 0.13);
  }
  impact({ kind = "clean", power = 0.5, head = true } = {}) {
    if (!this.live()) return;
    const now = this.ctx.currentTime;
    const blocked = kind === "arm" || kind === "guard";
    this.play("punch" + (1 + Math.floor(Math.random() * 3)), blocked ? 0.3 : 0.45 + power * 0.25, blocked, blocked ? 0.85 : 1);
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
  heartbeat() {
    if (!this.live()) return;
    const now = this.ctx.currentTime;
    this.tone("sine", 62, 40, 0.28, 0.01, 0.12, now);
    this.tone("sine", 58, 38, 0.2, 0.01, 0.12, now + 0.2);
  }
  tick(urgent) {
    if (!this.live()) return;
    this.tone("square", urgent ? 1250 : 900, urgent ? 1150 : 850, 0.04, 0.002, 0.04);
  }
  roar(amount) {
    this.excitement = Math.min(1, this.excitement + amount);
  }
  ko() {
    this.roar(1);
    for (let i = 0; i < 3; i++) this.play("bell", 0.5, false, 1, i * 0.32);
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
      this.musicFilter.frequency.setTargetAtTime(18000 * Math.pow(350 / 18000, muffle), now, muffle > 0.5 ? 0.08 : 0.3);
      // Dizzy: tape-warble pitch sag. Last seconds of a round: slight push in tempo.
      const rate = s.wobble ? 0.93 + Math.sin(this.clock * 3.1) * 0.025 : s.urgent ? 1.04 : 1;
      if (Math.abs(this.music.playbackRate - rate) > 0.004) this.music.playbackRate = rate;
    }
    if (this.crowdGain) {
      this.crowdGain.gain.setTargetAtTime(
        0.055 + this.excitement * 0.16,
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
    this.active = false;
    try {
      this.crowd?.stop();
    } catch {}
    this.crowd = null;
  }
}
