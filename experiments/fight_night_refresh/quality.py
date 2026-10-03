from pathlib import Path
root=Path('pose_corrector_lab/viewer')
p=root/'boxing_arena.js';s=p.read_text(encoding='utf-8')
s=s.replace('  spot("#fff1d6", -3.2, 8.5, 2.6, 85, true);','  const keyLight = spot("#fff1d6", -3.2, 8.5, 2.6, 85, true);')
s=s.replace('  for (const [x, z] of [[-2.4, -2.4]', '  const lightCones = [];\n  for (const [x, z] of [[-2.4, -2.4]')
s=s.replace('    arena.add(cone);','    arena.add(cone);\n    lightCones.push(cone);')
s=s.replace('  const count = 204;','  const count = 204;\n  let activeCount = count, crowdInterval = 1 / 30;')
s=s.replace('t - lastCrowdUpdate < 1 / 30','t - lastCrowdUpdate < crowdInterval')
s=s.replace('    // Seated sway at rest; standing jumps when the crowd erupts.\n    for (let i = 0; i < count; i++)','    // Seated sway at rest; standing jumps when the crowd erupts.\n    for (let i = 0; i < activeCount; i++)')
s=s.replace('  return { setVenue, update, drawBoard, seats };','''  function setQuality(level) {
    activeCount = level === 'low' ? 68 : level === 'balanced' ? 136 : count;
    crowdInterval = level === 'low' ? 1 / 20 : 1 / 30;
    bodies.count = heads.count = activeCount; arms.count = legs.count = activeCount * 2;
    lightCones.forEach(c => c.visible = level !== 'low');
    const shadowSize = level === 'high' ? 2048 : 1024;
    if (keyLight.shadow.mapSize.x !== shadowSize) {
      keyLight.shadow.map?.dispose(); keyLight.shadow.map = null;
      keyLight.shadow.mapSize.set(shadowSize, shadowSize);
    }
    lastCrowdUpdate = -Infinity;
  }
  return { setVenue, setQuality, update, drawBoard, seats };''')
p.write_text(s,encoding='utf-8')
p=root/'boxing_fx.js';s=p.read_text(encoding='utf-8-sig').replace('this.type=type;this.capacity=capacity;this.cursor=0;','this.type=type;this.capacity=capacity;this.cursor=0;this.density=1;')
s=s.replace('    for(let i=0;i<count;i++){\n      const s=this.state[this.cursor];','    count=Math.ceil(count*this.density);\n    for(let i=0;i<count;i++){\n      const s=this.state[this.cursor];')
s=s.replace('  hit(position,kind,power,direction){','  setQuality(level){const density=level===\'low\'?.55:level===\'balanced\'?.8:1;this.sparks.density=this.mist.density=this.drops.density=density;}\n  hit(position,kind,power,direction){')
p.write_text(s,encoding='utf-8')
p=root/'boxing.html';s=p.read_text(encoding='utf-8');needle='<label><span data-i18n="venue">'
s=s.replace(needle,'<label data-i18n-title="qualityTip"><span data-i18n="quality">Graphics</span><select id="quality"><option value="high" data-i18n="qualityHigh">High</option><option value="balanced" data-i18n="qualityBalanced">Balanced</option><option value="low" data-i18n="qualityLow">Performance</option></select></label>\n'+needle)
p.write_text(s,encoding='utf-8')
p=root/'boxing_i18n.js';s=p.read_text(encoding='utf-8');s=s.replace("en:{hits:","en:{quality:'Graphics',qualityHigh:'High',qualityBalanced:'Balanced',qualityLow:'Performance',qualityTip:'Lower graphics to prioritize fluid movement.',hits:")
s=s.replace("pt:{hits:","pt:{quality:'Gráficos',qualityHigh:'Alto',qualityBalanced:'Equilibrado',qualityLow:'Desempenho',qualityTip:'Reduza os gráficos para priorizar movimentos fluidos.',hits:")
p.write_text(s,encoding='utf-8')
p=root/'boxing.js';s=p.read_text(encoding='utf-8');needle='const CORNER_COLORS ='
pos=s.index(needle);s=s[:pos]+'''const GRAPHICS = { high: 1.7, balanced: 1.25, low: .85 };
function setGraphics(level) {
  if (!Object.hasOwn(GRAPHICS, level)) level = 'high';
  $('quality').value = level;
  renderer.setPixelRatio(Math.min(devicePixelRatio, GRAPHICS[level]));
  const shadows = level !== 'low';
  if (renderer.shadowMap.enabled !== shadows) {
    renderer.shadowMap.enabled = shadows;
    scene.traverse(node => {
      if (!node.material) return;
      for (const m of Array.isArray(node.material) ? node.material : [node.material]) m.needsUpdate = true;
    });
  }
  arena.setQuality(level); fx.setQuality(level);
  localStorage.setItem('cornerGraphics', level);
}
setGraphics(localStorage.getItem('cornerGraphics') || 'high');
$('quality').onchange = () => setGraphics($('quality').value);
''' + s[pos:]
p.write_text(s,encoding='utf-8')
