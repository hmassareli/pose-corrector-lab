"""Screenshot review of the cartoon redesign (lobby, HUD, hit FX, dizzy, bruise, KO)."""
from pathlib import Path
import json, sys
from playwright.sync_api import sync_playwright

out = Path(__file__).resolve().parents[1] / 'experiments' / 'boxing_redesign' / 'after'
out.mkdir(parents=True, exist_ok=True)
errors = []
NEUTRAL = "async()=>{const {neutralPose}=await import('/static/boxing_core.mjs');cornerDebug.reviewPose(neutralPose());}"

def settle(page, ms=60):
    # Advance a few real frames so hit-stop / pops progress deterministically.
    page.evaluate(f"""async()=>{{const t0=performance.now();while(performance.now()-t0<{ms}){{await new Promise(r=>requestAnimationFrame(r));}}}}""")

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist', '--autoplay-policy=no-user-gesture-required'])
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('pageerror', lambda e: (errors.append(str(e)), print('PAGEERROR', e, flush=True)))
    page.on('console', lambda m: m.type == 'error' and (errors.append(m.text), print('CONSOLE', m.text, flush=True)))
    page.add_init_script("""(()=>{const orig=WebGL2RenderingContext.prototype.getProgramParameter;
      WebGL2RenderingContext.prototype.getProgramParameter=function(p,pname){const r=orig.call(this,p,pname);
        if(pname===this.VALIDATE_STATUS&&!r){const src=(this.getAttachedShaders(p)||[]).map(s=>this.getShaderSource(s)).join('\\n');
          (window.__bad||=[]).push({name:(src.match(/SHADER_NAME ([^\\n]+)/)||[])[1]||null,corner:/corner/.test(src),outline:/outlineNormal/.test(src),
            samplers:(src.match(/uniform sampler2D[^;]*;/g)||[]).length,shadow:/USE_SHADOWMAP/.test(src)});}
        return r;};})()""")
    page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
    page.evaluate("""()=>{window.__shaderErrors=[];cornerDebug.renderer.debug.onShaderError=(gl,program,vs,fs)=>{
      const src=gl.getShaderSource(fs)||'';const name=(src.match(/SHADER_NAME ([^\\n]+)/)||[])[1];
      window.__shaderErrors.push({name,keys:(src.match(/corner[A-Za-z]+/g)||[]).slice(0,3),validate:gl.getProgramParameter(program,gl.VALIDATE_STATUS),link:gl.getProgramParameter(program,gl.LINK_STATUS)});};}""")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out / '01-lobby.png'))
    page.evaluate("document.getElementById('train').click()")
    page.wait_for_timeout(300)
    page.evaluate(NEUTRAL)
    page.evaluate("cornerDebug.notify('',0)")
    settle(page, 400)
    page.evaluate(NEUTRAL)
    settle(page, 200)
    page.screenshot(path=str(out / '02-training.png'))
    # Clean fast hit on the sparring partner + combo.
    page.evaluate("""()=>{const f=cornerDebug.fighters;cornerDebug.reviewEffect({victim:1,kind:'clean',power:.7,head:true,dir:[0,0,1],combo:3,hand:0});}""")
    settle(page, 90)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '03-hit-clean.png'))
    settle(page, 900)
    # Chin shot that dazes the opponent: stars, banner, bruise.
    page.evaluate("""()=>{const f=cornerDebug.fighters;f[1].dizzy=2.2;f[1].stun=2.2;cornerDebug.reviewEffect({victim:1,kind:'chin',power:.95,head:true,dir:[0,.2,1],combo:4,dizzy:true,hand:1});}""")
    settle(page, 140)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '04-chin-dizzy.png'))
    settle(page, 600)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '05-dizzy-stars.png'))
    # Arm block: attacker hand held on the guard.
    page.evaluate("""()=>{const f=cornerDebug.fighters;f[1].dizzy=0;f[1].stun=0;f[0].recoil=.45;cornerDebug.reviewEffect({victim:1,kind:'arm',blocked:true,power:.5,head:true,dir:[0,0,1],hand:0,arm:0});}""")
    settle(page, 100)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '06-arm-block.png'))
    # Self gets hit: hurt flash and shake.
    page.evaluate("""()=>{cornerDebug.reviewEffect({victim:0,kind:'clean',power:.8,head:true,dir:[0,0,-1],hand:0});}""")
    settle(page, 60)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '07-self-hurt.png'))
    settle(page, 500)
    # Settings dialog.
    page.evaluate("document.getElementById('settingsButton').click()")
    page.wait_for_timeout(350)
    page.screenshot(path=str(out / '08-settings.png'))
    page.evaluate("document.getElementById('settings').close()")
    # First person.
    page.evaluate("document.getElementById('view').value='first';cornerDebug.view()")
    page.evaluate(NEUTRAL)
    settle(page, 300)
    page.evaluate(NEUTRAL)
    page.screenshot(path=str(out / '09-first.png'))
    page.evaluate("document.getElementById('view').value='third';cornerDebug.view()")
    # KO sequence and result card.
    page.evaluate("""()=>{const f=cornerDebug.fighters;f[0].stats.maxCombo=4;f[0].stats.chin=1;f[0].stats.fastest=4.6;f[0].score=12;f[1].hp=0;cornerDebug.finish({winner:0,reason:'Nocaute',ko:true});}""")
    settle(page, 1300)
    page.screenshot(path=str(out / '10-ko.png'))
    settle(page, 2000)
    page.screenshot(path=str(out / '11-result.png'))
    page.set_viewport_size({'width': 1366, 'height': 768})
    page.evaluate("cornerDebug.exit()")
    settle(page, 1200)
    page.screenshot(path=str(out / '12-lobby-small.png'))
    print(json.dumps({'errors': errors, 'shaderErrors': page.evaluate('window.__bad||[]'), 'state': page.evaluate('cornerDebug.state()')}, default=str))
    browser.close()
sys.exit(1 if errors else 0)
