from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("targetCamera.set(a.x,4.1,a.z).addScaledVector(forward,-4.1)", "targetCamera.set(a.x,5.2,a.z).addScaledVector(forward,-3.8)")
s=s.replace("n.visible=!hide;", "n.visible=!hide;const fade=active&&!first&&i===self&&Math.hypot(fighters[0].x-fighters[1].x,fighters[0].z-fighters[1].z)<1.6;for(const m of Array.isArray(n.material)?n.material:[n.material]){m.transparent=fade;m.opacity=fade?.32:1;m.depthWrite=!fade;}")
s=s.replace("position.z", "position.z")
p.write_text(s,encoding='utf-8')
