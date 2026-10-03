"""Offline exports of the actual voice graph, for optional human audition."""
import json,base64
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet/voice_audition';OUT.mkdir(exist_ok=True)
RENDER=r'''async([clip,wet,music])=>{
 const {BoxingAudio}=await import('/static/boxing_audio.js');const audio=await fetch('/assets/boxing_audio/victor_clips/'+clip+'.wav').then(r=>r.arrayBuffer());const decode=new AudioContext(),buffer=await decode.decodeAudioData(audio);await decode.close();
 const frames=Math.ceil((buffer.duration+1.5)*44100),a=new BoxingAudio();a.enabled=true;a.ctx=new OfflineAudioContext(2,frames,44100);a.ctx.resume=async()=>{};await a.ensureContext();a.voiceWet.gain.value=wet;a.buffers[clip]=buffer;a.voicePending={clip,priority:40};a.flushVoice();
 if(music){window.musicBytes??=await fetch('/assets/boxing_audio/raw_phonk_boxing.m4a').then(r=>r.arrayBuffer());const song=await a.ctx.decodeAudioData(musicBytes.slice(0)),src=a.ctx.createBufferSource(),g=a.ctx.createGain();src.buffer=song;g.gain.value=.44*.7*.71;src.connect(g);g.connect(a.worldFilter);src.start(0,45,buffer.duration+1.5);}
 const result=await a.ctx.startRendering(),channels=result.numberOfChannels,bytes=new ArrayBuffer(44+result.length*channels*2),dv=new DataView(bytes);let offset=0;const ascii=s=>{for(const c of s)dv.setUint8(offset++,c.charCodeAt(0));};
 ascii('RIFF');dv.setUint32(offset,bytes.byteLength-8,true);offset+=4;ascii('WAVEfmt ');dv.setUint32(offset,16,true);offset+=4;dv.setUint16(offset,1,true);offset+=2;dv.setUint16(offset,channels,true);offset+=2;dv.setUint32(offset,44100,true);offset+=4;dv.setUint32(offset,44100*channels*2,true);offset+=4;dv.setUint16(offset,channels*2,true);offset+=2;dv.setUint16(offset,16,true);offset+=2;ascii('data');dv.setUint32(offset,bytes.byteLength-44,true);offset+=4;
 let peak=0,energy=0;for(let i=0;i<result.length;i++)for(let c=0;c<channels;c++){const v=result.getChannelData(c)[i];peak=Math.max(peak,Math.abs(v));energy+=v*v;dv.setInt16(offset,Math.max(-1,Math.min(1,v))*32767,true);offset+=2;}
 const array=new Uint8Array(bytes);let binary='';for(let i=0;i<array.length;i+=8192)binary+=String.fromCharCode(...array.subarray(i,i+8192));return {wavBase64:btoa(binary),duration:result.duration,peakDb:20*Math.log10(peak),rmsDb:20*Math.log10(Math.sqrt(energy/(result.length*channels)))};
}'''
clips=['ko_k_o','hit_heavy','pressure_you_re_hurt','combo_combo','counter_counter'];rows=[]
with sync_playwright() as p:
 b=p.chromium.launch();page=b.new_page();page.goto('http://127.0.0.1:8780/static/boxing_core.mjs')
 for clip in clips:
  for wet,music in [(0.15,False),(.20,False),(.25,False),(.35,False),(.20,True)]:
   r=page.evaluate(RENDER,[clip,wet,music]);name=clip+'_'+str(round(wet*100))+('_music' if music else '')+'.wav';(OUT/name).write_bytes(base64.b64decode(r.pop('wavBase64')));rows.append(dict(clip=clip,wet=wet,music=music,file=name,**r))
 b.close()
(OUT/'manifest.json').write_text(json.dumps(rows,indent=2));html=['<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>HEAVY HANDS — audição Victor</title><style>body{background:#101825;color:#eee;font:15px system-ui;padding:30px}table{border-collapse:collapse}td,th{padding:15px;border-bottom:1px solid #ffffff30}audio{width:210px}a{color:#e8bb71}</style><h1>HEAVY HANDS — voz do Victor</h1><p>Exportações do grafo real de reprodução. Comparação seca, 15/20/25/35% de reverb e mix com música. Conferência auditiva humana ainda pendente.</p><table><tr><th>Clipe</th><th>Original</th><th>15%</th><th>20% padrão</th><th>25%</th><th>35%</th><th>20% + música</th></tr>']
for clip in clips:
 html.append('<tr><th>'+clip+'</th><td><audio controls src="../../../assets/boxing_audio/victor_clips/'+clip+'.wav"></audio></td>'+''.join('<td><audio controls src="'+r['file']+'"></audio></td>' for r in rows if r['clip']==clip)+'</tr>')
html.append('</table></html>');(OUT/'index.html').write_text(''.join(html),encoding='utf-8');print('Exported',len(rows),'actual voice graph WAVs; no human audition claimed',flush=True)
