"""Feed benchmark photos through the real /live webcam -> WS -> NLF -> avatar path.

The only in-memory HTML additions record diagnostics and set a frontal review
camera. No model, retargeting, live update, or filtering code is replaced.
"""
from pathlib import Path
import argparse, hashlib, json, time, sys
import cv2
from PIL import Image, ImageDraw, ImageOps
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PHOTOS = sorted((ROOT / 'src/benchmark_images').glob('*.jpg'))
HOLD = 6
FPS = 30
sys.stdout.reconfigure(encoding='utf-8')

def make_camera(photos, directory):
    signature = hashlib.sha256(b''.join(p.read_bytes() for p in photos)).hexdigest()[:12]
    path = directory / f'benchmark_camera_{signature}.y4m'
    if path.exists():
        return path
    with path.open('wb') as f:
        f.write(f'YUV4MPEG2 W960 H540 F{FPS}:1 Ip A1:1 C420jpeg\n'.encode())
        for photo in photos:
            bgr = cv2.resize(cv2.imread(str(photo)), (960, 540), interpolation=cv2.INTER_AREA)
            frame = cv2.cvtColor(bgr, cv2.COLOR_BGR2YUV_I420).tobytes()
            for _ in range(HOLD * FPS):
                f.write(b'FRAME\n')
                f.write(frame)
    return path

HOOK = r'''
    globalThis.__reviewFrames = [];
    globalThis.__reviewCapture = (data, seq, roundTrip) => {
      if (!avatarRig || !avatarMode) return;
      avatar.updateMatrixWorld(true);
      const bones = {};
      for (const [key, rest] of avatarRig.bones) {
        bones[key] = {q: rest.bone.getWorldQuaternion(new THREE.Quaternion()).toArray(),
                      p: rest.bone.getWorldPosition(new THREE.Vector3()).toArray()};
      }
      // Independent geometry: actual finger-bone locations, not solver target axes.
      const handGeometry = {};
      avatar.traverse(node => {
        if (!node.isBone) return;
        const name = node.name.toLowerCase().replace(/[^a-z0-9]/g, '');
        for (const side of ['left', 'right']) {
          for (const part of ['hand', 'handindex1', 'handpinky1']) {
            if (name.endsWith(side + part)) {
              handGeometry[side + '_' + part] = node.getWorldPosition(new THREE.Vector3()).toArray();
            }
          }
        }
      });
      globalThis.__reviewFrames.push({t: performance.now(), videoTime: camVideo.currentTime,
        seq, roundTrip, data, bones, handGeometry, view: lastNlfView.map(p=>Array.isArray(p)?p:p.toArray()), avatarId});
    };
    globalThis.__reviewCamera = (side=0) => {
      camera.position.set(side ? 2.8 : 0, 1.05, side ? 1.0 : 3.5);
      controls.target.set(0, 0.9, 0); controls.update();
    };
    globalThis.__reviewWarm = warmupNlf;
    globalThis.__reviewWsReady = () => nlfWs?.readyState === WebSocket.OPEN;
'''

