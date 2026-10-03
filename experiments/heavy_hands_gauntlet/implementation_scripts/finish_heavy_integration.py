from pathlib import Path
p=Path('viewer/boxing_arena.js');s=p.read_text(encoding='utf-8')
s=s.replace('Arena • noite de gala','Night').replace('Ginásio • fim de tarde','Dawn')
s=s.replace('["#1a0d3d", "#46207a", "#ff5fa2"]','["#060b17", "#14213a", "#304558"]').replace('fog: "#2a1552"','fog: "#111c30"').replace('["#d9dcff", "#4b2a66", 0.95]','["#dee8f5", "#252837", 0.95]')
s=s.replace('"CORNER"','"HEAVY HANDS"').replace('"★  WEBCAM  CHAMPIONSHIP  ★"','""').replace('CORNER  ★  CHAMPIONSHIP','HEAVY HANDS')
s=s.replace('"900 128px \'Lilita One\', Impact, sans-serif"','"900 86px \'Barlow Condensed\', Impact, sans-serif"').replace('"900 86px \'Lilita One\', Impact, sans-serif"','"900 86px \'Barlow Condensed\', Impact, sans-serif"')
p.write_text(s,encoding='utf-8')
p=Path('viewer/boxing_net.js');s=p.read_text(encoding='utf-8')
import re
s=re.sub(r'this\.onStatus\("Não foi possível conectar ao servidor\."\)','this.onStatus("connectionError")',s)
s=re.sub(r'this\.onStatus\("Conexão encerrada • luta pausada"\)','this.onStatus("disconnected")',s)
s=re.sub(r'this\.onStatus\("Sala " \+ m\.room \+ " • aguardando oponente"\)','this.onStatus("waiting")',s)
s=re.sub(r'this\.onStatus\("Duelo conectado • [^"]+"\)','this.onStatus("joined")',s)
s=re.sub(r'this\.onStatus\("Oponente desconectou • luta pausada"\)','this.onStatus("disconnected")',s)
s=s.replace('this.onStatus(m.message)','this.onStatus("connectionError")').replace('this.onStatus("Erro de protocolo: " + err.message)','this.onStatus("connectionError")')
p.write_text(s,encoding='utf-8')
p=Path('viewer/boxing.js');s=p.read_text(encoding='utf-8')
a=s.index('      if (Array.isArray(m.attacks))');b=s.index('\n    }\n    if (m.type === "state"',a)
s=s[:a]+'''      if(Array.isArray(m.attacks))for(const attack of m.attacks.slice(0,4)){
        if(![0,1].includes(attack.hand)||!Number.isInteger(attack.id)||attack.id<1)continue;
        const existing=f.attacks.find(a=>a.remoteId===attack.id);
        if(existing){existing.forceN=Math.max(existing.forceN,safeForce(Number(attack.forceN)));existing.speed=clamp(Number(attack.speed)||0,0,12);continue;}
        f.remoteIds ??= new Set();if(f.remoteIds.has(attack.id))continue;
        f.remoteIds.add(attack.id);
        if(f.remoteIds.size>4000)f.remoteIds=new Set([...f.remoteIds].slice(-1000));
        const forceN=safeForce(Number(attack.forceN)),speed=clamp(Number(attack.speed)||0,0,12);
        f.attacks.push({remoteId:attack.id,hand:attack.hand,start:performance.now(),hit:false,mocap:true,forceN,speed,
          journalIndex:f.journal.attempt({hand:attack.hand,forceN,speed},fightElapsed)});
      }''' + s[b:]
s=s.replace('      journal: f.journal.entries,','      journal: f.journal.entries.slice(-8),\n      journalOffset:Math.max(0,f.journal.entries.length-8),')
s=s.replace("          fighters[i].journal.entries=f.journal.filter(e=>Number.isFinite(e.t)&&Number.isFinite(e.forceN)).slice(-4000).map(e=>({...e,forceN:safeForce(e.forceN)}));","""          const offset=Math.max(0,Number(f.journalOffset)||0);
          const incoming=f.journal.filter(e=>Number.isFinite(e.t)&&Number.isFinite(e.forceN));
          incoming.forEach((e,k)=>fighters[i].journal.entries[offset+k]={...e,forceN:safeForce(e.forceN)});
          fighters[i].journal.entries=fighters[i].journal.entries.filter(Boolean);""")
s=s.replace('      reaction: null,\n    });','      reaction: null,\n      remoteIds:new Set(), push:null,\n    });')
s=s.replace('      forceN:hit.forceN, stroke:hit,','      forceN:hit.forceN, stroke:hit, id:hit.id,')
a=s.index('        attacks: fighters[self].attacks');b=s.index('\n      });',a)
s=s[:a]+'''        attacks: fighters[self].attacks.map(a=>({hand:a.hand,id:a.id,speed:a.stroke?.speed||a.speed||0,forceN:a.stroke?.forceN||a.forceN||0})),''' + s[b:]
a=s.index('    const key=/erro|error|falha');b=s.index('\n    $("roomStatus")',a)
s=s[:a]+"""    const key=['connectionError','disconnected','connecting','waiting','joined'].includes(s)?s:'connectionError';""" + s[b:]
p.write_text(s,encoding='utf-8')
# Remove benchmark priming. Cached baseline remains available; --fresh forces a new run.
p=Path('scripts/benchmark_punch_power.py');s=p.read_text(encoding='utf-8')
s=s.replace('if cache.exists():',"if cache.exists() and '--fresh' not in sys.argv:")
a=s.index('    # A new connection keeps');b=s.index('    while True:',a)
s=s[:a]+s[b:];s=s.replace("    ws = connect(SERVER, max_size=None, open_timeout=120)","    ws = connect(SERVER, max_size=None, open_timeout=120)\n    ws.send('warmup'); warm=json.loads(ws.recv(timeout=120))\n    if not warm.get('ok'): raise RuntimeError(warm)")
p.write_text(s,encoding='utf-8')
