import { t } from '/static/boxing_i18n.js';
// Opt-in diagnostics. Reads the rig after each stage; never edits the pose.
import * as THREE from 'three';

const FPS = 15;
const SIZE = [1600, 900];
const EDGES = [[0,1],[0,2],[1,3],[2,4],[3,5],[4,6],[0,7],[7,14],[14,15],
  [7,8],[7,9],[8,10],[9,11],[10,12],[11,13]];
const finite = p => p?.length >= 3 && p.every(Number.isFinite);
const rounded = values => values.map(n => Math.round(n * 1e6) / 1e6);
const vector = new THREE.Vector3(), quaternion = new THREE.Quaternion();
const stamp = ms => `${Math.floor(ms / 60000).toString().padStart(2,'0')}:${Math.floor(ms / 1000 % 60).toString().padStart(2,'0')}`;

// Project camera-space input, then reflect screen X exactly like the webcam.
// The game's viewer pose can already be mirrored (or not, per calibration);
// prefer the original NLF camera coordinates to avoid that ambiguity entirely.
export function projectWebcamSkeleton(sample, {left,top,width,height}) {
  const info=sample?.cameraInfo, raw=sample?.debug?.rawCameraJoints;
  const points=raw || sample?.cameraPose;
  if (!points || !info?.size) return [];
  const [iw,ih]=info.size;
  const focal=Math.max(iw,ih)/(2*Math.tan((info.fov||55)*Math.PI/360));
  return points.map(p=>{
    if (!finite(p)) return null;
    const depth=raw?p[2]:-p[2];
    if(depth<=.2) return null;
    const px=raw?p[0]:(info.selfieMirrored===false?p[0]:-p[0]);
    const py=raw?p[1]:-p[1];
    return [left+width/2-focal*px/depth/iw*width,top+height/2+focal*py/depth/ih*height];
  });
}

export function snapshotRig(actor, full = false) {
  actor.group.updateWorldMatrix(true, true);
  const bones = [];
  if (full) actor.root.traverse(b => { if (b.isBone) bones.push(b); });
  else for (const { bone } of actor.rig.bones.values()) bones.push(bone);
  const indices = new Map(bones.map((b,i) => [b,i]));
  return {
    avatarId: actor.avatarId,
    group: { position: actor.group.position.toArray(), quaternion: actor.group.quaternion.toArray(), scale: actor.group.scale.toArray() },
    root: { position: actor.root.position.toArray(), quaternion: actor.root.quaternion.toArray(), scale: actor.root.scale.toArray() },
    bones: bones.map(b => ({ name: b.name, parent: indices.get(b.parent) ?? -1,
      localPosition: rounded(b.position.toArray()), localQuaternion: rounded(b.quaternion.toArray()),
      worldPosition: rounded(b.getWorldPosition(vector).toArray()),
      worldQuaternion: rounded(b.getWorldQuaternion(quaternion).toArray()) })),
    mapped: Object.fromEntries([...actor.rig.bones].map(([name,{bone}]) => [name, {
      position: rounded(bone.getWorldPosition(vector).toArray()),
      quaternion: rounded(bone.getWorldQuaternion(quaternion).toArray()) }])),
  };
}

// Folder mode streams to disk. The ZIP fallback only applies to browsers that
// don't expose a directory picker; one download avoids blocked multi-downloads.
class Output {
  constructor(directory) { this.directory = directory; this.files = new Map(); this.queue = Promise.resolve(); this.error = null; }
  async open(path) {
    let dir = this.directory;
    const parts = path.split('/');
    for (const part of parts.slice(0,-1)) dir = await dir.getDirectoryHandle(part, {create:true});
    return (await dir.getFileHandle(parts.at(-1), {create:true})).createWritable();
  }
  write(path, data) {
    this.queue = this.queue.then(async () => {
      if (!this.files.has(path)) this.files.set(path, this.directory ? await this.open(path) : []);
      const file = this.files.get(path);
      if (this.directory) await file.write(data);
      else file.push(data);
    }).catch(error => { this.error ||= error; });
  }
  async close() {
    await this.queue;
    if (this.directory) {
      for (const file of this.files.values()) try { await file.close(); } catch (error) { this.error ||= error; }
      return null;
    }
    return storedZip([...this.files].map(([name,parts]) => [name,new Blob(parts)]));
  }
}

