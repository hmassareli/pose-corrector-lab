from pathlib import Path
p=Path('viewer/boxing_core.mjs');s=p.read_text()
a=s.index('export function segmentSphereContact');b=s.index('export function segmentSphere(',a)
s=s[:a]+'''export function segmentSphereContact(a,b,c,r){
 const d=b.map((v,i)=>v-a[i]),w=a.map((v,i)=>v-c[i]);
 const A=d.reduce((n,v)=>n+v*v,0),B=w.reduce((n,v,i)=>n+v*d[i],0),C=w.reduce((n,v)=>n+v*v,0)-r*r;
 if(C<=0)return 0;if(A<1e-12)return -1;
 const discriminant=B*B-A*C;if(discriminant<0)return -1;
 const t=(-B-Math.sqrt(discriminant))/A;return t>=0&&t<=1?t:-1;
}
''' + s[b:]
a=s.index('export function segmentCapsuleContact');b=s.index('// Tuning shared',a)
s=s[:a]+'''export function segmentCapsuleContact(a,b,c,d,r){
 const sub=(a,b)=>a.map((v,i)=>v-b[i]),dot=(a,b)=>a.reduce((n,v,i)=>n+v*b[i],0);
 const u=sub(b,a),v=sub(d,c),w=sub(a,c),vv=dot(v,v);
 if(vv<1e-12)return segmentSphereContact(a,b,c,r);
 const projection=clamp(dot(w,v)/vv,0,1);
 if(Math.hypot(...w.map((n,i)=>n-v[i]*projection))<=r)return 0;
 let best=Infinity;
 for(const end of [c,d]){const t=segmentSphereContact(a,b,end,r);if(t>=0)best=Math.min(best,t);}
 const uv=dot(u,v),wv=dot(w,v),A=vv*dot(u,u)-uv*uv,B=vv*dot(u,w)-uv*wv,C=vv*dot(w,w)-wv*wv-r*r*vv;
 const disc=B*B-A*C;
 if(A>1e-12&&disc>=0){
  const t=(-B-Math.sqrt(disc))/A,y=wv+t*uv;
  if(t>=0&&t<=1&&y>=0&&y<=vv)best=Math.min(best,t);
 }
 return Number.isFinite(best)?best:-1;
}
''' + s[b:]
p.write_text(s)
