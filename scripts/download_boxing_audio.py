from pathlib import Path
import urllib.request, wave, hashlib,json
root=Path(__file__).resolve().parents[1]/'assets'/'boxing_audio'
root.mkdir(exist_ok=True)
items=[('punch1','punch_1_0.wav','DavidW','CC-BY-4.0','https://opengameart.org/node/165354'),('punch2','punch_2_0.wav','DavidW','CC-BY-4.0','https://opengameart.org/node/165354'),('punch3','punch_3_0.wav','DavidW','CC-BY-4.0','https://opengameart.org/node/165354'),('bell','boxing_matchbell.wav','Umplix','CC0-1.0','https://opengameart.org/content/boxing-ring-0'),('crowd','boxing_match_audience.wav','Umplix','CC0-1.0','https://opengameart.org/content/boxing-ring-0')]
manifest=[]
for name,file,author,license,source in items:
 target=root/(name+'.wav');url='https://opengameart.org/sites/default/files/'+file
 if not target.exists():
  req=urllib.request.Request(url,headers={'User-Agent':'CORNER asset evaluation'})
  with urllib.request.urlopen(req,timeout=30) as response: target.write_bytes(response.read())
 with wave.open(str(target)) as w: seconds=w.getnframes()/w.getframerate()
 manifest.append({'name':name,'file':target.name,'author':author,'license':license,'source':source,'download':url,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'seconds':seconds,'changes':'Unmodified original WAV'})
 print(name,round(seconds,2),target.stat().st_size,flush=True)
(root/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
(root/'CREDITS.md').write_text('# Sound credits\n\nPunch SFX by DavidW, licensed CC BY 4.0: https://opengameart.org/node/165354 — unmodified original WAV files. https://creativecommons.org/licenses/by/4.0/\n\nBoxing match bell and audience by Umplix, CC0: https://opengameart.org/content/boxing-ring-0 — unmodified original WAV files.\n\nImported 2026-10-01. Source licenses verified on asset pages; manifest contains hashes and download URLs. Cinematic mix uses gain and playback-rate variation only.\n',encoding='utf-8')
