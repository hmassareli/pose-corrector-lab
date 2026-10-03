// Recorded/licensed samples only. Attribution: /assets/boxing_audio/CREDITS.md.
export class BoxingAudio {
  constructor() {
    this.enabled = localStorage.getItem("cornerAudio") !== "off";
    this.volume = Number(localStorage.getItem("cornerVolume") ?? 0.5);
    this.buffers = {};
    this.onsets = {};
    this.excitement = 0;
    this.active = false;
  }
  async start() {
    this.active = true;
    this.ctx ??= new AudioContext({ latencyHint: "interactive" });
    await this.ctx.resume();
    if (!this.master) {
      this.master = this.ctx.createGain();
      this.master.connect(this.ctx.destination);
    }
    this.setVolume(this.volume);
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
      source.connect(this.crowdGain);
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
    this.setVolume(this.volume);
  }
  play(name, volume = 1, blocked = false) {
    if (!this.enabled || !this.ctx || !this.buffers[name]) return;
    const src = this.ctx.createBufferSource(),
      gain = this.ctx.createGain();
    src.buffer = this.buffers[name];
    src.playbackRate.value = 0.96 + Math.random() * 0.08;
    gain.gain.value = volume;
    src.connect(gain);
    if (blocked) {
      const filter = this.ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = 1100;
      gain.connect(filter);
      filter.connect(this.master);
    } else gain.connect(this.master);
    src.start(this.ctx.currentTime, this.onsets[name] || 0);
    src.onended = () => {
      src.disconnect();
      gain.disconnect();
    };
  }
  hit(blocked) {
    this.play(
      "punch" + (1 + Math.floor(Math.random() * 3)),
      blocked ? 0.25 : 0.55,
      blocked,
    );
    this.excitement = Math.min(1, this.excitement + (blocked ? 0.05 : 0.22));
  }
  bell() {
    this.play("bell", 0.55);
  }
  update(dt) {
    this.excitement = Math.max(0, this.excitement - dt * 0.08);
    if (this.crowdGain)
      this.crowdGain.gain.setTargetAtTime(
        0.055 + this.excitement * 0.11,
        this.ctx.currentTime,
        0.4,
      );
  }
  stop() {
    this.active = false;
    try {
      this.crowd?.stop();
    } catch {}
    this.crowd = null;
  }
}
