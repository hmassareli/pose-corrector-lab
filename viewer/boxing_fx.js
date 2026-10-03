// Fight-night presentation. Shared buffers, bounded pools; no gameplay decisions.
import * as THREE from "three";

export const INK = new THREE.Color("#080c14");
// Retained API name for arena callers; continuous lighting replaces cel bands.
export const toon = (color, extra = {}) => new THREE.MeshStandardMaterial({ color, roughness: 0.68, metalness: 0.12, ...extra });
export function toonifyAvatar(root) {
  const converted = new Map();
  root.traverse(node => {
    if (!node.isMesh || !node.material) return;
    const convert = m => {
      if (converted.has(m)) return converted.get(m);
      const material = new THREE.MeshStandardMaterial({
        name: m.name, color: m.color?.clone() ?? new THREE.Color('white'),
        map: m.map ?? null, normalMap: m.normalMap ?? null,
        emissive: m.emissive?.clone() ?? new THREE.Color('black'), emissiveMap: m.emissiveMap ?? null,
        alphaMap: m.alphaMap ?? null, alphaTest: m.alphaTest ?? 0,
        transparent: m.transparent, opacity: m.opacity, side: m.side,
        roughness: 0.66, metalness: 0.08,
      });
      if (m.normalScale) material.normalScale.copy(m.normalScale);
      converted.set(m, material);
      m.dispose();
      return material;
    };
    node.material = Array.isArray(node.material) ? node.material.map(convert) : convert(node.material);
  });
}
let glowTexture;
function glow() {
  if (glowTexture) return glowTexture;
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const x = c.getContext('2d'), g = x.createRadialGradient(32,32,0,32,32,32);
  g.addColorStop(0,'rgba(255,255,255,1)'); g.addColorStop(.18,'rgba(255,255,255,.65)'); g.addColorStop(1,'rgba(255,255,255,0)');
  x.fillStyle=g; x.fillRect(0,0,64,64);
  glowTexture=new THREE.CanvasTexture(c); glowTexture.colorSpace=THREE.SRGBColorSpace;
  return glowTexture;
}
export class CameraShake {
  constructor(){this.trauma=0;this.kick=0;this.scale=1;}
  add(amount,kick=0){this.trauma=Math.min(1,this.trauma+amount*this.scale);this.kick=Math.max(this.kick,kick*this.scale);}
  apply(camera,t,dt,amplitude){
    this.trauma=Math.max(0,this.trauma-dt*1.7);this.kick=Math.max(0,this.kick-dt*20);
    const s=this.trauma*this.trauma;
    if(s>.0001){const n=(f,p)=>Math.sin(t*f+p)*.6+Math.sin(t*f*2.31+p*1.7)*.4;
      camera.position.x+=n(37,1.3)*s*amplitude;camera.position.y+=n(41,4.1)*s*amplitude*.7;
      camera.position.z+=n(33,2.2)*s*amplitude;camera.rotateZ(n(29,.4)*s*amplitude*.35);
    }return this.kick;
  }
}

