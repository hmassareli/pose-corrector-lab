import fs from 'node:fs';
import {PunchDetector,punchTier} from './experiment_core.mjs';
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const detector=new PunchDetector(80),events=[];
for(let i=0;i<input.times.length;i++)events.push(...detector.update(input.cam[i],input.times[i]*1000,[0,0,1]));
// Chronological, one-to-one maximum matching, then minimum timestamp error.
// Labels are rounded to 100ms and mark wrist peaks, whereas detection marks onset.
// 350ms covers a 150ms regression window plus onset-to-peak and label rounding.
const tolerance=.35,used=new Set(),matched=new Map();
for(const hand of [0,1]){
 const es=events.map((e,i)=>({e,i})).filter(o=>o.e.hand===hand);
 const rs=input.reference.map((r,i)=>({r,i})).filter(o=>o.r.hand===(hand===0?'L':'R'));
 const dp=Array.from({length:rs.length+1},()=>Array.from({length:es.length+1},()=>({count:0,error:0,move:null})));
 const better=(a,b)=>a.count>b.count||(a.count===b.count&&a.error<b.error);
 for(let i=1;i<=rs.length;i++)for(let j=1;j<=es.length;j++){
  let best={...dp[i-1][j],move:'up'};
  const left={...dp[i][j-1],move:'left'};if(better(left,best))best=left;
  const error=Math.abs(rs[i-1].r.t-es[j-1].e.time/1000);
  if(error<=tolerance){const diagonal={count:dp[i-1][j-1].count+1,error:dp[i-1][j-1].error+error,move:'match'};if(better(diagonal,best))best=diagonal;}
  dp[i][j]=best;
 }
 let i=rs.length,j=es.length;
 while(i&&j){const move=dp[i][j].move;if(move==='match'){used.add(es[j-1].i);matched.set(rs[i-1].i,es[j-1].e);i--;j--;}else if(move==='up')i--;else j--;}
}
const rows=input.reference.map((ref,i)=>{const e=matched.get(i);return {...ref,detected:!!e,eventT:e?.time/1000,actualForceN:e?.forceN||0};});
const phases=[[0,12],[14,26],[30,40],[43,55],[58,66]].map(([start,end])=>{
 const chosen=rows.filter(r=>r.t>=start&&r.t<=end),found=chosen.filter(r=>r.detected);
 const all=events.filter(e=>e.time/1000>=start&&e.time/1000<=end);
 return {start,end,moves:chosen.length,detected:found.length,events:all.length,meanForceN:all.reduce((n,e)=>n+e.forceN,0)/Math.max(1,all.length),
  meanPowerPct:all.reduce((n,e)=>n+Math.min(100,e.forceN/12),0)/Math.max(1,all.length),referenceMeanForce:chosen.reduce((n,r)=>n+r.forceN,0)/Math.max(1,chosen.length)};
});
const result={poses:input.times.length,events:events.length,matched:used.size,totalReference:rows.length,matchingToleranceSeconds:tolerance,
 falseEvents:events.filter((e,i)=>!used.has(i)).map(e=>({t:e.time/1000,hand:e.hand,forceN:e.forceN,extension:e.extension})),phases,rows,
 events:events.map(e=>({...e,tier:punchTier(e.forceN).id}))};
fs.writeFileSync(process.argv[3],JSON.stringify(result,null,2));
console.log(JSON.stringify({events:events.length,matched:used.size,totalReference:rows.length,falseEvents:result.falseEvents,phases},null,2));
