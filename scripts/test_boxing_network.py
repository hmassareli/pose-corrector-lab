"""Live relay integration checks. Start serve_boxing.py before running."""
import asyncio,json,sys
from websockets.asyncio.client import connect

async def main():
 url=sys.argv[1] if len(sys.argv)>1 else 'ws://127.0.0.1:8790'
 async with connect(url,proxy=None) as a,connect(url,proxy=None) as b:
  await a.send(json.dumps({'type':'join','room':'TEST01'}));assert json.loads(await a.recv())['slot']==0
  await b.send(json.dumps({'type':'join','room':'TEST01'}));assert json.loads(await b.recv())['slot']==1
  assert json.loads(await a.recv())['type']=='ready';assert json.loads(await b.recv())['type']=='ready'
  async with connect(url,proxy=None) as c:
   await c.send(json.dumps({'type':'join','room':'TEST01'}));assert json.loads(await c.recv())['type']=='error'
  await a.send(json.dumps({'type':'packet','seq':1,'data':{'type':'state','clock':90}}));assert json.loads(await b.recv())['data']['clock']==90
  await b.send(json.dumps({'type':'packet','seq':1,'data':{'type':'input','lateral':1}}));assert json.loads(await a.recv())['data']['lateral']==1
  await b.close();assert json.loads(await a.recv())['type']=='peer-left'
 print('PASS: roles, two-player room limit, bidirectional relay, disconnect cleanup')

asyncio.run(main())
