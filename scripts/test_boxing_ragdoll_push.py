"""Focused browser check for the KO shove derived from the final punch vector."""
import json
from playwright.sync_api import sync_playwright

RUN = r'''async ({direction}) => {
  const c = await import('/static/boxing_core.mjs');
  const d = cornerDebug;
  d.paused = true;
  d.reviewPose(c.neutralPose());
  d.enter();
  d.fighters.forEach(f => f.tracking = false);
  for (let i = 0; i < 3; i++) d.frame(performance.now());
  const actor = d.actors[0], fighter = d.fighters[0];
  fighter.reaction = {kind:'finisher', power:1, dir:direction, start:d.presentation().vclock};
  d.finish({winner:1, ko:true, reason:'knockout'});
  d.presentation().ko.delay = 1e9;
  const start = actor.knockout.diagnostics();
  const startHips = start.parts.hips.position.slice();
  for (let i = 0; i < 6; i++) actor.knockout.update(1/120, 1/120);
  const transfer = actor.knockout.diagnostics();
  for (let i = 6; i < 480; i++) actor.knockout.update(1/120, 1/120);
  const end = actor.knockout.diagnostics();
  const delta = end.parts.hips.position.map((v, i) => v - startHips[i]);
  return {start, transfer, end, delta};
}'''

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1100, 'height': 760})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
    page.select_option('#avatarSelect', 'boxer-prism31', force=True)
    page.wait_for_function('(id)=>cornerDebug.actors[0]?.avatarId===id', arg='boxer-prism31', timeout=120000)
    result = page.evaluate(RUN, {'direction': [0, 0, -1]})
    print(json.dumps(result, indent=2))
    browser.close()
    assert not errors, errors
    direction = result['start']['pushDirection']
    assert direction and direction[2] < -0.95, direction
    assert 0.50 <= result['start']['pushImpulse'] <= 0.84, result['start']['pushImpulse']
    assert 0.08 <= result['start']['pushTorsoImpulse'] <= 0.16, result['start']['pushTorsoImpulse']
    assert result['start']['parts']['head']['speed'] > 0.05, result['start']['parts']['head']
    assert result['start']['parts']['hips']['speed'] < 0.05, result['start']['parts']['hips']
    assert result['transfer']['parts']['hips']['speed'] > 0.05, result['transfer']['parts']['hips']
    assert result['transfer']['parts']['spine2']['speed'] > 0.05, result['transfer']['parts']['spine2']
    assert result['start']['anchorError'] < 0.01, result['start']['anchorError']
    assert result['end']['settled'], result['end']
    assert result['end']['anchorError'] < 0.03, result['end']['anchorError']
    assert result['delta'][2] < -0.05, result['delta']
    print('PASS: final-punch direction produces a bounded shove and the ragdoll settles')