def compare(photo, avatar, out, title):
    left = ImageOps.contain(Image.open(photo).convert('RGB'), (960, 540))
    right = ImageOps.contain(Image.open(avatar).convert('RGB'), (540, 540))
    canvas = Image.new('RGB', (1500, 582), (23, 27, 35))
    canvas.paste(left, ((960-left.width)//2, 42))
    canvas.paste(right, (960+(540-right.width)//2, 42))
    ImageDraw.Draw(canvas).text((14, 12), title + ' | Foto original (selfie) / avatar do /live', fill='white')
    canvas.save(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--avatar', default='boxeador')
    ap.add_argument('--limit', type=int, default=13)
    ap.add_argument('--port', type=int, default=8780)
    ap.add_argument('--wait-ws', action='store_true')
    ap.add_argument('--tag', default='')
    ap.add_argument('--images-dir', type=Path, default=ROOT/'src/benchmark_images')
    ap.add_argument('--output-dir', type=Path)
    ap.add_argument('--warmup-seconds', type=float, default=0)
    args = ap.parse_args()
    output = args.output_dir or HERE / (args.avatar + args.tag)
    output.mkdir(parents=True, exist_ok=True)
    photos = sorted(args.images_dir.glob('*.jpg'))[:args.limit]
    if not photos:
        raise ValueError(f'Nenhuma foto em {args.images_dir}')
    video = make_camera(photos, output)
    html = (ROOT/'viewer/live.html').read_text(encoding='utf-8')
    marker = '\n    let bootTimer = null;'
    assert marker in html
    html = html.replace(marker, '\n'+HOOK+marker, 1)
    capture_marker = '\n    }\n\n    let bootTimer = null;'
    # Capture at the end of applyNlfResult, immediately before the injected hook.
    before_hook = '\n    }\n\n'+HOOK
    assert before_hook in html
    html = html.replace(before_hook, '\n      globalThis.__reviewCapture?.(data, seq, roundTrip);\n    }\n\n'+HOOK, 1)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
            f'--use-file-for-fake-video-capture={video}', '--autoplay-policy=no-user-gesture-required',
            '--enable-unsafe-swiftshader',
            '--disable-features=LocalNetworkAccessChecks',
            '--use-gl=angle', '--use-angle=d3d11',
        ])
        context = browser.new_context(viewport={'width':1600,'height':950}, permissions=['camera'],
                                      ignore_https_errors=True)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type=='error' else None)
        base=f'http://127.0.0.1:{args.port}'
        page.route(base+'/live', lambda route: route.fulfill(body=html, content_type='text/html'))
        page.goto(base+'/live', wait_until='domcontentloaded', timeout=60_000)
        page.wait_for_function('() => typeof poseLabDebug === "function"', timeout=90_000)
        print('PAGE READY', flush=True)
        page.locator('#btnPoseNlf').click()
        if args.avatar != 'boxeador':
            page.locator('#avatarSel').select_option(args.avatar)
            page.wait_for_function('() => !document.querySelector("#avatarSel").disabled',timeout=30_000)
        page.locator('#btnAvatar').click()
        page.wait_for_function('() => poseLabDebug().avatarMode', timeout=60_000)
        page.evaluate('() => __reviewCamera()')
        if args.wait_ws:
            page.evaluate('() => __reviewWarm()')
            page.wait_for_function('() => __reviewWsReady()', timeout=20_000)
        page.locator('#btnCam').click()
        print('CAMERA REQUESTED', flush=True)
        try:
            page.wait_for_function('() => poseLabDebug().running && __reviewFrames.length>0',timeout=120_000)
        except Exception:
            page.screenshot(path=str(output/'startup_failure.png'))
            (output/'startup_failure.json').write_text(json.dumps({'errors':errors,'debug':page.evaluate('() => poseLabDebug()')},indent=2))
            raise
        print('LIVE STARTED', args.avatar, page.evaluate('() => poseLabDebug()'), flush=True)
        cycle_start = 0
        if args.warmup_seconds:
            page.wait_for_function('(t) => camVideo.currentTime >= t',arg=args.warmup_seconds,timeout=int((args.warmup_seconds+30)*1000))
            current = page.evaluate('() => camVideo.currentTime')
            cycle_start = __import__('math').ceil(current/(HOLD*len(photos))) * HOLD * len(photos)
            print('SAME CONNECTION WARMED',current,'capture cycle',cycle_start,flush=True)
        summaries=[]
        for i, photo in enumerate(photos):
            wanted = cycle_start + i * HOLD + 4
            page.wait_for_function('(t) => document.querySelector("#camVideo").currentTime >= t', arg=wanted,timeout=60_000)
            page.wait_for_function('([i,n]) => __reviewFrames.length && Math.floor(__reviewFrames.at(-1).videoTime/6)%n === i',arg=[i,len(photos)],timeout=15_000)
            page.locator('#canvas3d').screenshot(path=str(output/f'{photo.stem}_avatar.png'))
            page.screenshot(path=str(output/f'{photo.stem}_live.png'))
            # The original photo is mirrored in the live UI; use the same view here.
            mirrored=output/f'{photo.stem}_selfie.jpg'
            ImageOps.mirror(Image.open(photo)).save(mirrored)
            compare(mirrored, output/f'{photo.stem}_avatar.png', output/f'{photo.stem}_compare.png',f'Benchmark {i+1:02d} - {args.avatar}')
            snapshot=page.evaluate('() => ({frame:__reviewFrames.at(-1),debug:poseLabDebug(),fps:document.querySelector("#fpsLabel").textContent,latency:document.querySelector("#deltaLabel").textContent,video:{w:camVideo.videoWidth,h:camVideo.videoHeight,t:camVideo.currentTime}})')
            summaries.append({'image':photo.name,**snapshot})
            print('CAPTURE', i+1, snapshot['fps'], snapshot['latency'], flush=True)
        page.locator('#btnCam').click()
        frames=page.evaluate('() => __reviewFrames')
        (output/'frames.json').write_text(json.dumps(frames),encoding='utf-8')
        (output/'summary.json').write_text(json.dumps({'avatar':args.avatar,'source_sha256':hashlib.sha256((ROOT/'viewer/live.html').read_bytes()).hexdigest(),'solver_sha256':hashlib.sha256((ROOT/'viewer/mikapo_mixamo_solver.js').read_bytes()).hexdigest(),'input_images':[{'image':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in photos],'hold_seconds':HOLD,'fake_camera_fps':FPS,'capture_cycle_start':cycle_start,'frames':len(frames),'captures':summaries,'browser_errors':errors},indent=2),encoding='utf-8')
        browser.close()
    print('DONE', output, len(frames), 'frames', flush=True)

if __name__=='__main__':
    main()
