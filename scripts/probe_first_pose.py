import asyncio, json, time, struct, sys, cv2, websockets
img = cv2.imread(sys.argv[1])
h, w = img.shape[:2]
ok, buf = cv2.imencode(".jpg", img); jpg = buf.tobytes()
async def main():
    t0 = time.perf_counter()
    async with websockets.connect("ws://127.0.0.1:8781/nlf", max_size=8 << 20) as ws:
        await ws.send("warmup"); print("warmup", round(time.perf_counter() - t0, 2), json.loads(await ws.recv()).get("ok"))
        for i in range(1, 40):
            await ws.send(b"NLF1" + struct.pack("<I", i) + jpg)
            m = json.loads(await ws.recv())
            print(i, round(time.perf_counter() - t0, 2), m.get("ok"), m.get("error"), m.get("server_ms"))
            if m.get("ok"): break
asyncio.run(main())
