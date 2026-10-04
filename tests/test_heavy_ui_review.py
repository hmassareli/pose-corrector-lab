"""Independent evaluator: locale, empty stats, loaded PEAK and reducer UI."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
reports = []
with sync_playwright() as pw:
    browser = pw.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    for locale, peak in [('pt-BR', 0), ('en-US', 1234.5)]:
        ctx = browser.new_context(locale=locale, viewport={'width': 1280, 'height': 800})
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('localStorage.setItem("cornerPeakN",' + json.dumps(str(peak)) + ')')
        page.goto('http://127.0.0.1:8780/static/boxing.html', wait_until='domcontentloaded')
        page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
        state = page.evaluate('''()=>({lang:document.documentElement.lang,title:document.title,
          training:document.getElementById('train').textContent,disabled:document.getElementById('train').disabled,
          peakHidden:document.getElementById('peakRecord').hidden,peak:document.getElementById('peakValue').textContent,
          room:document.getElementById('room').value})''')
        assert state['disabled'] and state['title'] == 'HEAVY HANDS' and state['room'] == 'HEAVY1'
        assert state['peakHidden'] == (peak == 0)
        assert state['lang'] == ('pt-BR' if locale == 'pt-BR' else 'en')
        page.evaluate('''()=>{cornerDebug.enter();cornerDebug.paused=true;cornerDebug.finish({winner:0,ko:false});}''')
        result = page.evaluate('''()=>({stats:document.getElementById('resultStats').textContent,
          support:document.getElementById('resultSupport').textContent,
          bars:document.getElementById('resultTimeline').children.length,journal:cornerDebug.journal().summary(60)})''')
        assert 'NaN' not in result['stats'] + result['support']
        assert result['journal']['total'] is None and result['journal']['average'] is None
        assert result['bars'] == 0 and result['stats'].count('–') == 4
        other = 'en' if locale == 'pt-BR' else 'pt'
        switched = page.evaluate('''v=>{const el=document.getElementById('language');el.value=v;
          el.dispatchEvent(new Event('change'));return {lang:document.documentElement.lang,
            title:document.getElementById('resultTitle').textContent,stats:document.getElementById('resultStats').textContent};}''', other)
        assert switched['title'] == ('Victory' if other == 'en' else 'Vitória')
        page.evaluate('''()=>{const e=document.getElementById('reducedImpact');e.checked=true;e.dispatchEvent(new Event('change'));}''')
        option = page.evaluate('''()=>({reduced:cornerDebug.audio.reducedImpact,stored:localStorage.getItem('cornerReducedImpact')})''')
        assert option['reduced']
        page.reload(wait_until='domcontentloaded')
        page.wait_for_function('window.cornerDebug?.state().loaded', timeout=90000)
        persisted = page.evaluate('''()=>({lang:document.documentElement.lang,reduced:cornerDebug.audio.reducedImpact,
          peak:cornerDebug.peak().current,checked:document.getElementById('reducedImpact').checked})''')
        assert persisted['reduced'] and persisted['checked'] and persisted['peak'] == peak
        assert not errors
        reports.append({'locale': locale, 'initial': state, 'emptyResult': result, 'switched': switched,
                        'option': option, 'persisted': persisted, 'errors': errors})
        ctx.close()
    browser.close()
(ROOT / 'experiments/heavy_hands_gauntlet/independent_ui_review.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
print(json.dumps(reports, indent=2))
print('Independent UI review PASS')
