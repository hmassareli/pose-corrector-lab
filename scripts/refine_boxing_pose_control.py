from pathlib import Path
root=Path(__file__).resolve().parents[1]/'viewer';p=root/'boxing.js';s=p.read_text(encoding='utf-8')
marker="function demoAux(p)"
idx=s.index(marker)
helpers="""function constrainFacing(p,aux){const across=new THREE.Vector3(...p[8]).sub(new THREE.Vector3(...p[9]));const heading=Math.atan2(-across.z,across.x);const correction=clamp(heading,-Math.PI/15,Math.PI/15)-heading;const c=Math.cos(correction),sn=Math.sin(correction),pivot=new THREE.Vector3(...p[0]);const rotate=v=>{const x=v.x-pivot.x,z=v.z-pivot.z;v.x=pivot.x+x*c+z*sn;v.z=pivot.z-x*sn+z*c;return v;};for(let i=0;i<p.length;i++)p[i]=rotate(new THREE.Vector3(...p[i])).toArray();if(aux){const anchor=aux.pelvis?.clone()||new THREE.Vector3();for(const [key,v] of Object.entries(aux))if(v?.isVector3){const x=v.x-anchor.x,z=v.z-anchor.z;v.x=anchor.x+x*c+z*sn;v.z=anchor.z-x*sn+z*c;}}return p;}\n"""
s=s[:idx]+helpers+s[idx:]
s=s.replace("fighters[self].pose=p;fighters[self].aux=reviveAux(e.data.aux);", "const hydrated=reviveAux(e.data.aux);constrainFacing(p,hydrated);fighters[self].pose=p;fighters[self].aux=hydrated;")
s=s.replace("fighters[self].detected=fighters[self].detector.update(p,lastPoseTime);", "fighters[self].detected=fighters[self].detector.update(p,lastPoseTime);")
s=s.replace("if(online&&!fighters[1-self].tracking)", "if(online&&(!fighters[1-self].tracking||(self===0&&now-(fighters[1].lastInput||0)>1000)))")
s=s.replace("function resize(){renderer.setSize", "function resize(){renderer.setSize")
# A paused review still needs a real completed frame after WebGL resize.
s=s.replace("camera.updateProjectionMatrix();}window.addEventListener('resize'", "camera.updateProjectionMatrix();if(window.cornerDebug?.paused){requestAnimationFrame(t=>window.cornerDebug.frame(t));}}window.addEventListener('resize'")
p.write_text(s,encoding='utf-8')
p=root/'live.html';s=p.read_text(encoding='utf-8')
s=s.replace("function applyNlfResult(data, t0, seq) {", "let cornerLastNlfFrame = -1;\n    function applyNlfResult(data, t0, seq) {\n      if (new URLSearchParams(location.search).has('gameBridge') && data.joints) {\n        const fid = Number(data.frame_id ?? seq);\n        if (fid <= cornerLastNlfFrame) return;\n        cornerLastNlfFrame = fid;\n      }")
s=s.replace("async function startCamera() {", "async function startCamera() {\n      cornerLastNlfFrame = -1;")
s=s.replace("renderer.render(scene, camera);", "if (!new URLSearchParams(location.search).has('gameBridge')) renderer.render(scene, camera);")
p.write_text(s,encoding='utf-8')
