from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
a=s.index("for(let h=0;h<2;h++){const glove=");b=s.index("updateAvatarPose({model:root",a)
s=s[:a]+s[b:]
a=s.index("for(let h=0;h<2;h++){const hand=");b=s.index("function frame(now)",a)
# Keep only renderActor's closing brace after mesh traversal.
s=s[:a]+"}\n"+s[b:]
a=s.index("if(active&&first&&actors[self]){for(let h=");b=s.index("renderer.render(scene,camera)",a)
s=s[:a]+s[b:]
s=s.replace("const hide=active&&first&&i===self;", "const hide=false;")
s=s.replace(".addScaledVector(forward,.12)", ".addScaledVector(forward,.24)")
p.write_text(s,encoding='utf-8')