// ZIP STORE: interoperable local headers + CRC32 + central directory, no CDN.
export async function storedZip(files) {
  const table = new Uint32Array(256);
  for (let n=0;n<256;n++) { let c=n; for(let k=0;k<8;k++) c=c&1 ? 0xedb88320^(c>>>1) : c>>>1; table[n]=c>>>0; }
  const chunks=[], directory=[]; let offset=0, centralSize=0;
  for (const [name,blob] of files) {
    const bytes = new Uint8Array(await blob.arrayBuffer()), filename = new TextEncoder().encode(name);
    let crc=0xffffffff; for (const byte of bytes) crc=table[(crc^byte)&255]^(crc>>>8); crc=(crc^0xffffffff)>>>0;
    const header = new Uint8Array(30+filename.length), h = new DataView(header.buffer);
    h.setUint32(0,0x04034b50,true); h.setUint16(4,20,true); h.setUint16(6,0x800,true);
    h.setUint32(14,crc,true); h.setUint32(18,bytes.length,true); h.setUint32(22,bytes.length,true); h.setUint16(26,filename.length,true); header.set(filename,30);
    const central = new Uint8Array(46+filename.length), c=new DataView(central.buffer);
    c.setUint32(0,0x02014b50,true); c.setUint16(4,20,true); c.setUint16(6,20,true); c.setUint16(8,0x800,true);
    c.setUint32(16,crc,true); c.setUint32(20,bytes.length,true); c.setUint32(24,bytes.length,true); c.setUint16(28,filename.length,true); c.setUint32(42,offset,true); central.set(filename,46);
    chunks.push(header,blob); directory.push(central); offset+=header.length+bytes.length; centralSize+=central.length;
  }
  const end=new Uint8Array(22), e=new DataView(end.buffer); e.setUint32(0,0x06054b50,true);
  e.setUint16(8,files.length,true); e.setUint16(10,files.length,true); e.setUint32(12,centralSize,true); e.setUint32(16,offset,true);
  return new Blob([...chunks,...directory,end],{type:'application/zip'});
}

