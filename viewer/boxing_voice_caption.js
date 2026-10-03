// Victor's actual spoken line, placed in free screen space at the edges.
export function overlaps(a,b){return a.x<b.x+b.width && a.x+a.width>b.x && a.y<b.y+b.height && a.y+a.height>b.y;}
export function captionSlot(width,height,w,h,obstacles,previous=null){
 const margin=24,right=width-w-margin,bottom=height-h-76;
 const center=(width-w)/2;
 const candidates=[previous,{x:margin,y:Math.max(170,height*.25)},{x:right,y:Math.max(170,height*.25)},
  {x:center,y:Math.max(170,height*.25)},
  {x:margin,y:bottom},{x:right,y:bottom},{x:(width-w)/2,y:bottom},
  {x:margin,y:height*.48},{x:right,y:height*.48},
  ...[190,210,230,250,270].flatMap(y=>[{x:margin,y},{x:right,y},{x:center,y}])].filter(Boolean);
 return candidates.find(p=>p.x>=margin && p.y>=24 && p.x+w<=width-margin && p.y+h<=height-24 &&
  // Reserve the complete slide/skew/overshoot envelope, not just layout size.
  !obstacles.some(b=>overlaps({x:p.x-54,y:p.y-20,width:w+108,height:h+40},b)))||null;
}
export class VoiceCaption {
 constructor(element,obstacles,visible){this.element=element;this.obstacles=obstacles;this.visible=visible;this.clear();}
 clear(){clearTimeout(this.timer);this.slot=null;this.line=null;this.element.hidden=true;this.element.classList.remove('show');}
 show(line){
  this.clear();if(!line?.text)return;
  this.line=line;this.element.querySelector('strong').textContent=line.text;
  this.element.dataset.clip=line.clip;this.element.dataset.priority=line.priority;
  const duration=Math.min(2.6,Math.max(1.25,line.duration+.35));
  this.element.style.setProperty('--voice-duration',duration+'s');
  this.update();this.element.classList.add('show');
  this.timer=setTimeout(()=>this.clear(),duration*1000);
 }
 update(){
  if(!this.line)return;
  const el=this.element;
  if(!this.visible()){el.hidden=true;return;}
  el.hidden=false;el.style.visibility='hidden';
  el.style.maxWidth=Math.min(290,innerWidth*(innerWidth<600?.42:.25))+'px';
  const slot=captionSlot(innerWidth,innerHeight,el.offsetWidth,el.offsetHeight,this.obstacles(),this.slot);
  el.hidden=!slot;el.style.visibility='';
  if(!slot)return;
  this.slot=slot;el.style.left=slot.x+'px';el.style.top=slot.y+'px';
  el.style.setProperty('--voice-entry',slot.x<innerWidth/2?'-28px':'28px');
 }
}
