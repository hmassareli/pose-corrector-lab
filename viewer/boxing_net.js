export class DuelConnection {
  constructor(onMessage, onStatus) {
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.seq = 0;
    this.last = -1;
    this.slot = 0;
    this.connected = false;
    this.peerReady = false;
    this.pendingIce = [];
  }
  async connect(url, room, mode) {
    this.close();
    this.mode = mode;
    this.seq = 0;
    this.last = -1;
    this.ws = new WebSocket(url);
    this.ws.onopen = () =>
      this.ws.send(JSON.stringify({ type: "join", room, mode }));
    this.ws.onerror = () =>
      this.onStatus("connectionError");
    this.ws.onclose = () => {
      this.connected = false;
      this.peerReady = false;
      this.onStatus("disconnected");
      this.onMessage({ type: "disconnected" });
    };
    this.ws.onmessage = async (e) => {
      try {
        const m = JSON.parse(e.data);
        if (m.type === "joined") {
          this.slot = m.slot;
          this.connected = true;
          this.onMessage(m);
          this.onStatus("waiting");
        } else if (m.type === "ready") {
          this.peerReady = true;
          this.onMessage(m);
          this.onStatus("joined");
          if (this.mode === "p2p") await this.setupPeer();
        } else if (m.type === "signal") {
          await this.signal(m.data);
        } else if (m.type === "peer-left") {
          this.peerReady = false;
          this.onStatus("disconnected");
          this.onMessage({ type: "disconnected" });
        } else if (m.type === "error") {
          this.onStatus("connectionError");
        } else this.deliver(m);
      } catch (err) {
        this.onStatus("connectionError");
      }
    };
  }
  deliver(m) {
    if (m.type !== "packet" || !Number.isInteger(m.seq) || m.seq <= this.last)
      return;
    this.last = m.seq;
    this.onMessage(m.data);
  }
  send(data) {
    if (!this.peerReady) return;
    const payload = JSON.stringify({ type: "packet", seq: ++this.seq, data });
    if (this.dc?.readyState === "open" && this.dc.bufferedAmount < 32768) {
      this.dc.send(payload);
    } else if (this.ws?.readyState === 1 && this.ws.bufferedAmount < 32768)
      this.ws.send(payload);
  }
  async setupPeer() {
    this.pc?.close();
    this.pendingIce = [];
    this.pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });
    this.pc.onicecandidate = (e) => {
      if (e.candidate)
        this.ws.send(
          JSON.stringify({ type: "signal", data: { candidate: e.candidate } }),
        );
    };
    this.pc.ondatachannel = (e) => this.bindChannel(e.channel);
    this.pc.onconnectionstatechange = () => {
      if (
        ["failed", "disconnected", "closed"].includes(this.pc.connectionState)
      )
        this.onStatus("joined");
    };
    if (this.slot === 0) {
      this.bindChannel(
        this.pc.createDataChannel("pose", {
          ordered: false,
          maxRetransmits: 0,
        }),
      );
      await this.pc.setLocalDescription(await this.pc.createOffer());
      this.ws.send(
        JSON.stringify({
          type: "signal",
          data: { description: this.pc.localDescription },
        }),
      );
    }
  }
  bindChannel(dc) {
    this.dc = dc;
    dc.onopen = () => this.onStatus("joined");
    dc.onclose = () => this.onStatus("joined");
    dc.onmessage = (e) => {
      try {
        this.deliver(JSON.parse(e.data));
      } catch {}
    };
  }
  async signal(d) {
    if (!this.pc) return;
    if (d.description) {
      await this.pc.setRemoteDescription(d.description);
      for (const c of this.pendingIce) await this.pc.addIceCandidate(c);
      this.pendingIce = [];
      if (d.description.type === "offer") {
        await this.pc.setLocalDescription(await this.pc.createAnswer());
        this.ws.send(
          JSON.stringify({
            type: "signal",
            data: { description: this.pc.localDescription },
          }),
        );
      }
    } else if (d.candidate) {
      if (this.pc.remoteDescription) await this.pc.addIceCandidate(d.candidate);
      else this.pendingIce.push(d.candidate);
    }
  }
  close() {
    this.peerReady = false;
    this.connected = false;
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.close();
    }
    if (this.dc) this.dc.onclose = null;
    this.dc?.close();
    this.pc?.close();
    this.pc = null;
    this.dc = null;
  }
}
