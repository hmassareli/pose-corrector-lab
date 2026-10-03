"""Music behaviour probe: lobby level, fight bed, dazed muffle + warble, recovery."""
import json
from playwright.sync_api import sync_playwright

READ = """()=>{const a=cornerDebug.audio;return {playing:a.musicPlaying(),ctx:a.ctx?.state,t:+(a.music?.currentTime||0).toFixed(2),
 mode:a.musicMode,gain:+(a.musicGain?.gain.value||0).toFixed(3),lowpass:Math.round(a.musicFilter?.frequency.value||0),rate:+(a.music?.playbackRate||0).toFixed(3)}}"""
with sync_playwright() as p:
    b = p.chromium.launch(channel='chrome')
    pg = b.new_page()
    errors = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto('http://127.0.0.1:8780/static/boxing.html')
    pg.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    pg.wait_for_timeout(800)
    out = {'before_gesture': pg.evaluate(READ), 'hint_visible': pg.evaluate("!document.getElementById('soundHint').hidden")}
    pg.mouse.click(700, 120)
    pg.wait_for_timeout(2500)
    out['lobby'] = pg.evaluate(READ)
    out['hint_after'] = pg.evaluate("!document.getElementById('soundHint').hidden")
    pg.evaluate("async()=>{const {neutralPose}=await import('/static/boxing_core.mjs');document.getElementById('train').click();window.__k=setInterval(()=>cornerDebug.reviewPose(neutralPose()),50);}")
    pg.wait_for_timeout(2500)
    out['fight'] = pg.evaluate(READ)
    pg.evaluate("cornerDebug.fighters[0].dizzy=3;cornerDebug.fighters[0].stun=3")
    pg.wait_for_timeout(1200)
    out['dazed'] = pg.evaluate(READ)
    pg.evaluate("cornerDebug.fighters[0].dizzy=0;cornerDebug.fighters[0].stun=0")
    pg.wait_for_timeout(2000)
    out['recovered'] = pg.evaluate(READ)
    pg.evaluate("cornerDebug.exit()")
    pg.wait_for_timeout(2000)
    out['back_to_lobby'] = pg.evaluate(READ)
    out['errors'] = errors
    print(json.dumps(out, indent=1))
    b.close()
