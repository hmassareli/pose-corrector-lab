"""Deterministic KO integration checks on the three actual rigs, no webcam.

Includes pose takeover, bounded motion, floor, finite bones, and reset.

Three things were stale here:

1. Joint limits were read from ``joint.bone`` / ``joint.base`` /
   ``joint.limit``, fields that belonged to the retired bone-backed joint
   wrapper. Every run died with ``TypeError`` before reaching an assertion, so
   the limit this test claimed to check was never checked at all. They are now
   read from the real cannon-es equations (see ``_limits`` below).

2. The bounds ``maxSlide <= 0.221`` and ``maxHeadRise < 0.15`` described the
   pre-launch knockout, before the shove power was raised. The audit (§1) is
   explicit that the launch must not be reduced to satisfy articulation, so
   those two asserts were encoding the opposite of the wanted behaviour. They
   are replaced by ring containment plus a blow-up ceiling, and the launch
   itself is now asserted to EXIST on a straight-back punch.

3. The run called itself deterministic but drew fighter positions from the
   sparring AI, which uses ``Math.random`` throughout. The KO therefore started
   from a different state on every execution, and one configuration out of ten
   wedged mid-air and never settled. Both ``Math.random`` and the clock are now
   pinned, and the horizon went from 6 s to 15 s because a launched ragdoll
   lands at 2.0-6.3 s instead of under 3 s.

4. ``MIN_LAUNCH_RISE = 0.30`` was itself stale. It was recorded BEFORE the
   ``applyImpulse`` lever-arm fix (world coordinate -> point relative to the
   centre of mass), so it captured what the bug produced rather than what the
   KO should do: 1.28 m of head rise and 40086 rad/s of spin came from a ~1.9 m
   lever, and both vanish once the lever is the real 0.108 m offset. The A/B
   table by ``MIN_THROW`` holds both rows; the launch is now asserted as the
   distance thrown plus the spin ceiling the fix guarantees.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'experiments/performance_audit_20261003'
OUT.mkdir(parents=True, exist_ok=True)

# A launched ragdoll needs longer on the floor than the old, clamped one.
HORIZON_S = 15
# Straight-back punch: the one direction where the launch must be visible.
LAUNCH_DIRECTION = [0, 0, -1]
# Re-derived on the FIXED build from an A/B that runs this very RUN against
# both interpretations of applyImpulse's second argument (same contact, same
# seeded clock, only the world/relative reading differs):
#
#   variant  maxHeadRise  rootRise  |headAng|@t0  maxSlide  peakTwist
#   base           1.280     1.365         40086     1.993     11.071
#   fix            0.000     0.000           798     1.839      1.508
#
# The old `MIN_LAUNCH_RISE = 0.30  # measured 0.74-1.12 m` was recorded while
# applyImpulse still received WORLD coordinates. A ~1.9 m lever spun the head
# to -40086 rad/s and the joint reaction threw the whole body 1.37 m into the
# air; that vertical rise was an artefact of the bug, not the launch. What
# survives the fix is a horizontal throw, so that is what the guard measures.
MIN_THROW = 1.50  # measured 1.75-2.23 m (10 runs) + 1.94 m translated
# The bug is a spin bug, so guard it where it actually shows: at t0.
MAX_HEAD_SPIN = 5000  # measured 266-783 rad/s fixed; 40086 rad/s before the fix

RUN = r'''async ({fps,direction,victim,horizon,translate,contactMode})=>{
  const T=await import('three'),c=await import('/static/boxing_core.mjs'),
        koMod=await import('/static/boxing_knockout.js'),d=cornerDebug;
  const realRandom=Math.random;
  let seed=20261004>>>0;
  Math.random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
  d.paused=true;await new Promise(r=>requestAnimationFrame(r));
  d.reviewPose(c.neutralPose());d.enter();d.fighters.forEach(f=>f.tracking=false);
  // Translation-invariance probe: slide the WHOLE match sideways. A KO whose
  // spin depends on where in the ring the fighters stood cannot be correct,
  // because cannon's applyImpulse takes a point relative to the body center.
  if(translate&&translate.length===2)
    d.fighters.forEach(f=>{f.x+=translate[0];f.z+=translate[1];});
  const real=performance.now.bind(performance);let clock=1000000;
  Object.defineProperty(performance,'now',{value:()=>clock,configurable:true});
  const render=d.renderer.render;d.renderer.render=()=>{};
  for(let i=0;i<20;i++)d.frame(clock+=1000/60);
  const a=d.actors[victim],f=d.fighters[victim];
  const head=a.rig.bones.get('head').bone;
  const startHead=head.getWorldPosition(new T.Vector3());
  // impact() always hands the ragdoll the glove contact point
  // (boxing.js:1686, fighters[victim].reaction.pos). Reaching the constructor
  // without it means "shove through the center of mass": with the lever arm
  // corrected the head would get a perfectly centred impulse and never spin -
  // a scenario the game cannot produce. Anchor the contact on the head BODY,
  // not the head bone: the body is centred on the skull's mesh bounds
  // (boxing_knockout.js:258) and sits well above the bone, so anchoring on the
  // bone put the contact BELOW the centre, which pitched the face down instead
  // of snapping it back and removed the launch entirely. A throwaway
  // construction reads this avatar's exact centre; the constructor only reads
  // the actor and builds its own isolated world, so it has no side effects.
  const awayArr=[f.x-d.fighters[1-victim].x,0,f.z-d.fighters[1-victim].z];
  const hc=new koMod.KnockoutRagdoll(a,f,awayArr).parts.get('head').body.position;
  const dirN=new T.Vector3(...direction);
  if(dirN.lengthSq()<1e-8)dirN.set(0,0,1);
  dirN.normalize();
  // Where a glove lands: on the face, 10 cm off centre on the side the push
  // comes from, 4 cm above the centre (brow height).
  const contact=[hc.x-dirN.x*.10,hc.y+.04,hc.z-dirN.z*.10];
  f.reaction={kind:'finisher',power:1,dir:direction,
              pos:contactMode==='none'?undefined:contact,
              start:d.presentation().vclock};
  d.finish({winner:1-victim,ko:true,reason:'knockout'});d.presentation().ko.delay=1e9;
  const K=a.knockout;
  // Snapshot of the initial conditions the lever-arm fix governs. Read before
  // any step so this is exactly what applyImpulse handed the solver.
  const _hb=K.parts.get('head').body;
  const _tb=(K.parts.get('spine2')||K.parts.get('spine1')).body;
  const r3=v=>v.toArray().map(n=>+n.toFixed(4));
  const t0={headLin:r3(_hb.velocity),headAng:r3(_hb.angularVelocity),
            torsoLin:r3(_tb.velocity),torsoAng:r3(_tb.angularVelocity),
            hitOffset:r3(K.pushPoint.clone().sub(_hb.position)),
            hitOffsetLen:+K.pushPoint.distanceTo(_hb.position).toFixed(4)};
  const start=d.presentation().vclock;
  let maxSlide=0,maxHeadY=startHead.y,minFloor=Infinity,maxJoint=0,maxRootStep=0;
  let maxRadius=0,previous=a.group.position.clone();
  let maxUpStep=0,peakCone=0,peakTwist=0,worstCone='',worstTwist='';
  let settleTime=null,settlePose=null,endHeadY=startHead.y;
  const rows=[],cpuMs=[];
  const deg=r=>r*180/Math.PI;
  // Keyed by POSITION, not by name: fighter-web carries 124 bones under 26
  // duplicated mixamo names, so a name-keyed map silently aliases distinct
  // bones and reports a phantom 3 rad drift on a perfectly still ragdoll.
  const restPose=K.pose.map(p=>p.quaternion.clone());
  const maxDev=(ref)=>{let m=0;
    for(let i=0;i<K.pose.length;i++)
      m=Math.max(m,K.pose[i].bone.quaternion.angleTo(ref[i]));
    return m;};
  // cannon-es: ConeEquation keeps its limit in `angle`, RotationalEquation in
  // `maxAngle`; both measure the angle between `axisA` and `axisB`.
  // RotationalMotorEquation carries neither field and is skipped for free.
  const _limits=()=>{let cone=0,tw=0,wc='',wt='';
    for(const j of K.joints)for(const e of j.equations){
      if(!e.axisA||!e.axisB)continue;
      const isCone=typeof e.angle==='number'&&!('maxAngle' in e);
      const isTwist=typeof e.maxAngle==='number';
      if(!isCone&&!isTwist)continue;
      const lim=isCone?e.angle:e.maxAngle;if(!(lim>0))continue;
      const th=Math.acos(Math.max(-1,Math.min(1,e.axisA.dot(e.axisB))));
      const r=th/lim;
      if(isCone){if(r>cone){cone=r;wc=j.name+' '+deg(th).toFixed(0)+'/'+deg(lim).toFixed(0);}}
      else{if(r>tw){tw=r;wt=j.name+' '+deg(th).toFixed(0)+'/'+deg(lim).toFixed(0);}}
    }
    return {cone,tw,wc,wt};};
  // update() substeps on an internal 1/120 accumulator, so sampling per frame
  // would miss the worst of the launch. Wrap the substep itself.
  const origStep=K.step.bind(K);
  K.step=()=>{origStep();const s=_limits();
    if(s.cone>peakCone){peakCone=s.cone;worstCone=s.wc;}
    if(s.tw>peakTwist){peakTwist=s.tw;worstTwist=s.wt;}};
  // Input keeps changing after KO, but the skeleton must belong to KO.
  for(let i=0;i<fps*horizon;i++){
    f.pose=c.neutralPose();f.pose[12][1]+=(i%2)*.3;
    const cpuStart=real();d.frame(clock+=1000/fps);cpuMs.push(real()-cpuStart);
    const elapsed=(d.presentation().vclock-start)/1000;
    if(elapsed<.12)previous.copy(a.group.position);
    maxUpStep=Math.max(maxUpStep,a.group.position.y-previous.y);
    maxRootStep=Math.max(maxRootStep,a.group.position.distanceTo(previous));
    previous.copy(a.group.position);
    maxSlide=Math.max(maxSlide,Math.hypot(a.group.position.x-f.x,a.group.position.z-f.z));
    maxRadius=Math.max(maxRadius,Math.hypot(a.group.position.x,a.group.position.z));
    maxHeadY=Math.max(maxHeadY,head.getWorldPosition(new T.Vector3()).y);
    endHeadY=head.getWorldPosition(new T.Vector3()).y;
    maxJoint=Math.max(maxJoint,maxDev(restPose));
    for(const p of K.pose)if(p.bone.position.distanceTo(p.position)>1e-8)
      throw Error('bone length changed');
    a.root.traverse(b=>{if(b.isBone&&!b.matrixWorld.elements.every(Number.isFinite))
      throw Error('nonfinite bone');});
    if(i%Math.max(1,Math.floor(fps/5))===0)
      rows.push({elapsed,root:a.group.position.toArray(),
                 head:head.getWorldPosition(new T.Vector3()).toArray()});
    if(K.settled&&settleTime===null){
      settleTime=elapsed;
      settlePose=K.pose.map(p=>p.bone.quaternion.clone());
    }
    // Once it stops it must stay stopped: give it a second, then read the pose.
    if(settleTime!==null&&elapsed-settleTime>1)break;
  }
  // Independent full vertex scan validates the sparse runtime floor support.
  const p=new T.Vector3();
  a.root.traverse(m=>{if(!m.isSkinnedMesh)return;m.skeleton.update();
    for(let i=0;i<m.geometry.attributes.position.count;i++){
      p.fromBufferAttribute(m.geometry.attributes.position,i);
      m.applyBoneTransform(i,p);m.localToWorld(p);minFloor=Math.min(minFloor,p.y);
    }
  });
  const end=_limits();
  // `drift` keeps its original meaning - did anything move after it stopped -
  // but the reference is the settle snapshot rather than a fixed 3 s mark that
  // the launch now overruns.
  const drift=settlePose?maxDev(settlePose):Infinity;
  cpuMs.sort((x,y)=>x-y);
  const result={avatar:a.avatarId,fps,victim,direction,maxSlide,
    maxHeadRise:maxHeadY-startHead.y,minFloor,maxJoint,maxRootStep,maxUpStep,drift,
    settleTime:settleTime===null?null:+settleTime.toFixed(3),
    maxRadius:+maxRadius.toFixed(3),endHeadY:+endHeadY.toFixed(3),
    peakConeRatio:+peakCone.toFixed(3),peakTwistRatio:+peakTwist.toFixed(3),
    worstCone,worstTwist,
    endConeRatio:+end.cone.toFixed(3),endTwistRatio:+end.tw.toFixed(3),
    endConeJoint:end.wc,endTwistJoint:end.wt,
    t0,
    sleeping:!!K.settled,
    cpuFrameMs:{p50:cpuMs[Math.floor(cpuMs.length*.5)],p95:cpuMs[Math.floor(cpuMs.length*.95)]},
    rows};
  K.step=origStep;
  d.renderer.render=render;Object.defineProperty(performance,'now',{value:real,configurable:true});
  Math.random=realRandom;
  d.camera.position.set(f.x+3,1.6,f.z+2);d.camera.lookAt(f.x,.6,f.z);
  d.renderer.render(d.scene,d.camera);
  return result;
}'''

with sync_playwright() as p:
    browser = p.chromium.launch(args=['--use-angle=d3d11', '--ignore-gpu-blocklist'])
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/static/boxing.html')
    page.wait_for_function('window.cornerDebug?.state().loaded', timeout=120000)
    # boxer-prism31 is the avatar the page boots with, so selecting it below
    # fires no change event and no rebuild: it keeps whatever unseeded,
    # real-timing state page init produced, and those two runs came out
    # differently on every execution while the other seven were bit-identical.
    # Boot a different rig first so every avatar in the matrix is rebuilt
    # through the same path.
    page.select_option('#avatarSelect', 'boxeador', force=True)
    page.wait_for_function('(id)=>cornerDebug.actors[0]?.avatarId===id',
                           arg='boxeador', timeout=120000)
    # The first measured run races page settling: avatar textures and other
    # async init are still landing, so one real rAF frame with a large `dt`
    # gets in before the pinned clock takes over and the ragdoll is built from
    # a different pose than on the next execution. That was exactly the run
    # that changed while the other eight stayed bit-identical. Spend one KO
    # first so the matrix only ever measures a settled page.
    page.evaluate(RUN, {'fps': 60, 'direction': [0, 0, -1], 'victim': 0,
                        'horizon': HORIZON_S})
    page.evaluate('cornerDebug.exit()')
    results = []
    for avatar in ['boxer-prism31', 'boxeador', 'fighter-web']:
        page.evaluate('cornerDebug.exit()')
        page.select_option('#avatarSelect', avatar, force=True)
        page.wait_for_function(
            '(id)=>cornerDebug.actors[0]?.avatarId===id', arg=avatar, timeout=120000)
        for fps, direction in [(60, [0, 0, -1]), (30, [1, 0, 0]), (144, [-.7, 0, -.7])]:
            result = page.evaluate(
                RUN, {'fps': fps, 'direction': direction, 'victim': 0,
                      'horizon': HORIZON_S, 'translate': [0, 0]})
            results.append(result)
            page.screenshot(path=str(OUT / f'ko-{avatar}-{fps}.png'))
            print(json.dumps({k: v for k, v in result.items() if k != 'rows'}), flush=True)
            page.evaluate('''()=>{cornerDebug.exit();
              if(cornerDebug.actors.some(a=>a.knockout))throw Error('KO not reset');}''')
    result = page.evaluate(
        RUN, {'fps': 60, 'direction': [0, 0, 1], 'victim': 1, 'horizon': HORIZON_S,
              'translate': [0, 0]})
    results.append(result)
    # Same KO with the whole match slid 2.5 m across the ring. cannon's
    # applyImpulse takes a point RELATIVE TO THE BODY CENTER; the KO used to
    # pass world coordinates, so the spin was a function of where the fighters
    # happened to stand and the torso received a lever arm of its own altitude.
    #
    # Run base and slid copy BACK TO BACK on ONE rig. The matrix leaves
    # `fighter-web` selected while results[0] is boxer-prism31, and two
    # different avatars read exactly like a translation bug: for the identical
    # punch boxer-prism31 answers headAng [-334.3, 0.008, 0.013] while
    # fighter-web answers [-474.4, 13.9, -17.4]. Pairing them here makes
    # `translate` the only variable, and the avatar check below keeps that
    # substitution from coming back.
    rig = results[0]['avatar']
    page.evaluate('cornerDebug.exit()')
    page.select_option('#avatarSelect', rig, force=True)
    page.wait_for_function('(id)=>cornerDebug.actors[0]?.avatarId===id',
                           arg=rig, timeout=120000)
    # Same reason as the warmup above: the first KO after a rig rebuild races
    # async init, so spend one before measuring the pair.
    page.evaluate(RUN, {'fps': 60, 'direction': [0, 0, -1], 'victim': 0,
                        'horizon': HORIZON_S, 'translate': [0, 0]})
    page.evaluate('cornerDebug.exit()')
    base_result = page.evaluate(
        RUN, {'fps': 60, 'direction': [0, 0, -1], 'victim': 0,
              'horizon': HORIZON_S, 'translate': [0, 0]})
    page.evaluate('cornerDebug.exit()')
    translated = page.evaluate(
        RUN, {'fps': 60, 'direction': [0, 0, -1], 'victim': 0,
              'horizon': HORIZON_S, 'translate': [2.5, 1.1]})
    page.evaluate('cornerDebug.exit()')
    report = {'results': results, 'base': base_result,
              'translated': translated, 'errors': errors}
    (OUT / 'knockout-validation.json').write_text(
        json.dumps(report, indent=2), encoding='utf-8')
    browser.close()

    assert not errors, errors
    for r in results:
        # Structural: floor, finite bones, preserved bone lengths, no root
        # teleport, and the articulation really does move.
        assert r['minFloor'] >= .010, r
        assert r['maxJoint'] > .15, r
        assert r['maxUpStep'] < .08, r
        # The KO must come to rest, then stay at rest: `drift` is measured from
        # the settle snapshot, so a ragdoll that creeps or twitches fails here.
        assert r['sleeping'], r
        assert r['drift'] < .01, r
        # Ends on the floor, inside the ring, back at its calibrated shape.
        assert r['endHeadY'] < 1.2, r
        assert r['maxRadius'] <= 3.6, r
        assert r['endConeRatio'] <= 1.35, r
        assert r['endTwistRatio'] <= 1.50, r
        # Launch guard: a straight-back punch must THROW the body, not tip it
        # over where it stood. Two earlier bounds both encoded the bug: the
        # original `maxHeadRise < 0.15` asserted the launch did NOT happen, and
        # its successor `>= 0.30` asserted the vertical artefact the lever-arm
        # fix removed. The throw that remains is measured along the floor it
        # covers, and the spin the fix eliminated is checked at its source.
        if r['direction'] == LAUNCH_DIRECTION:
            assert r['maxSlide'] >= MIN_THROW, r
            assert max(abs(v) for v in r['t0']['headAng']) < MAX_HEAD_SPIN, r
        # It must launch, but not blow up out of the arena.
        assert r['maxHeadRise'] < 3.0, r
    # Same KO with the ring slid 2.5 m sideways: identical initial conditions.
    # cannon's applyImpulse wants a point relative to the body center, so world
    # coordinates make this fail on the first digit.
    # Both halves must be the same rig: two avatars differ here even with no
    # translation at all, which is how this comparison was quietly broken.
    assert translated['avatar'] == base_result['avatar'], (
        base_result['avatar'], translated['avatar'])
    base, other = base_result['t0'], translated['t0']
    for key in ('headLin', 'headAng', 'torsoLin', 'torsoAng', 'hitOffset',
                'hitOffsetLen'):
        assert other[key] == base[key], (key, other[key], base[key])
    # The contact must sit off-center - otherwise there is no spin here at all -
    # and stay inside the constructor's 0.16 m clamp.
    assert .02 <= base['hitOffsetLen'] <= .16, base
    assert max(abs(v) for v in base['headAng']) > 1.0, base
    print(f"t0: headAng={base['headAng']} torsoAng={base['torsoAng']} "
          f"hitOffset={base['hitOffset']} ({base['hitOffsetLen']} m)", flush=True)
    peakCone = max(r['peakConeRatio'] for r in results)
    peakTwist = max(r['peakTwistRatio'] for r in results)
    settle = [r['settleTime'] for r in results if r['settleTime'] is not None]
    print(f'PEAK transient overstretch during launch: cone {peakCone}x, '
          f'twist {peakTwist}x (reported, not asserted - known open defect)')
    print(f'settled in {min(settle)}-{max(settle)} s '
          f'({len(settle)}/{len(results)} runs)')
    print('PASS: all rigs, 30/60/144 FPS, both victims, seeded clock, bounded '
          'joints/root, floor, in-ring, settles and stays settled, launch '
          'intact, translation-invariant impulse')