export class GloveTrail {
  constructor(scene,samples=20){
    this.n=samples;this.count=0;this.intensity=0;
    this.points=Array.from({length:samples},()=>({p:new THREE.Vector3(),age:1}));
    this.view=new THREE.Vector3();this.side=new THREE.Vector3();this.tangent=new THREE.Vector3();
    const g=new THREE.BufferGeometry();this.position=new Float32Array(samples*6);this.alpha=new Float32Array(samples*2);
    const uv=new Float32Array(samples*4),index=[];
    for(let i=0;i<samples;i++){uv.set([0,i/(samples-1),1,i/(samples-1)],i*4);if(i<samples-1){const a=i*2;index.push(a,a+1,a+2,a+1,a+3,a+2);}}
    g.setAttribute('position',new THREE.BufferAttribute(this.position,3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('alpha',new THREE.BufferAttribute(this.alpha,1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('uv',new THREE.BufferAttribute(uv,2));g.setIndex(index);
    this.color={value:new THREE.Color('#009dff')};
    this.mesh=new THREE.Mesh(g,new THREE.ShaderMaterial({
      uniforms:{color:this.color},transparent:true,depthWrite:false,side:THREE.DoubleSide,blending:THREE.AdditiveBlending,
      vertexShader:'attribute float alpha;varying float vAlpha;varying vec2 vUv;void main(){vAlpha=alpha;vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
      fragmentShader:`uniform vec3 color;varying float vAlpha;varying vec2 vUv;
      void main(){float edge=pow(max(0.0,1.0-abs(vUv.x*2.0-1.0)),.7);
      float core=pow(edge,5.0);gl_FragColor=vec4(mix(color,vec3(1.0),core*.24),vAlpha*edge*.82);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
      }`,
    }));this.mesh.name='Glove motion ribbon';this.mesh.frustumCulled=false;this.mesh.visible=false;scene.add(this.mesh);
  }
  reset(){this.count=0;this.intensity=0;this.mesh.visible=false;}
  update(point,target,color,width,camera,dt){
    dt=Math.min(.05,Math.max(0,dt));
    if(this.count && this.points[0].p.distanceToSquared(point)>.36)this.reset();
    this.intensity+=(target-this.intensity)*(1-Math.exp(-dt*(target>this.intensity?35:14)));
    for(let i=0;i<this.count;i++)this.points[i].age+=dt;
    // Reuse the oldest sample: no Vector3 or typed-array allocations per frame.
    const sample=this.points.pop();sample.p.copy(point);sample.age=0;this.points.unshift(sample);this.count=Math.min(this.n,this.count+1);
    this.mesh.visible=this.intensity>.025&&this.count>2;if(!this.mesh.visible)return;
    this.color.value.set(color);
    for(let i=0;i<this.n;i++){
      const s=this.points[Math.min(i,this.count-1)],q=this.points[Math.min(i+1,this.count-1)].p;
      this.tangent.subVectors(s.p,q);if(this.tangent.lengthSq()<1e-8)this.tangent.set(0,1,0);
      this.view.subVectors(camera.position,s.p);this.side.crossVectors(this.tangent,this.view);
      if(this.side.lengthSq()<1e-8)this.side.setFromMatrixColumn(camera.matrixWorld,0);else this.side.normalize();
      const life=Math.max(0,1-s.age/.20),w=width*(.3+.7*life),p=s.p,o=i*6;
      this.position[o]=p.x+this.side.x*w;this.position[o+1]=p.y+this.side.y*w;this.position[o+2]=p.z+this.side.z*w;
      this.position[o+3]=p.x-this.side.x*w;this.position[o+4]=p.y-this.side.y*w;this.position[o+5]=p.z-this.side.z*w;
      this.alpha[i*2]=this.alpha[i*2+1]=i<this.count?this.intensity*life*life:0;
    }
    this.mesh.geometry.attributes.position.needsUpdate=true;this.mesh.geometry.attributes.alpha.needsUpdate=true;
  }
}

// Three batches: hot streaks, cool droplets and dust. Billboards represent tiny
// volumes in world space, with velocity, drag and gravity; never screen overlays.
class ParticleBatch {
  constructor(scene,capacity,type){
    this.type=type;this.capacity=capacity;this.cursor=0;this.density=1;
    this.state=Array.from({length:capacity},()=>({life:0,total:1,p:new THREE.Vector3(),v:new THREE.Vector3(),color:new THREE.Color(),size:0,seed:0}));
    const quad=new THREE.PlaneGeometry(1,1),g=new THREE.InstancedBufferGeometry();
    g.index=quad.index;g.attributes.position=quad.attributes.position;g.attributes.uv=quad.attributes.uv;
    for(const [name,n] of [['offset',3],['velocity',3],['tint',3],['params',4]])g.setAttribute(name,new THREE.InstancedBufferAttribute(new Float32Array(capacity*n),n).setUsage(THREE.DynamicDrawUsage));
    g.instanceCount=0;
    const material=new THREE.ShaderMaterial({
      uniforms:{mode:{value:type}},transparent:true,depthWrite:false,
      blending:type===1?THREE.NormalBlending:THREE.AdditiveBlending,
      vertexShader:`attribute vec3 offset;attribute vec3 velocity;attribute vec3 tint;attribute vec4 params;
      uniform float mode;varying vec2 vUv;varying vec3 vTint;varying vec3 vParams;
      void main(){vUv=uv;vTint=tint;vParams=params.yzw;
      vec4 mv=modelViewMatrix*vec4(offset,1.0);vec2 dir=(modelViewMatrix*vec4(velocity,0.0)).xy;
      float speed=length(dir);dir=speed>.001?dir/speed:vec2(0.0,1.0);
      vec2 across=vec2(dir.y,-dir.x);float stretch=mode<.5?clamp(speed*3.4,3.0,18.0):1.0;
      mv.xy+=(across*position.x*(mode<.5?.4:1.0)+dir*position.y*stretch)*params.x;gl_Position=projectionMatrix*mv;}`,
      fragmentShader:`uniform float mode;varying vec2 vUv;varying vec3 vTint;varying vec3 vParams;
      void main(){vec2 p=vUv*2.0-1.0;float r=dot(p,p);if(r>1.0)discard;
      float a=pow(1.0-r,mode<.5?1.8:2.0);
      if(mode>.5&&mode<1.5){a*=.64+.36*sin(p.x*9.0+vParams.z)*sin(p.y*8.0+vParams.y*5.0);}
      gl_FragColor=vec4(vTint,a*vParams.x);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
      }`,
    });
    this.mesh=new THREE.Mesh(g,material);this.mesh.name=['Impact sparks','Impact mist','Sweat droplets'][type];
    this.mesh.frustumCulled=false;this.mesh.visible=false;scene.add(this.mesh);
  }
  emit(origin,direction,count,power,color){
    count=Math.ceil(count*this.density);
    for(let i=0;i<count;i++){
      const s=this.state[this.cursor];this.cursor=(this.cursor+1)%this.capacity;
      const smoke=this.type===1;
      s.total=s.life=smoke?.34+Math.random()*.28:.16+Math.random()*.32;
      s.p.copy(origin);s.p.x+=(Math.random()-.5)*.055;s.p.y+=(Math.random()-.5)*.055;s.p.z+=(Math.random()-.5)*.055;
      s.v.copy(direction).multiplyScalar(smoke?.15+power*.25:.6+power*2.0);
      const spread=smoke?.35:1.7;
      s.v.x+=(Math.random()-.5)*spread;s.v.y+=Math.random()*spread;s.v.z+=(Math.random()-.5)*spread;
      s.size=smoke?.12+Math.random()*.13:this.type===2?.012+Math.random()*.017:.008+Math.random()*.012;
      s.color.set(color);s.seed=Math.random()*20;
    }
  }
  update(dt){
    const g=this.mesh.geometry,a=g.attributes;let count=0;
    for(const s of this.state){
      if(s.life<=0)continue;s.life-=dt;if(s.life<=0)continue;
      const smoke=this.type===1,u=1-s.life/s.total;
      s.v.multiplyScalar(Math.exp(-dt*(smoke?2.8:1.2)));s.v.y+=dt*(smoke?.5:this.type===2?-7.8:-3.4);
      s.p.addScaledVector(s.v,dt);if(s.p.y<.025){s.life=0;continue;}
      a.offset.setXYZ(count,s.p.x,s.p.y,s.p.z);a.velocity.setXYZ(count,s.v.x,s.v.y,s.v.z);
      a.tint.setXYZ(count,s.color.r,s.color.g,s.color.b);
      const opacity=smoke?Math.sin(Math.PI*u)*.24:Math.min(1,(1-u)*2.5);
      a.params.setXYZW(count,s.size*(smoke?1+u*2.5:1),opacity,u,s.seed);count++;
    }
    g.instanceCount=count;this.mesh.visible=count>0;
    if(count)for(const attr of Object.values(a))if(attr.isInstancedBufferAttribute)attr.needsUpdate=true;
  }
  clear(){for(const s of this.state)s.life=0;this.mesh.visible=false;this.mesh.geometry.instanceCount=0;}
}
export class ImpactFx {
  constructor(scene){
    this.sparks=new ParticleBatch(scene,160,0);this.mist=new ParticleBatch(scene,32,1);this.drops=new ParticleBatch(scene,64,2);
    this.origin=new THREE.Vector3();this.direction=new THREE.Vector3();this.motionDirection=new THREE.Vector3();
    this.motionCarry=new Float32Array(4);
  }
  setQuality(level){const density=level==='low'?.55:level==='balanced'?.8:1;this.sparks.density=this.mist.density=this.drops.density=density;}
  hit(position,kind,power,direction){
    this.origin.fromArray(position);this.direction.set(0,.1,1);if(direction)this.direction.fromArray(direction).normalize();
    power=THREE.MathUtils.clamp(power,0,1);
    const blocked=kind==='arm'||kind==='guard',big=['chin','finisher','ko'].includes(kind);
    this.sparks.emit(this.origin,this.direction,Math.round((blocked?9:5)+power*17+(big?14:0)),power,blocked?'#009dff':big?'#ffb21a':'#ff6820');
    this.drops.emit(this.origin,this.direction,blocked?3:Math.round(4+power*10),power,'#a9dfff');
    if(power>.3||big)this.mist.emit(this.origin,this.direction,big?7:3,power,big?'#a49b89':'#8596a8');
  }
  motion(point,velocity,speed,finisher,channel,dt){
    // Rate is time-based, bounded even after stalls, and gated by measured speed.
    if(!finisher||speed<2.4||speed>14){this.motionCarry[channel]=0;return;}
    this.motionCarry[channel]+=Math.min(dt,.04)*Math.min(75,28+speed*6);
    const count=Math.floor(this.motionCarry[channel]);if(!count)return;this.motionCarry[channel]-=count;
    this.motionDirection.copy(velocity).normalize().multiplyScalar(-.4);
    this.sparks.emit(point,this.motionDirection,count,.35,'#ff9b0a');
    this.mist.emit(point,this.motionDirection,1,.12,'#8896a8');
  }
  update(dt){dt=Math.min(.05,Math.max(0,dt));this.sparks.update(dt);this.mist.update(dt);this.drops.update(dt);}
  clear(){this.sparks.clear();this.mist.clear();this.drops.clear();this.motionCarry.fill(0);}
}
// Small hot motes indicate the stun window; no cartoon stars.
export class DizzyStars {
  constructor(scene){
    this.group=new THREE.Group();this.amount=0;
    this.stars=Array.from({length:5},()=>{
      const s=new THREE.Sprite(new THREE.SpriteMaterial({map:glow(),color:'#ffab0a',transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));this.group.add(s);return s;
    });this.group.visible=false;scene.add(this.group);
  }
  update(head,active,t,dt){
    this.amount+=((active?1:0)-this.amount)*(1-Math.exp(-dt*(active?10:5)));
    this.group.visible=this.amount>.02&&!!head;if(!this.group.visible)return;
    this.group.position.copy(head);this.group.position.y+=.19;
    this.stars.forEach((s,i)=>{const a=t*1.8+i*Math.PI*2/5;
      s.position.set(Math.cos(a)*.23,.035+Math.sin(a*2)*.045,Math.sin(a)*.23);
      s.scale.setScalar(.045+.025*(.5+.5*Math.sin(t*7+i)));s.material.opacity=this.amount*.8;
    });
  }
}
export class CrowdFlashes {
  constructor(scene,seats){this.seats=seats;this.pending=0;this.sprites=Array.from({length:10},()=>{
    const s=new THREE.Sprite(new THREE.SpriteMaterial({map:glow(),color:'#d3eaff',transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));s.visible=false;scene.add(s);return {s,life:0};
  });}
  burst(n){this.pending=Math.min(20,this.pending+n);}
  update(dt,ambient){
    if(Math.random()<dt*ambient)this.pending++;
    for(const f of this.sprites){
      if(f.life>0){f.life-=dt;f.s.material.opacity=Math.max(0,f.life/.09);f.s.visible=f.life>0;}
      else if(this.pending>0&&Math.random()<.5){this.pending--;const seat=this.seats[Math.floor(Math.random()*this.seats.length)];
        f.s.position.copy(seat);f.s.position.y+=.5;f.s.scale.setScalar(.3+Math.random()*.25);f.life=.09;f.s.visible=true;
      }
    }this.pending=Math.min(this.pending,20);
  }
}
