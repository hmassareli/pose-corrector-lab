from pathlib import Path
root=Path(__file__).resolve().parents[1]/'viewer'
p=root/'boxing_core.mjs';s=p.read_text(encoding='utf-8')
s=s.replace("[0,1.72,0]]; }", "[0,1.72,0]].map(v=>[-v[0],v[1],v[2]]); }")
p.write_text(s,encoding='utf-8')
p=root/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("left_collar:[-.075,1.43,0],right_collar:[.075,1.43,0],left_eye:[-.035,1.74,.075],right_eye:[.035,1.74,.075],left_foot:[-.19,.05,.24],right_foot:[.19,.05,.09]", "left_collar:[.075,1.43,0],right_collar:[-.075,1.43,0],left_eye:[.035,1.74,.075],right_eye:[-.035,1.74,.075],left_foot:[.19,.05,.24],right_foot:[-.19,.05,.09]")
s=s.replace("h?.24:-.24,-.25,-.58-extension*.35", "h?-.2:.2,-.25,-.75-extension*.35")
s=s.replace("gloves[h].scale.set(1.4,1.3,1.65)", "gloves[h].scale.set(.85,.8,1.15)")
p.write_text(s,encoding='utf-8')