export class BoxingDebugRecorder {
  constructor({button,status,getContext,getVideo,getBridge,notify}) {
    Object.assign(this,{button,status,getContext,getVideo,getBridge,notify});
    this.recording=false; this.busy=false; this.latest=null; this.stopPromise=null;
    button.addEventListener('click', () => { if (!this.busy) void (this.recording ? this.stop() : this.start()); });
    window.addEventListener('beforeunload', event => {
      if (this.recording || this.busy) { event.preventDefault(); event.returnValue=''; }
    });
    document.addEventListener('visibilitychange', () => {
      if (this.recording) this.event('visibility',{state:document.visibilityState});
    });
  }
  label(text, recording=false) {
    this.status.textContent=text; this.status.hidden=!text;
    this.button.classList.toggle('recording',recording);
    this.button.setAttribute('aria-pressed',String(recording));
    const title=recording ? t('saving') : t('record');
    this.button.title=title; this.button.setAttribute('aria-label',title);
  }
  async start({memory=false}={}) {
    if (this.recording || this.busy) return false;
    const video=this.getVideo();
    if (!video?.srcObject?.getVideoTracks().some(t=>t.readyState==='live') || video.readyState<2) {
      this.notify(t('noCamera')); return false;
    }
    if (!window.MediaRecorder || !HTMLCanvasElement.prototype.captureStream) {
      this.notify(t('recordError')); return false;
    }
    this.busy=true; this.button.disabled=true; this.label(t('starting'));
    let directory=null;
    this.name='corner-debug-'+new Date().toISOString().replace(/[:.]/g,'-');
    try {
      if (!memory && window.showDirectoryPicker) {
        const parent=await window.showDirectoryPicker({id:'corner-debug',mode:'readwrite'});
        directory=await parent.getDirectoryHandle(this.name,{create:true});
      }
      this.output=new Output(directory); this.started=performance.now(); this.startedAbsolute=performance.timeOrigin+this.started;
      this.frameCount=0; this.poseCount=0; this.lastCapture=-Infinity; this.lastSnapshot=-Infinity;
      this.pendingSnapshots=new Set(); this.recorders=[]; this.latest=null; this.initial=this.getContext(); this.lastError=null;
      this.canvas=document.createElement('canvas'); [this.canvas.width,this.canvas.height]=SIZE;
      this.ctx=this.canvas.getContext('2d',{alpha:false}); this.ctx.fillStyle='#10101b'; this.ctx.fillRect(0,0,...SIZE);
      this.comparisonStream=this.canvas.captureStream(0);
      this.captureTrack=this.comparisonStream.getVideoTracks()[0];
      // Only video tracks; never request a microphone or stop webcam-owned tracks.
      this.makeRecorder(this.comparisonStream,'comparacao');
      this.makeRecorder(new MediaStream(video.srcObject.getVideoTracks()),'webcam');
      this.recording=true;
      this.getBridge().debugRecording=true;
      this.event('start',{startedAbsoluteMs:this.startedAbsolute,webcamTime:video.currentTime,context:this.initial.state,
        webcamSettings:video.srcObject.getVideoTracks()[0].getSettings()});
      this.writeReadme(); this.label('REC 00:00',true);
      return true;
    } catch (error) {
      this.recording=false;
      if (this.getBridge()) this.getBridge().debugRecording=false;
      for (const r of this.recorders || []) if(r.recorder.state!=='inactive') r.recorder.stop();
      await Promise.all((this.recorders || []).map(r=>r.done));
      this.comparisonStream?.getTracks().forEach(t=>t.stop());
      if (this.output) await this.output.close();
      if (error.name!=='AbortError') { this.notify(t('recordError')); this.label(t('recordError')); }
      else this.label('');
      return false;
    } finally { this.busy=false; this.button.disabled=false; }
  }
  makeRecorder(stream,name) {
    const mime=['video/webm;codecs=vp8','video/webm','video/mp4'].find(t=>MediaRecorder.isTypeSupported(t));
    const recorder=new MediaRecorder(stream,{...(mime?{mimeType:mime}:{}),videoBitsPerSecond:name==='webcam'?3000000:4500000});
    const path=name+(recorder.mimeType.includes('mp4')?'.mp4':'.webm');
    const done=new Promise(resolve=>recorder.addEventListener('stop',resolve,{once:true}));
    recorder.addEventListener('dataavailable',e=>{if(e.data.size) this.output.write(path,e.data);});
    recorder.addEventListener('error',e=>{this.lastError=e.error?.message || t('recordError'); void this.stop();});
    recorder.start(1000);
    this.recorders.push({recorder,path,done,startOffsetMs:performance.now()-this.started});
  }
  event(type,data={}) {
    if (!this.recording) return;
    this.output.write('timeline.ndjson',JSON.stringify({type,tMs:performance.now()-this.started,...data})+'\n');
  }
  pose(data,received=performance.now()) {
    if (!this.recording) return;
    this.latest={...data,receivedAbsoluteMs:performance.timeOrigin+received,sequence:++this.poseCount};
    this.event('pose',{sequence:this.poseCount,receivedAbsoluteMs:this.latest.receivedAbsoluteMs,input:data});
  }
  beginFrame(now) {
    this.sampleFrame=this.recording && now-this.lastCapture>=1000/FPS;
    if (this.sampleFrame) { this.frameWorkStarted=performance.now(); this.stageWorkMs=0; this.stages={}; }
  }
  stage(i,name,actor,pose=null) {
    if (!this.sampleFrame) return;
    const started=performance.now();
    try { (this.stages[i] ||= {})[name]={rig:snapshotRig(actor),...(pose?{pose}: {})}; }
    catch(error) { this.lastError=error.message; void this.stop(); }
    finally { this.stageWorkMs+=performance.now()-started; }
  }
  capture(now) {
    if (!this.sampleFrame || !this.recording) return;
    this.sampleFrame=false; this.lastCapture=now;
    const captureStarted=performance.now();
    try {
      const c=this.getContext(), actors=c.actors;
      const frame={type:'frame',index:this.frameCount++,tMs:now-this.started,absoluteMs:performance.timeOrigin+now,
        webcamTime:this.getVideo().currentTime,poseSequence:this.latest?.sequence ?? null,
        sourceAgeMs:this.latest ? performance.timeOrigin+now-this.latest.receivedAbsoluteMs : null,
        game:c.state,camera:{position:c.camera.position.toArray(),quaternion:c.camera.quaternion.toArray(),
          fov:c.camera.fov,near:c.camera.near,aspect:c.camera.aspect,projection:c.camera.projectionMatrix.toArray(),view:c.camera.view},
        fighters:c.fighters,actors:actors.map(a=>a?{rig:snapshotRig(a,true),contact:a.guardContact?.diagnostics,
          groundInitialized:a.groundInitialized,groundY:a.groundY,groundOffset:a.groundOffset}:null),
        stages:this.stages};
      this.draw(c,frame); this.captureTrack.requestFrame?.();
      frame.captureWorkMs=this.stageWorkMs+performance.now()-captureStarted;
      frame.gameAndCaptureWorkMs=performance.now()-this.frameWorkStarted;
      this.output.write('timeline.ndjson',JSON.stringify(frame)+'\n');
      this.label('REC '+stamp(frame.tMs),true);
      if (now-this.lastSnapshot>=5000) {
        this.lastSnapshot=now;
        const path=`prints/${String(frame.index).padStart(6,'0')}-${Math.round(frame.tMs)}ms.jpg`;
        const pending=new Promise(resolve=>this.canvas.toBlob(blob=>{if(blob) this.output.write(path,blob);resolve();},'image/jpeg',.88));
        this.pendingSnapshots.add(pending); pending.finally(()=>this.pendingSnapshots.delete(pending));
      }
      if (this.output.error) { this.lastError=this.output.error.message; void this.stop(); }
    } catch(error) { this.lastError=error.message; void this.stop(); }
  }
  draw(c,frame) {
    const x=this.ctx; x.fillStyle='#10101b'; x.fillRect(0,0,...SIZE);
    const game=c.renderer.domElement, scale=Math.min(1200/game.width,858/game.height);
    x.drawImage(game,(1200-game.width*scale)/2,42+(858-game.height*scale)/2,game.width*scale,game.height*scale);
    const video=this.getVideo(), w=384, h=Math.min(300,w*video.videoHeight/video.videoWidth), top=78;
    x.save(); x.translate(1208+w,top); x.scale(-1,1); x.drawImage(video,0,0,w,h); x.restore();
    // Latest result over the live mirrored webcam, explicitly labelled with its age.
    const overlay=projectWebcamSkeleton(this.latest,{left:1208,top,width:w,height:h});
    x.save(); x.beginPath(); x.rect(1208,top,w,h); x.clip(); this.lines(overlay,EDGES,'#53f1ba'); x.restore();
    x.fillStyle='#fff7e6'; x.font='bold 18px sans-serif'; x.fillText('CORNER DEBUG  •  '+stamp(frame.tMs)+`  •  frame ${frame.index}`,16,28);
    x.font='14px sans-serif'; x.fillText(`${t(c.state.first?'first':'third')} • ${t('smoothing')} ${c.state.smooth}% • ${c.state.trackingStatus}`,510,28);
    x.fillText('Webcam espelhada + último NLF',1210,28);
    x.fillStyle='#bdbbd5'; x.fillText(`Pose ${frame.poseSequence??'—'} • idade ${Math.round(frame.sourceAgeMs??0)} ms`,1210,54);
    this.schematic(this.latest?.pose,EDGES,1208,top+h+34,384,215,t('recordSource'));
    const a=frame.actors[c.state.self]?.rig;
    if (a) {
      const inv=c.actors[c.state.self].group.matrixWorld.clone().invert();
      const pts=a.bones.map(b=>new THREE.Vector3(...b.worldPosition).applyMatrix4(inv).toArray());
      this.schematic(pts,a.bones.map((b,i)=>[b.parent,i]).filter(([p])=>p>=0),1208,top+h+277,384,215,t('recordAvatar'));
    }
  }
  lines(points,edges,color) {
    const x=this.ctx; x.strokeStyle=color; x.lineWidth=2;
    x.beginPath(); for(const [a,b] of edges) if(points[a]&&points[b]) {x.moveTo(...points[a]);x.lineTo(...points[b]);} x.stroke();
    x.fillStyle=color; for(const p of points) if(p) {x.beginPath();x.arc(...p,2,0,Math.PI*2);x.fill();}
  }
  schematic(points,edges,left,top,w,h,title) {
    const x=this.ctx; x.fillStyle='#fff7e6'; x.font='14px sans-serif'; x.fillText(title,left,top);
    const valid=points?.filter(finite); if (!valid?.length) return;
    const minY=Math.min(...valid.map(p=>p[1])), maxY=Math.max(...valid.map(p=>p[1]));
    const cx=(Math.min(...valid.map(p=>p[0]))+Math.max(...valid.map(p=>p[0])))/2;
    const s=Math.min((h-30)/Math.max(.2,maxY-minY),w/Math.max(.3,...valid.map(p=>2*Math.abs(p[0]-cx))));
    // Display-only selfie reflection, matching the webcam panel. Keep every
    // recorded coordinate and the game's rig unchanged.
    this.lines(points.map(p=>finite(p)?[left+w/2-(p[0]-cx)*s,top+22+(maxY-p[1])*s]:null),edges,'#53f1ba');
  }
  writeReadme() {
    this.output.write('LEIA-ME.txt',`HEAVY HANDS — gravação de diagnóstico\n\nwebcam: câmera original, sem espelhar e sem áudio; útil para reprocessar NLF.\ncomparacao: jogo renderizado + webcam espelhada + último esqueleto recebido + avatar final. O HUD HTML/menus não entram neste vídeo.\nprints/: comparação em JPEG a cada 5 segundos.\ntimeline.ndjson: um JSON por linha. Eventos pose guardam entrada antes do jogo; frame guarda poses processadas, estágios de retarget e todos os ossos finais de ambos os avatares.\nmanifest.json: configurações, relógios, arquivos, duração e contagens.\n\nTodos os tempos tMs são relativos ao início. absoluteMs usa performance.timeOrigin + performance.now(); relógio do iframe convertido para o mesmo domínio. Cada frame referencia poseSequence e webcamTime. NLF roda com atraso: o overlay mostra a última resposta, NÃO uma detecção do frame atual da webcam.\nO esqueleto frontal é uma projeção esquemática; coordenadas 3D e quaternions estão na timeline. Ossos worldPosition são no ringue; localQuaternion é relativo ao pai; root/group incluem escalas. Stages são leituras, sem alterar a pose. As vistas frontais se ajustam ao tamanho do esqueleto: use worldPosition para medir flutuação.\nCaptura de comparação e avatar: alvo 15 fps, taxa efetiva depende do jogo. Vídeo webcam usa a taxa da câmera. A gravação pode acrescentar carga; captureWorkMs mede parte do custo e intervalos revelam travamentos.\nOs arquivos ficam locais e não são enviados ao adversário nem a serviços externos.\n`);
  }
  stop() {
    if (this.busy) return this.stopPromise;
    if (!this.recording) return Promise.resolve(null);
    this.busy=true; this.recording=false; this.sampleFrame=false;
    if (this.getBridge()) this.getBridge().debugRecording=false;
    this.button.disabled=true; this.label(t('saving')+'…');
    this.stopPromise=this.finish(); return this.stopPromise;
  }
  async finish() {
    let result=null;
    try {
      const ended=performance.now();
      for(const r of this.recorders) if(r.recorder.state!=='inactive') r.recorder.stop();
      await Promise.all(this.recorders.map(r=>r.done));
      this.comparisonStream.getTracks().forEach(t=>t.stop());
      await Promise.all([...this.pendingSnapshots]);
      await this.output.queue;
      const manifest={schema:'corner-debug-v1',startedAbsoluteMs:this.startedAbsolute,durationMs:ended-this.started,
        frames:this.frameCount,poses:this.poseCount,targetCaptureFps:FPS,size:SIZE,
        videos:this.recorders.map(({path,startOffsetMs,recorder})=>({path,startOffsetMs,mimeType:recorder.mimeType})),
        initial:this.initial.state,final:this.getContext().state,error:this.lastError || this.output.error?.message || null,
        files:[...this.output.files.keys(),'manifest.json'],storage:this.output.directory?'folder':'zip-download'};
      this.output.write('manifest.json',JSON.stringify(manifest,null,2));
      const blob=await this.output.close();
      result={manifest,blob,name:this.name};
      if(blob) {
        const url=URL.createObjectURL(blob), a=document.createElement('a'); a.href=url; a.download=this.name+'.zip';
        a.click(); setTimeout(()=>URL.revokeObjectURL(url),60000);
      }
      const error=this.lastError || this.output.error?.message;
      this.label(error?t('recordError'):t('recordSaved'));
      this.notify(error?t('recordError'):t('recordSaved')+': '+this.name+(blob?'.zip':''));
      this.lastResult=result;
    } catch(error) { this.label(t('recordError')); this.notify(t('recordError')); }
    finally { this.comparisonStream?.getTracks().forEach(t=>t.stop()); this.busy=false; this.button.disabled=false; this.latest=null; this.output=null; this.recorders=[]; }
    return result;
  }
}
