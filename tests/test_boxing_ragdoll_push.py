"""Focused browser check for the KO shove derived from the final punch vector.

Two runs are compared (audit §6): the real shove, and a control built from the
same pose and the same number of steps but with every velocity zeroed right
after construction. Gravity alone still moves the ragdoll, so only the
component ALONG the punch direction proves the punch transferred momentum.
"""
import json
from playwright.sync_api import sync_playwright

RUN = r'''async ({direction, control}) => {
  const c = await import('/static/boxing_core.mjs');
  const ko = await import('/static/boxing_knockout.js');
  const d = cornerDebug;
  d.paused = true;
  d.reviewPose(c.neutralPose());
  d.enter();
  d.fighters.forEach(f => f.tracking = false);
  for (let i = 0; i < 3; i++) d.frame(performance.now());
  const actor = d.actors[0], fighter = d.fighters[0];
  fighter.reaction = {
    kind: 'finisher', power: 1, dir: direction,
    pos: [0.02, 2.14, -0.42],
    start: d.presentation().vclock,
  };
  d.finish({winner: 1, ko: true, reason: 'knockout'});
  d.presentation().ko.delay = 1e9;
  const K = actor.knockout;
  if (control) {
    // Same pose, same steps, no shove: cancel what the constructor applied
    // before the first step so only gravity acts from here on.
    for (const {body} of K.parts.values()) {
      body.velocity.setZero();
      body.angularVelocity.setZero();
    }
  }
  const start = K.diagnostics();
  const startHips = start.parts.hips.position.slice();
  for (let i = 0; i < 6; i++) K.update(1 / 120, 1 / 120);
  const transfer = K.diagnostics();
  for (let i = 6; i < 480; i++) K.update(1 / 120, 1 / 120);
  const end = K.diagnostics();
  const delta = end.parts.hips.position.map((v, i) => v - startHips[i]);
  const alongPunch = delta[0] * direction[0] + delta[1] * direction[1]
                   + delta[2] * direction[2];
  return {
    start, transfer, end, delta, alongPunch, control,
    config: {
      base: ko.KO_IMPULSE_BASE,
      perPower: ko.KO_IMPULSE_PER_POWER,
      torsoRatio: ko.KO_IMPULSE_TORSO_RATIO,
    },
  };
}'''

DIRECTION = [0, 0, -1]

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1100, 'height': 760})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
    page.select_option('#avatarSelect', 'boxer-prism31', force=True)
    page.wait_for_function(
        '(id)=>cornerDebug.actors[0]?.avatarId===id',
        arg='boxer-prism31', timeout=120000)

    result = page.evaluate(RUN, {'direction': DIRECTION, 'control': False})
    page.evaluate('cornerDebug.exit()')
    control = page.evaluate(RUN, {'direction': DIRECTION, 'control': True})
    browser.close()

    print(json.dumps({'shove': result, 'control': control}, indent=2))
    assert not errors, errors

    start = result['start']
    cfg = result['config']

    # Direction of the recorded shove.
    direction = start['pushDirection']
    assert direction and direction[2] < -0.95, direction

    # Impulse is derived from the versioned constants, never restated here.
    assert start['pushImpulse'] == cfg['base'] + cfg['perPower'], (
        start['pushImpulse'], cfg)
    assert start['pushTorsoImpulse'] == start['pushImpulse'] * cfg['torsoRatio'], (
        start['pushTorsoImpulse'], cfg)
    assert cfg['base'] > 0 and cfg['torsoRatio'] > 0, cfg

    # The shove reaches the head first, then travels down the torso.
    assert start['parts']['head']['speed'] > 0.05, start['parts']['head']
    assert start['parts']['hips']['speed'] < 0.05, start['parts']['hips']
    assert result['transfer']['parts']['hips']['speed'] > 0.05, result['transfer']['parts']['hips']
    assert result['transfer']['parts']['spine2']['speed'] > 0.05, result['transfer']['parts']['spine2']

    # Structural integrity.
    assert start['anchorError'] < 0.01, start['anchorError']
    assert result['end']['settled'], result['end']
    assert result['end']['anchorError'] < 0.03, result['end']['anchorError']

    # Gravity control: without the shove the ragdoll falls forward inside its
    # own stance and still crosses part of the punch axis, so the shove alone
    # cannot be read as momentum transfer. What proves the punch is the
    # COMPONENT ALONG the punch direction beyond that control.
    assert control['start']['parts']['head']['speed'] < 0.01, control['start']['parts']['head']
    assert result['delta'][2] < -0.05, result['delta']
    assert result['alongPunch'] > 0.05, result['alongPunch']
    assert result['alongPunch'] > control['alongPunch'] + 0.25, (
        'shove indistinguishable from gravity',
        result['alongPunch'], control['alongPunch'])

    print(
        'PASS: shove along punch axis '
        f'{result["alongPunch"]:+.3f} m vs gravity control '
        f'{control["alongPunch"]:+.3f} m; ragdoll settles')
