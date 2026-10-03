import json
from websockets.sync.client import connect
with connect('ws://127.0.0.1:8781/nlf',max_size=None,open_timeout=120) as ws:
 ws.send('warmup');print(json.dumps(json.loads(ws.recv(timeout=180)),indent=1))
