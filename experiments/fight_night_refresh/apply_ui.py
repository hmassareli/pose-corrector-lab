from pathlib import Path
p=Path('pose_corrector_lab/viewer/boxing_ui.css');s=p.read_text(encoding='utf-8-sig')
s=s.replace('--ink:#0b1018;--cream:#f3f1e9;--muted:#969ba7;--gold:#e8bb71;--blue:#6bcafa;--red:#fa7c83','--ink:#080c14;--cream:#f4f6fa;--muted:#a3b0c2;--gold:#ffb21a;--blue:#009dff;--red:#ef233c')
s=s.replace('#e8bb71','#ffb21a').replace('#a9d6e4','#009dff').replace('#ff865b','#ff681e').replace('#ffd08e','#ffb21a')
a=s.index('.pow{');b=s.index('@keyframes banner-in',a)
s=s[:a]+s[b:]
a=s.index('/* Restrained impact lettering:');b=s.index('.voice-caption{',a);s=s[:a]+s[b:]
s=s.replace('#a62b3280','#df12294d').replace('#ffb21a80','#ff9b0a38').replace('0%{opacity:.65}','0%{opacity:.45}')
s=s.replace('background:linear-gradient(145deg,#1a2332f7,#0e151ffb);border:1px solid #ffffff24;border-radius:12px','background:linear-gradient(145deg,#141c29fa,#090d15fc);border:1px solid #344154;border-top:3px solid var(--red);border-radius:3px')
s=s.replace('backdrop-filter:blur(5px)','backdrop-filter:blur(3px)')
s=s.replace('background:var(--gold);border-radius:4px;color:#141519','background:linear-gradient(100deg,#e01f2e,#a00f20);border-radius:2px;color:#fff')
s=s.replace('background:#ffd79b','background:#f12b3d')
s=s.replace('border-radius:6px','border-radius:2px').replace('border-radius:4px','border-radius:2px')
s=s.replace('#d8b25a','#ffb21a').replace('#e01f26','#ef233c').replace('#c4151c','#df182c').replace('#8e0d12','#990d20')
s=s.replace('#f3ead7','#f4f6fa').replace('#ffc48e','#ffb21a')
s=s.replace('#9bd4ac','#27e495').replace('#b8cdbf','#7aebba')
s += '''
/* Shared championship surfaces: sharp panels and saturated corner identifiers. */
.health { height: 9px; background: #1a2636; box-shadow: 0 1px 0 #ffffff14; }
.health i { background: linear-gradient(90deg,#006bcc,var(--blue)); }
.right .health i { background: linear-gradient(90deg,#a70e27,var(--red)); }
.badge { border-color:#39536f; color:var(--blue); background:#081c30; border-radius:2px; }
.right .badge { color:#ff5368; background:#2a0b16; border-color:#6f2331; }
.plate strong { text-shadow:0 2px 12px #000; }
.round { padding:8px 6px; border-top:2px solid var(--gold); background:linear-gradient(#0a101dec,transparent); }
#guide { border-left:2px solid var(--blue); background:#0b121ee8; }
dialog h2 { font-family:Oswald,var(--display); font-size:34px; text-transform:uppercase; }
dialog .dialog-top { padding-bottom:4px; border-bottom:1px solid #ffffff13; margin-bottom:20px; }
dialog select:focus,dialog input:focus { border-color:var(--gold); }
dialog .primary { font-family:Oswald,var(--display); letter-spacing:2px; }
.stats>div { border-top:2px solid #314457; background:linear-gradient(145deg,#1a2533,#101722); }
.stats .new-peak { border-top-color:var(--gold); }
.stats .new-peak b { color:var(--gold); }
#result[data-outcome=lose] #resultTitle { color:var(--red); }
.timeline .bar { background:#2874a5; }
.bar[data-tier=forte] { background:var(--blue); }
.bar[data-tier=pesado] { background:var(--gold); }
.bar[data-tier=devastador] { background:#ff681e; }
#screenFx.hurt { background:radial-gradient(ellipse,transparent 66%,#ef233c55); }
#screenFx.chin { background:radial-gradient(ellipse,transparent 62%,#ff9b0a40); }
@media(max-height:650px) and (min-width:801px){.lobby-logo{top:10vh}.lobby-logo b{font-size:clamp(56px,12vh,94px)}.lobby-logo span{margin-top:12px;font-size:11px}.lobby-menu{top:51vh;gap:10px}#lobby .primary{padding:12px 22px;font-size:24px}#lobby .secondary{padding:10px 22px;font-size:20px}.fighter-card{top:15vh;padding:18px 20px}}
'''
p.write_text(s,encoding='utf-8')
