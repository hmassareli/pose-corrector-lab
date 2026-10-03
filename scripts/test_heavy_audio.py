"""Executed WebAudio DSP and narrator priority/spacing checks in Chromium."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'experiments/heavy_hands_gauntlet'
DSP=r'''async()=>{
 const {BoxingAudio,VOICE_FX}=await import('/static/boxing_audio.js');
 const render=async(mode)=>{
  const a=new BoxingAudio();a.enabled=true;a.ctx=new OfflineAudioContext(1,48000*4.4,48000);a.ctx.resume=async()=>{};await a.ensureContext();
  a.master.gain.value=0;a.worldGain.disconnect();a.worldGain.connect(a.ctx.destination);
  const tone=a.ctx.createOscillator(),g=a.ctx.createGain();tone.frequency.value=4000;g.gain.value=.1;tone.connect(g);g.connect(a.worldFilter);tone.start(0);tone.stop(4.4);
  if(mode==='off')a.setReducedImpact(true);
  if(mode!=='baseline')a.earPlug(4);
  const samples=(await a.ctx.startRendering()).getChannelData(0);
  const rms=(start,end)=>{let s=0;for(let i=Math.round(start*48000);i<Math.round(end*48000);i++)s+=samples[i]*samples[i];return Math.sqrt(s/((end-start)*48000));};
  return {start:rms(.005,.015),closed:rms(.10,.15),held:rms(.5,.6),restored:rms(4.1,4.2),earNodes:a.earNodes?.length||0};
 };
 const base=await render('baseline'),ko=await render('ko'),off=await render('off');
 return {base,ko,off,dropAt100msDb:20*Math.log10(ko.closed/base.closed),restoreDb:20*Math.log10(ko.restored/base.restored),disabledDb:20*Math.log10(off.closed/base.closed),VOICE_FX};
}'''
VOICE=r'''async()=>{
 const {BoxingAudio}=await import('/static/boxing_audio.js');const a=new BoxingAudio();await a.start();
 const wait=t=>new Promise(r=>setTimeout(r,t));
 a.say('combo_combo',20);a.say('hit_good',40);a.say('hit_clean',60);await wait(80);
 const first=a.voiceLog.slice();const rejected=a.say('combo_combo',20);
 a.say('hit_he_s_hurt',70);a.say('hit_he_s_rocked',80);await wait(3350);
 a.say('ko_k_o',100);await wait(80);const logs=a.voiceLog.slice();
 a.setReducedImpact(false);a.earPlug(4);const earStarted=a.earNodes.length;a.setReducedImpact(true);
 const canceled={nodes:a.earNodes.length,until:a.earUntil,frequency:a.worldFilter.frequency.value,gain:a.worldGain.gain.value,voiceGain:a.voiceBus.gain.value};
 a.resetFight();await a.ctx.close();return {loaded:Object.keys(a.buffers).filter(k=>!['punch1','punch2','punch3','punch_heavy','punch_super','crowd','bell'].includes(k)).length,first,rejected,logs,earStarted,canceled};
}'''
with sync_playwright() as p:
 b=p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required']);page=b.new_page();page.goto('http://127.0.0.1:8780/static/boxing_core.mjs');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 dsp=page.evaluate(DSP);voice=page.evaluate(VOICE)
 assert dsp['dropAt100msDb']<=-20,dsp
 assert abs(dsp['restoreDb'])<.1 and abs(dsp['disabledDb'])<.001,dsp
 assert voice['loaded']==37,voice
 assert voice['first'][0]['priority']==60 and voice['rejected'] is False,voice
 assert voice['logs'][1]['priority']==80 and voice['logs'][1]['time']-voice['logs'][0]['time']>=3.19,voice
 assert voice['logs'][-1]['clip']=='ko_k_o',voice
 assert voice['canceled']['nodes']==0 and voice['canceled']['until']==0 and voice['canceled']['frequency']==18000 and voice['canceled']['gain']==1,voice
 assert not errors,errors
 result={'result':'PASS','checks':['4kHz world bus attenuated ≥20dB at100ms','world restored within4sec','reduced-impact DSP equals baseline','37 Victor WAVs decoded','highest-priority simultaneous voice','3.2sec narrator spacing','KO always speaks','earplug heartbeat/ring/curves canceled'],'dsp':dsp,'voice':voice,'errors':errors,'limitation':'DSP measurements, not a human audition of voice intelligibility.'}
 (OUT/'audio-web-test.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));b.close()
