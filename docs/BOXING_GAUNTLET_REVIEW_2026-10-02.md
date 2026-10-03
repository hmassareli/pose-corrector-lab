# HEAVY HANDS — independent gauntlet review (2026-10-02)

Evaluator scope: implementation and evidence against **every requirement** in BOXING_FIX_PLAN_2026-10-02.md. The baseline below describes files before the implementation round; it is not a verdict on the final game. No gameplay sources were modified by the evaluator.

## Scoring rules

100 weighted points / 10 = score. Overlapping section 5 requirements are scored in their owning domain, not twice. Implemented code alone earns partial credit; explicit quantitative acceptance criteria require executed evidence. Optional features and requirements explicitly outside scope do not reduce the score. Recorded benchmark results from before the changes cannot establish acceptance of the new runtime. Browser tests that insert attacks manually do not validate the real detector. Synthetic geometry tests cannot establish webcam accuracy.

A 9.0+ verdict additionally requires no major functional break, no unresolved gameplay error in the browser, and no major knowingly unimplemented requirement. Every unavailable empirical check is identified; uncertainty is never represented as a pass.

## Baseline checklist and weighted score

| Domain (source coverage) | Weight | Baseline points | Required implementation and evidence | Baseline finding |
| --- | ---: | ---: | --- | --- |
| 0: startup crop and calibration | 8 | 0 | Reset/new-session StickyBBox; first frame synchronous detection; YOLO warmed in runtime load; plausible 1.3–2.1 m height and ~0.5 s stable calibration; calibrating status. Fresh-WS/no-priming first-second height ±3 cm, median jitter <4 cm; compare primed. | Runtime tracker shared between workers; detection asynchronous; reference fixed on first valid pose. |
| A: NLF-only legs | 4 | 1 | Delete inferred steps, feet visibility, all post-retarget leg rotations and foot IK. Preserve natural menu stance. | FootPlanting.applyInferred and foot visibility remain active. Old tests explicitly require them. |
| B: sole/canvas | 6 | 1 | Per-frame lowest native sole planted; smooth floor; no gradual drift. Replay ≥95% frames within ±2 cm. | plantGround is conditional; FootPlanting modifies legs. No acceptance measurement. |
| C: firm self contact | 4 | 1 | No 2 cm soft band; tight face envelope excluding ears; free motion outside penetration. Guard glove spread approximately source video. | SOFT_BAND=.02, softContactGap, native hull explicitly includes ears. |
| D: deterministic hands | 5 | 0 | Wrist/forearm <10°, palm 45°±10° in guard, roll with raised elbow; avoid ugly mesh fold/twist. Measure all avatars + bent/upraised guard and dynamic punches. Answer feasibility of automatic fold correction. | alignHandsToBody preserves pre-IK hand world quaternion. |
| E: torso nonpenetration | 5 | 0 | Firm rendered torso capsules, preserve jab reach; zero overlapping replay frames. | Only pelvis minimum distance 0.72 observed, no rendered capsule separation. |
| F: rendered guard only | 6 | 2 | Remove guarded(b.pose) fallback; gloves/forearms block only before target along sweep; demonstrate visible blocks and unblocked face path; replay defense fraction vs video. | Rendered hitboxes exist but simulate still sets guard from skeleton; arms disabled when dazed/recoiling. |
| G + 5.1 + 5.2: physics | 12 | 1 | Detected extension ≥1 m/s, reach ≥0.40 m; 150 ms regression; 80 kg configurable; hand .006, forearm .016, upper .027, trunk .43, head .07, coupling .18; target-direction contribution and .015 s contact. tierScaleN1200 independent maxN2500/minN80; proportional damage 1/85 head,1/120 body, chin1.35/dizzy1.3/counter1.2, cap30; <80 N zero damage. Body velocities must come from camera-space trajectory before pelvis normalization. | Runtime only two-frame wrist speed; maxDamage18 and nonlinear minimum base damage. Benchmark physics exists outside runtime. |
| H + 5.3 + 5.4: impact/feedback | 7 | 2 | Surface hold ~110 ms; both elbows 6–8°/compression 2–3 cm; ~80 ms release; force recoil, larger dazed recoil, directional gravity KO; distinct restrained VFX. Six calibrated tiers, no text below forte, LANDED/CRUSHING/DEVASTATING, stable .6 s condensed text; context tags and COMBO3+/UNSTOPPABLE7+; force-scaled stop, shake, flash, sound, bruises, stun. | Some hitstop/recoil/VFX/KO already exist; comic WORDS and random rotations remain, KO predetermined backwards, no Newton tiers. |
| I + 5.5: Victor | 8 | 0 | All selected event clips, KO/result, dazed self/opponent, chin/finisher/counter, combo3/5/7, force tiers, HP downward crossings25 once/fighter/round. One voice, 3–4 s interval, proper simultaneous priorities, KO always. Voice bus, generated1.4s reverb/35ms pre-delay/.20 wet, +3dB120Hz,18ms/-12cent/-10dB double,9kHz tail LPF. Replay cadence and audition documented. | Clips exist, no narrator runtime found. |
| J: permanent avatar outlines removal | 4 | 0 | Delete addSkinnedOutlines/outlineNormals/call/a.outlines/option/cornerOutline storage and mesh guards. Static arena outline stays. Original triangle count; FPS/pose cadence same or better. | All named legacy implementation paths still present. |
| K + 5.7 + 5.8: language/tone | 6 | 0 | English combat/HUD regardless menu language. Single strings.en/pt +data-i18n+t(); browser default; live switching incl lang, tooltips, errors, dynamic network/results/tracking texts. Short labels, no slogans/cards/promotional text/technology jargon; functional camera positioning/privacy retained. | PT literals widespread, html lang fixed pt-BR, descriptive menus. |
| 5.9: main menu/record | 4 | 0 | HEAVY HANDS/settings/3Dguard/selector/Training/Online/camera chip; Training disabled without camera. PEAK localStorage only landed punches, locale formats, hidden no record, reload preserved, general record. Result NEW PEAK; optional guard-up voice on start. | Old CORNER lobby; no peak system. |
| 5.10: result statistics | 5 | 0 | Punch register t/hand/force/target/tier/hit/combo; detector counts thrown and simulate landed. Peak N+kgf, total kN, average, accuracy; head/body peaks, combo force, high tier counts, speed, chin, blocks, rate, received damage/peak. CSS timestamp/force/tier chart; NEW PEAK bar and previous comparison; estimate tooltip, empty –/no NaN, totals equal register. | Four legacy speed/combo result fields only. |
| 5.6 + 5.11: impact samples and loser KO audio | 5 | 0 | Heavy/super WAV44.1k trimmed1.3/.8s/fades, average−15..−18dB/peak≤−1dB; replacement only for upper tiers, retain synth, metadata/CREDITS. World LPF for all audio, loser-only attenuation/bell/crowd/pitch/ring/heartbeat/voice penetration; earPlug method; option disables effect; >2kHz energy−20dB by100ms, restored≤4s. | Original MP3s not prepared/loaded. Only music muffled; KO3bells for either side. |
| 8: identity/documentation | 1 | 0 | Title/logo/aria HEAVY HANDS; remove subtitle; room HEAVY1; README/CREDITS updated; preserve saved internal settings names and boxing filenames. Explicitly identify name availability as unverified unless researched. | Title/logo CORNER, roomCORNER1, README no game identity. |
| Section 4 process + 6 acceptance/regressions | 10 | 1 | Before/after same 11min fight and cadence benchmark; ≥64/67 real punches,≤3 false positives, fist-only≤15% mean, carried guard0 events; detailed geometry/startup/UI/audio metrics; relevant core/browser/network/debug-recording tests; visually inspect avatars/menu/HUD/results and performance. | Existing test suite runs old assertions; archived benchmark is reference evidence only. |
| **Total** | **100** | **9** | **Baseline 0.9 / 10** | Intended task largely remains to implement. |

## Executed baseline validation

- `node scripts/test_boxing_core.mjs`: PASS (2026-10-02). This is an old-regression baseline; assertions demand speed damage, synthetic stepping/contact/visibility and skeleton guard, so it **does not** establish requested acceptance.
- Local services were listening on 8780/8781, process18184, at baseline inspection. Source modifications require restarting the backend before fresh-start acceptance tests; an old process is not evidence of new Python behavior.
- Existing benchmark has2016 poses/67.1s and recorded1351 repeated priming frames. This demonstrates why a cache-only run cannot prove item0.
- Browser replay, native wrist/palm geometry, new-session NLF accuracy, audio audition, audio spectral measurement and performance acceptance: **not yet executed for a changed build**.

## Concrete initial traps for implementers

1. Update stale tests rather than treating the old PASS as task completion; footwork tests currently enforce exactly the inferred gait itemA removes.
2. Replay runtime PunchDetector via JS against NPZ/timeline; the Python reference calculates candidate movement maxima over future windows, so its offline table cannot be claimed as realtime detector recall without matching/measurement.
3. Damage must use F, not tier percentage; hits above1200N still grow linearly to2500N. Touches below80N must not consume HP or falsely become landed scored punches/peak records.
4. Preserve world/camera movement for force before pose root centering; otherwise trunk/head physical contribution silently vanishes.
5. A nearest-approach segment parameter is not the first surface intersection. Verify target-before-guard ordering with analytic front/rear cases, not only broad capsule overlap.
6. All-avatar rendered torso checks need actual capsule dimensions; minimum pelvis distance alone cannot guarantee nonpenetration after leaning.
7. Reorient wrist after every corrective IK including guard contact/block/impact; correct forearm alignment before a later IK does not preserve it.
8. KO priority can preempt narration but post-KO result voice must respect one-voice/cadence. HP warning must reset every round. Simultaneous force/combo/context candidates need priority arbitration.
9. Menu locale must update already-open result content/chart/title/ARIA/status, and fixed combat notices must remain English with PT menu chosen.
10. Client1 online thrown/landed counts and persistent peak must be validated, not just host/self0. Do not trust copied mutable arrays or missing force in network inputs/effects.
11. 5.11's timeline prose has a3–6s opening example, but acceptance says normal≤4s; satisfy the explicit acceptance limit.
12. Prepared sample average/RMS and peak measurements do not replace audibility audition against the music. Flag subjective listen checks honestly if unavailable.

## Validation commands for implementation rounds

```powershell
node scripts/test_boxing_core.mjs
python scripts/test_boxing_combat_e2e.py
python scripts/test_boxing_footwork.py
python scripts/test_boxing_network.py
python scripts/test_boxing_debug_recording.py
python scripts/test_avatar_self_contact.py
python scripts/probe_boxing_fps.py
python scripts/analyze_punch_power.py ../debug_luta/corner-debug-2026-10-02T15-07-23-920Z 80
python scripts/benchmark_punch_power.py benchmarks/punch_cadence_20261002.mp4 80
```

Additional tests must cover runtime force against cached benchmark, independent physical/collision/contact metrics, UI languages/menu/record/statistics, sample measurements and WebAudio OfflineAudioContext spectral loser/option scenarios. Fresh no-cache/no-priming WS check needs its own output so benchmark source caches remain preserved.

## Round results

Baseline and intermediate rounds below are historical. The final independent verdict is recorded in round3 after them.

## Incremental audit — implementation round 1 (not a final score)

Read-only source and browser audit while implementation is still in progress. Issues were sent directly to the implementer. Files can change immediately after these observations; this is an evidence log, not a claim that every issue remains unresolved.

### Observations and corrections

- Critical hand-basis bug discovered: both constructed bases initially had determinant−1 because cross products produced a reflection. Quaternion conversion requires a right-handed basis. The implementer corrected both bases; subsequent browser evidence below confirms normalized quaternions and straight wrists.
- Native guard solver initially preserved the old hand quaternion after IK and rendering reoriented the glove afterwards. That can invalidate the measured gap. The implementation now calls deterministic hand orientation in the contact solver; multiple projection passes may still be required for residual contact.
- Capsule body separation uses XZ centers of capsule endpoints, not the closest points of capsule axes. Tilted trunks and ring-edge clamping still need executed nonpenetration evidence or a stronger solver.
- Rendered defense volumes still require confirming native glove coverage; one thin forearm capsule is not sufficient proof that a visibly larger glove blocks across its full width.
- Earplug cancellation originally did not track heartbeat nodes, and the reduced-impact option still needed checking that loser KO also retained ordinary bell/crowd behavior. These were reported for correction.
- Received-peak statistic originally included blocked punches with zero damage. Subthreshold45N journal initially retained maxComboForce45 despite hits0/peaknull. These were reported for correction.
- Online remote attack IDs now prevent duplicate attempts and allow force updates on an existing attempt; confirmed by inspection after the implementer updated the handler.
- Directional KO physics and defender elbow/compression response remain specific acceptance questions, not inferred from the existence of generic hit reactions.

### Executed browser evidence

Backend PID33572; no webcam started and no new GPU inference process launched. A fresh Chromium page loaded HEAVY HANDS with no pageerror, pt-BR default and Training disabled without camera. Menu hands on Prism and boxeador had quaternion norms≈1 and wrist/forearm angles0–0.00087°.

A read-only temporary browser stress test applied24 postures per avatar through the actual game render chain: wrist height1.45/1.65/1.82m, depth−.15/0/.15/.30m, elbow height1.3/1.7m, wrists±.10m and elbows±.30m. Smoothing0; each pose reset contact history. No pageerrors.

| Avatar | Postures | Maximum wrist angle | Minimum actual final guard gap | Finding |
| --- | ---: | ---: | ---: | --- |
| Prism | 24 | .02269° | −2.171mm | Residual penetration in right glove at wrist[−.1,1.82,.15], elbow[−.3,1.7,.05]. Before−4.199mm, correction3.547mm. Reported for iterative resolution. |
| Boxeador | 24 | .01771° | +3.9998mm | No penetration in the tested postures. |
| Fighter Web | 24 | .02262° | +4.1178mm | No penetration in the tested postures. |

This validates wrist direction for these synthetic postures only; palm45° acceptance, native mesh fold inspection, full video replay fidelity and real webcam guard spacing remain separate checks. No final grade issued.

## Independent round 2 — quantitative audit, 16:55 (provisional)

The findings above are historical: right-handed hand bases, final wrist alignment, contact iterations, closest-capsule torso separation, actual native glove defense spheres, ear-node cancellation and blocked received-peak filtering have been corrected. No implementation files were edited by the evaluator.

### Geometry actually executed

`python scripts/test_heavy_hands_geometry_review.py` uses the real browser render chain, cached NLF joints, 24 raised/bent synthetic guards, one neutral guard and four source-height offsets. 185 frames per avatar, 555 total; generated auxiliary landmarks, no new inference. Evidence: `experiments/heavy_hands_gauntlet/independent_geometry_review.json`.

| Avatar | Maximum wrist angle | Minimum contact gap | Minimum sampled native-skin gap | Maximum sole error | Frames within 2 cm |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prism | 0.0000332° | +4.558 mm | +6.847 mm | 8.000 mm | 100% |
| Boxeador | 0.0000197° | +4.000 mm | +5.086 mm | 8.000 mm | 100% |
| Fighter Web | 0.0000194° | +4.137 mm | +5.719 mm | 8.000 mm | 100% |

Quaternion norm error below 1e-7. Neutral-guard projected palm angles against fixed fighter rays: Prism46.50°/48.55°, Boxeador45.22°/45.90°, Fighter Web46.85°/46.04°. Raised elbow configurations preserve equal-angle projected bisector within0.000044°. The projected face/other rays cease to be orthogonal in arbitrary bent postures, so neither angle can always equal45°; this is geometrically expected and not an excuse to omit the neutral-guard check. Actual ray to head center differs from the fixed fighter-axis interpretation; visual and source-video guard spacing remain distinct acceptance questions. No pageerrors. This establishes measured geometry for these poses, not a proof that every vertex is free of ugly folds.

### UI, journal, combat and audio

- Independent `python scripts/test_heavy_ui_review.py`: PASS, pt-BR and en-US defaults; Training disabled without camera; no-record PEAK hidden; loaded record locale-formatted; open result language switched without reload; language, reduced-impact option and PEAK survive reload; empty main cards show four dashes with noNaN. Evidence: `independent_ui_review.json`. A minor literal5.10 gap remains in empty supporting force fields: maxComboForce and receivedPeak display0N rather than a dash when no corresponding event occurred. Counts0 are useful; absent measured forces should be dashes.
- Implementer's real-page combat E2E: PASS: clean180N gives2.118HP vs800N gives9.412HP, 1000N chin gives15.882HP, guard gives0damage and attacker recoil, an exposed head above the guard is hit, body under high guard gives6.667HP, KO opens results. Seven attempts/six landed; journal total4380N, average730N, accuracy6/7, peak1000N, result4.4kN andNEWPEAK. These injected attacks validate collision/damage/UI, not real detector recall.
- Implementer's WebAudio test: 37 Victor buffers loaded; priority and3.2s ordinary cadence; KO preempts; all8 earplug nodes canceled on option change. Offline4000Hz world-bus attenuation at100ms−63.43dB, reopened at4.1s≈0dB, disabled≈0dB. The test isolates the world bus and does not measure the deliberate bypass tinnitus/heartbeat or prove subjective intelligibility against music. Independent production-finish check with reduced impact enabled uses ordinary three-bell KO and no earplug effect. Audio graphs and cancellation are verified; human audition of5clips×4reverb settings and both samples is not claimed.
- Recorded webcam path PASS in `recorded-webcam-test.json`: actual JPEG/NLF/bridge flow, no synthetic feet. Recorded fake-camera footage establishes this integration; it is not a live-human acceptance session.

### Blocking acceptance still awaiting closure

1. **Target-direction physics in production:** at this inspection `boxing.js:814` calls `detector.update(raw,sampleTime)` and the bot also omits targetDirection, so default is wrist velocity. The optional core parameter alone does not meet G's requirement. Project velocity onto opponent direction in the appropriate source space or remeasure at contact; add an orthogonal-versus-frontal regression and preserve captured camera trajectory. Sent to implementer.
2. **Detector benchmark:** latest files are changing during tuning. A run reporting72candidate events,65matched and7unmatched has only2 unmatched events≥80N, but5sub80N extra movements. Report candidates and valid damaging punches separately with the filtering rule defined before scoring; do not call raw≤3 a pass. The one-to-one DP matcher uses±350ms explicitly; retain that tolerance and distinguish onset from peak. Fresh capture's phase14–26 previously averaged940.9N against613.4N; D2 agreement still needs the completed target-direction run.
3. **Startup:** synchronous detector/reset/warm-up and stable calibration are implemented, but fresh-versus-primed first-second and first25s height±3cm/jitter<4cm numerical outputs have not yet been delivered to this evaluator. Menu load probe is not an NLF startup acceptance test.
4. **Full11min replay:** extracted data exists, but executed final runtime aggregate of torso overlap, native sole/wrist/contact, actual defense proportion, Victor cadence and low-HP-per-round remains pending. Partial geometry and injected E2E cannot replace this evidence.
5. **Outline performance:** source removal passes inspection and static arena outline remains. Matched before/after original mesh triangle counts, FPS and NLF pose cadence must still be recorded.
6. **Online:** two-browser final result/journal/record propagation test is still running; no finalPASS claimed yet.

### Provisional weighted score

| Domain | Points / weight | Reason for withheld points |
| --- | ---: | --- |
| 0 startup | 5.5 /8 | Fresh/primed numerical height and jitter pending |
| A NLF legs | 4 /4 | Removed production synthetic-leg paths |
| B soles | 6 /6 | Independent555frames,100% within2cm |
| C self contact | 3.5 /4 | Video guard-spacing comparison pending |
| D hands | 4.5 /5 | Geometry passes; whole-mesh fold visual review pending |
| E body | 4.5 /5 | Closestcapsules and stress evidence;11min zero-overlap pending |
| F visible guard | 5.5 /6 | Real rendered E2E passes; replay defense proportion pending |
| G physics | 9 /12 | Production target direction and completed D2/recall/false acceptance |
| H impact | 6 /7 | Functional hold/compression/KO implementation; exact dynamic6–8°/2–3cm measurements pending |
| I Victor | 6.5 /8 | Executed DSP/scheduler;11min events and subjective audition pending |
| J outlines | 3.5 /4 | Matched performance comparison pending |
| K language | 6 /6 | Independent locale/result/reload checks pass |
| 5.9 menu/record | 4 /4 | Menu and real landed peak evidence pass |
| 5.10 result | 4.5 /5 | Empty support force dashes and final peer journal pending |
| 5.6/5.11 audio | 4.5 /5 | Prepared assets/DSP/option verified; subjective audition absent |
| 8 identity | 1 /1 | Game title/logo/aria/room/documentation inspection |
| 4 process/6 regressions | 4 /10 | Full replay, startup, final benchmark/network/performance incomplete |
| **Total** | **82.5 /100 = 8.25 /10** | **Provisional; no9+ approval until major gaps close** |

This is a progress score, not a stopping verdict. Evidence delivered after this timestamp can earn the withheld points without changing the fixed weights. Passing features do not conceal the named acceptance gaps.

## Independent round 3 — final verdict

**Final score:91.5/100 =9.15/10. The requested minimum9 is met.** This is an evidence-based weighted verdict, not a claim that every subjective or field acceptance check was performed. No major browser/gameplay defect identified by this evaluator remains unresolved in the audited version. The fixed baseline weights have not changed.

### Final evidence reviewed

- `startup-ws-test.json` and `scripts/test_heavy_startup.py`: actual two fresh WS sessions, no priming image before measurement, same stationary human frame30times/session. First heights1.523348/1.523176m; first-frame difference0.172mm; within-session height deviation/jitter0. Synchronous first-frame detection/reset is supported by this controlled test. Repeated identical input naturally has no physical movement noise; this does **not** establish dynamic live-human jitter or dynamic first25s invariance. Warm-up is explicit, not hidden priming.
- `benchmark_runtime_cached.json` and `benchmark_runtime_fresh.json`: both64/67 matched, one unmatched candidate; one-to-one chronological DP with stated±350ms tolerance; fist-only10.552%/10.525%. Core independently rerun: carried guard0, frontal contribution positive, orthogonal/opposite contribution0, linear mass/force/damage/tier testsPASS. Production camera-frame convention projects onto+Z and bot onto actual opponent direction. This closes the missing production target-direction call.
- D2 remains an **approximate reference, not exact acceptance passed**. Cached phase means224/450/412/543/127N; fresh299/801/412/543/126N; original D2≈270/613/599/683/136N. Direction projection differs from the old velocity-magnitude estimate, and fresh depth changes the second phase substantially. Maximum major phase deviation≈31%; points are withheld. Thresholds and masses must not be tuned solely to force agreement with these labels.
- `live11-runtime.json`: all17696old recorded raw samples processed by current calibration/detector;17641accepted/55calibrating, accepted calibration at2.200s,218attempts, mean349N. Its own limitation is correct: old158legacy hit labels are not physical hit ground truth.
- `live11-geometry-test.json` and inspected `scripts/test_heavy_live_replay.py`:17641accepted joint samples through current actual avatar corrections, both Prism fighters. GPU drawing skipped, native transforms/skin still evaluated. Soles100%within2cm, max8.016mm; torso-overlap frames0, penetration0; minpelvisdistance.720m; minimum contact+3.999mm; maxwrist.0001525°; exact post-retarget leg quaternion component change0;5ring-edge cases clear. Opponent/root state held between60saved samples, and combat/narration are not being simulated in this geometry replay. Independent185frames×3avatars complements this Prism-only full replay.
- `after_fps.txt` versus `baseline_fps.txt`: toon60.3FPS after vs60.0before; non-toon60.3vs60.3. Rendered triangles≈1.879million in both builds; additional static effects alter counts slightly. Avatar skinned-outline generation/options/storage and per-avatar guards are removed by inspection; static arena outlines retained. No matched live NLF-cadence before/after test was provided, so that subcriterion remains unverified.
- `browser-relay-test.json`: actual two browsers, duplicate remote attempt rejected, Newton force and movement replicated, air punch does not set PEAK;60history entries deliberately missing **when KO occurs**, then all61absolute slots recovered after active simulation stops. Guest and host agree total36000N/average600N/60of61, peak600N; final UI36.0kN/98% and noNaN/pageerrors. Evaluator identified the terminal race in round3; implementation now continues bounded archive transfer until result/history ACK, preserves sparse absolute slots and defensively renders available entries. Source inspected after correction; executed terminal-loss testPASS. Relay is verified; P2P equivalent transport was not separately executed in this final round.
- `footwork-test.json`: stable half-second calibration, source foot lift preserved, no invented root step/synthetic feet, metric lateral/depth translation, sole8mmPASS. `debug-recording.txt`: real encoders/ZIPCRC/nativebones/independentretargetstages/timestamps/two-view exports and repeated capturePASS.
- `audio-preparation.txt`: heavy1.3s44.1kHz,RMS−17.16dB,peak−1dB; super.8s44.1kHz,RMS−17dB,peak−2.29dB. Proven DSP/narrator checks from round2 remain valid;37loadedVictor buffers,3.2s ordinary interval, priority arbitration, KO override, worldbus−63.43dBat100ms and option cancellation. Human5clips×4reverb audition and11min combat narrator/HP event log remain unverified; no claim of subjective listeningPASS.
- Final menu screenshots of Prism/Boxeador/FighterWeb and settings en/pt visually inspected: full avatars in guard, legs untwisted, no obvious wrist fold in the pictured pose, readable concise controls, no clipped settings panel. Combat result screenshot readable with force timeline and record marker. Independent UI test rerun after latest changesPASS, no pageerrors. Received-peak absence now shows dash; empty combo force still displays0N, a small presentation gap retained in scoring.
- README/title/logo/ARIA/roomHEAVY1 and audio credits updated. Saved internal corner settings retained. Name availability explicitly remains unverified.

### Final fixed-weight score

| Requirement domain | Final points / fixed weight | Remaining deduction |
| --- | ---: | --- |
| 0 startup | 7.5 /8 | Controlled stationary WS, not dynamic live-human/first25s study |
| A NLF legs | 4 /4 | Production removal and exact0leg-component post-retarget change verified |
| B sole/canvas | 6 /6 | Full replay and independent3avatar geometry pass |
| C own-face contact | 3.5 /4 | Firm contact passes; source-video glove spacing≈1.0 not directly measured |
| D deterministic hands | 4.75 /5 | Numeric+menuvisual pass; arbitrary triangle-fold detection absent/unrequired |
| E torso collision | 5 /5 | Full joint replay0overlap plus ring-edge cases |
| F rendered guard | 5.5 /6 | First-contact/nativeglove E2E passes; annotated11min defense fraction not measured |
| G +5.1/5.2 physics | 10.5 /12 | Physical rules/recall/fist limit pass; D2phase deviations remain explicit |
| H +5.3/5.4 impact | 6 /7 | Functional hold/release/compression/directionalKO; exact both-elbow6–8° dynamic acceptance not quantified |
| I +5.5 Victor | 7 /8 | Scheduler/DSP/event hooks/roundreset verified; long combat event log and subjective audition absent |
| J outlines/performance | 3.75 /4 | Source/triangle/FPS pass; matched NLF pose cadence unverified |
| K +5.7/5.8 language | 6 /6 | Independent locales/openresult/reload+visual pass |
| 5.9 menu/record | 4 /4 | Actual landed record, persistence, empty menu and selector verified |
| 5.10 result stats | 4.75 /5 | Complete terminal online journal recovered; empty combo0N minor gap |
| 5.6/5.11 audio | 4.75 /5 | Assets/DSP/cancel/ordinaryKO pass; subjective sample audition absent |
| 8 identity | 1 /1 | Identity and explicit availability caveat verified |
| 4 process +6 regressions | 7.5 /10 | Broad executed suite/full geometry; annotated defense ground truth, narrated full combat and live cadence remain outside proven checks |
| **Total** | **91.5 /100** | **9.15 /10, approved against requested minimum9** |

The residual items above are genuinely unverified/partial and remain visible in the handoff. This approval does not turn them into passes. Further numerical tuning should preserve the physical model and add controlled labeled captures rather than hide D2 differences.

## Post-verdict stability audit — approval reopened

The91.5point verdict above is historical until this newly discovered native-server crash is corrected and the recorded-webcam/combat path revalidated. A process death is a major functional defect and overrides the numeric9+ approval rule; passing earlier geometry does not establish server stability.

### Confirmed crash evidence

Evaluator read Windows Application events around17:26:53. Event1000 identifies **python.exe PID0x8324=33572**, the NLF server, fault module`ntdll.dll`, exception`0xc0000374` (heap corruption). Associated1001APPCRASH/FaultTolerantHeap records agree. Evidence saved to `experiments/heavy_hands_gauntlet/server-native-crash-review.json`. Stderr immediately before process death reports degraded mean483.4ms, baseline34ms, p9525.6ms, drop85%, and starts asynchronous rebalance. There is no Python traceback. The event confirms native process failure; it does **not** identify which native library corrupted memory.

### Concrete source defects and minimal safe remediation

1. `_TrtRunner.__init__` originally creates logger and runtime as local variables, preserving neither while retaining engine/context. Retain one process-wide TensorRT logger plus `self.runtime`/`self.logger`; use the same logger for optional engine construction. Factory/logger lifetimes must span created objects and their use, according to [NVIDIA's object lifetime and logging documentation](https://docs.nvidia.com/deeplearning/tensorrt/latest/architecture/how-trt-works.html). The observed logger mismatch and native heap death make this a strong candidate, not a proven singular cause.
2. `_swap_lock` only snapshots backend/runner before releasing the lock; `_dispatch` can call the same DirectML session concurrently from independent WS workers, warm-up and HTTP inference. Protect dispatch with a per-engine execution lock. ONNX Runtime explicitly disallows concurrent Run calls on one DML session and requires sequential execution with memory patterns disabled; see [DirectML provider requirements](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html). The existing predictor lock protects YOLO's mutable state, not NLF sessions.
3. Rebalance creates/benches several fresh engines sharing the live TorchScript crop/decode model and GPU while live poses continue. Existing rebalance lock does not span the background job and there is no in-progress flag. Serialize native inference/warm-up/rebench/swap on a runtime gate, add try/finally in-progress bookkeeping, and synchronize outstanding CUDA work before releasing/destructing contexts. Prefer deferring expensive rebench while active sessions exist; include an explicit bounded pause if serialization is chosen. Do not bench the known pathologically slow cold TorchScript backend during live rebalancing.
4. Monitor uses arithmetic mean and drops; one huge cold outlier explains mean483ms despite p9525.6ms. Require sustained median **and** p95 degradation; frame drops alone can indicate producer overload rather than a slower backend.
5. CLI forced backend was lost because `load(backend=None)` sets `_backend_forced` from its parameter rather than resolved`self._backend`. Preserve explicit CLI backend choice.
6. Gate/bootstrap ordering must cover worker warm-up and query-weight changes: workers previously observed `_engine` before runtime readiness, and `set_dense` can mutate decode weights while inference runs. Keep lock ordering consistent and avoid waiting on the native gate while holding the short rebalance bookkeeping lock.

### Separate final-test corrections

- Final P2P artifact `browser-p2p-test.json` PASS reviewed: two actual browsers, duplicate rejection, airPEAK0,60missing entries recovered afterKO, complete36000Nterminal stats, noNaN/pageerrors. This extends the relay evidence.
- Empty combo-force UI was updated to a dash, replacing the minor0Npresentation gap. It does not compensate for an unresolved native crash.
- A repeated combat fixture exposed nondeterminism: chin_fast_open initially allowed autonomous AI/high guard and reported arm/zero damage, so that run cannot certify a chin hit. Implementer changed open guard and freezes AI; accept only an executed result asserting actual chin classification and dazed reaction after the fix.

### Stability addendum closed — latest approval9.18/10

**Latest independent score:91.75/100 =9.175/10, displayed9.18/10. Approval restored after executed revalidation.** The native crash is retained in this audit history; it is not erased or mislabeled as a Python exception. Its exact native corruption origin has not been proven by a dump, but the concrete lifetime/concurrency defects have been corrected and their affected paths exercised successfully.

- Source re-audited: process-wide retained TensorRT logger, retained runtime parent, CUDA stream synchronization under runner mutex; per-engine dispatchRLock; runtime nativeRLock across initialization, inference, warm-up, query-weight update and full rebench/swap; worker waits for runtime readiness; finally-cleared rebalance-in-progress flag; forced CLI backend retained; rolling median and p95 must both deteriorate; drops alone cannot trigger; cold TorchScript bench skipped when accelerated; boot's20%TRT robustness preference reused in rebalancing.
- `backend-stability-test.json`: PASS. Eighty actual TensorRT calls from concurrent threads with two runtimes, GC between creation/disposal and recreation; features exactly match reference(maxdifference0). Dispatch overlap-sensitive test observes maxconcurrency1; cold50soutlier with healthy95%does not trigger rebalance, sustained degradation triggers once.
- `backend-rebalance-test.json`: PASS. Real production NLF runtime, real TRT+DML rebench while12inference callers queue/execute on native gate;14totalinferences valid/finite before/during/after, no crash, flag cleared. Rebench4.758s, finalDML, maximum pose difference.02569m between providers. GPU candidates verified; CPU-only candidates not covered by this particular stress test. Legitimate live rebench intentionally pauses pose inference; this is documented behavior, not an uninterrupted-latency claim.
- `suite-result.json`, final17:51run: **17/17commands exit0**, including core, sparring clips, backend stability, fresh WS startup, benchmark, independent UI, audio, footwork, corrected chin combat, network unit, actual relay, actualP2P, debug encoders, independent3avatar geometry, full11min geometry, real backend rebalance and recorded camera. Evaluator inspected the full aggregate and underlying key artifacts.
- Corrected combat fixture freezes opponent AI and uses open guard for chin. Actual revalidated effect`chin`,15.882HP and1.88sda​​zed at.86m; separate visible-guard tests still assert zero damage. Earlier accidental arm interception is not used as chin evidence.
- Camera entry no longer discards menu-calibrated scale/floor/source pose. The same-camera reference is retained and root rebased while combat detector/statistics reset. Latest camera PASS verifies`menuCalibrationPreservedOnEntry:true`,220actualNLFobservations,15.198poses/s, maxgap254.2ms, camera-space translation, source legs, first/third view and stop-pauses-round; no pageerrors.
- Calibration evidence remains transparent: a continuously punching fixture initially timed out with server alive; an independently rerun original continuous recording then passed553poses,15.337poses/s,maxgap270.8ms(`recorded-webcam-raw-final.json`). The final deterministic fixture prefixes2srepeating its own first real image and then retains every original moving frame. This follows the existing500msstable-pose requirement instead of bypassing it. Production menu instructions now explicitly tell the person to hold still briefly in en/pt. Neither recorded-camera variant certifies a new live-human session.
- Empty combo/head/body/fastest/received-force support fields now show dashes; independent UI artifact verifies both languages. FinalP2P also exercisesKOwhile60journal entries are missing and recovers complete terminal totals. These close the previously deducted5.10presentation gap: **5.10score4.75→5.00**, the only numeric change from round3; all other fixed domain scores and disclosed deductions remain unchanged.
- 25 WAV files were exported from the actual voice graph for listening comparisons (`voice_audition`, `voice-audition.txt`). Exporting them does not imply a human audition; this remaining subjective requirement continues to lose points.

The latest9.18approval satisfies the requested minimum9 and supersedes the reopened status. Remaining deductions from round3 still apply: D2 numerical differences, stationary rather than live dynamic startup study, annotated full-fight defense proportion/narrator event log, exact dynamic bilateral elbow angles and matched NLF before/after cadence. No claim of100%empirical acceptance is made.

### Automatic mesh-fold detection/correction feasibility

Yes, possible, but wrist-bone alignment alone is insufficient. Compare skinned triangle orientation and local area against bind pose, detect flipped/collapsed triangles and excessive stretch around wrist/elbow, and sample self-intersection using a spatial acceleration structure. Stabilize alerts over several frames and exempt deliberate animation contacts. Correction can start with joint-limit/IK constraints and better twist distribution; difficult deformation cases need corrected skin weights, dual-quaternion skinning or pose-space corrective shapes. A future module should validate per-avatar thresholds and preserve the tracked pose rather than indiscriminately moving limbs. No automatic mesh-fold correction module was requested as a current implementation requirement; the current requirement is avoiding bad folds and answering feasibility honestly.


## New user feedback: restrained impact words, slower displacement and exact voice captions — review in progress

The user's subsequent instruction restores impact onomatopoeia, overriding original MD5.3's removal. This is an authorized scope change, not a failure to obey the original specification. Latest historical complete-suite score remains9.18; newly added behavior requires its own acceptance evidence.

Independent production-helper probe (`independent-impact-core-review.json`) covers24force/repetition/FPS scenarios:180/800/2500N,1/20hits,15/30/60/120Hz. All initial speeds remain<=.26m/s and one-second root travel<=.03687m. Strong KO helper reaches1.48rad and.22m; sampled peak travel speed.29997m/s, angular speed2.33624rad/s. These measurements establish the new displacement model, not rendered head/sole grounding or subjective fall quality.

Voice-caption source currently obtains text from the actual flushed clip's manifest after `src.start`, clears on reset and mute, and updates obstacles every renderframe. An independent CSS geometry probe (`scripts/test_heavy_caption_geometry_review.py`, `independent-caption-geometry-review.json`) measures actual transformed bounding boxes across1280x800,390x844,844x390 and four actual phrases at five animation times. It identifies a slot-envelope issue in the first implementation: nominal obstacle padding12px does not cover all animated transforms; mobile NOT EVEN CLOSE reaches15.5px outside the nominal left edge at100ms withopacity.58. This is a concrete insufficient margin, not proof that a fighter was covered in a particular screenshot. Implementer notified; rendered scene overlap and visibility frequency still pending. Longest tested mobile text height76px, no horizontal overflow in this isolated test.


Additional independent probe (`scripts/test_heavy_caption_mesh_review.py`, `independent-caption-mesh-review.json`) samples every seventh native skinned vertex using actual Three.js deformation and projects visible-frustum screen samples. Third-person neutral rigs are covered by bone endpoint+36px bounds in these two avatars. First-person opponent Boxeador exceeds that envelope by18.66px on its right at1280x800 and21.92px at390x844, plus.52/2.72px on its left. Thus the current skeleton envelope is not conservative for rendered geometry. Self first-person near clipping can project mesh portions far beyond valid endpoint bounds; sampled vertices include potentially backface-culled vertices, so that observation does not by itself establish actual pixel occlusion. The opponent excess is sufficient to reject the claim that zero overlap against the same rig bounds proves no coverage of the character. Implementer notified; conservative mesh/radius bounds and independent rendered overlap acceptance pending.


Implemented displacement revalidated in actual browser transform chain (`impact-feedback-test.json`): head peak world speed2.04933->1.04619m/s(-49%); KO total slide.70->.22m, peak slide speed1.10->.299919m/s(-73%); minimum native soles/head ground18.000mm; no page errors. Browser simulation used actual native rig updates but disabled drawing for trajectory loop. The supplied `impact-after-ko.png` currently shows the result modal after completion; it does not establish the visual quality of the fall or restored impact typography. Earlier CSS slot margin was increased to54px and mobile max-width to42%; this covers the previously measured animation samples, while native mesh bounds remain pending at the time of this entry.


Independent rendered captures now available (`scripts/test_heavy_impact_visual_review.py`, `independent-impact-word.png`, `independent-impact-ko-{0,500,950,1150}.png`). Evaluator viewed the impact word plus500/950msfall captures: BOOM with context/force is readable and restrained; the KO tilt progresses visibly and its reduced translation is consistent with measured dynamics. This closes the impact visual review, subject to final regression execution.

Bounds implementation subsequently switched to whole-triangle influence-signature groups and view-space AABBs of every weighted component before near-plane clipping. This addresses the cross-bone convex-combination clipping flaw identified in the previous implementation. First-person variants omit only triangles entirely discarded by the existing head-weight shader; boundary triangles stay fully represented. The geometric reasoning is sound for the current nonnegative normalized linear skinning, without morph deformations.

First independent moving-pose probe (`scripts/test_heavy_caption_dynamic_review.py`, `independent-caption-dynamic-review.json`) executes20cachedNLFmovingposes and moving roots in each of four desktop/mobile first/third contexts, recomputing native deformation and screen projection every frame. Every29thnativevertex sampled:2,614,692total screen samples, zero outside supplied regions and zero caption/character/HUD intersections. However, only desktop third-person presented captions in this sequence(20/20); the other three cases presented0/20. Hidden fallback is valid for avoiding occlusion, but it cannot certify presentation success. The first implementation generated bind groups on the first subtitle with Prism cold1.50-1.66s plus Boxeador.24-.31s, a material first-announcement freeze. Implementer notified to prewarm/bake. Hot bounds+layout third-person median.3-.5ms/p95.5-.8ms; first-person median2.4-3.4ms/p953.7-3.8ms. Source changed between contexts during development, so these are preliminary measurements pending a stable-source final rerun. The probe now records source hashes and explicitly distinguishes geometry acceptance from caption visibility.


### New caption regression: current approval withheld until corrected

Stable-source final moving probe (bounds SHA256 `623e82144d5c46dac75655d3dc4418a7af934a4f481b78fafe36ce6a46d78254`, identical before/after all four contexts) confirms zero character/HUD intersections and zero sampled vertices outside regions across2,608,995current native screen samples. Normal/first prewarming closes the first subtitle's bind-group construction stall in third-person: initial requests1.3-3.7ms for both avatars combined. However, exact near-plane refinement invokes production `mesh.getVertexPosition` over many repeated vertices per frame, causing a **critical first-person runtime performance regression**: bounds both actors median257.4/275.8ms, p95303/336.4ms desktop/mobile; bounds+layout median240.9/257.1ms. This implies roughly4FPS while the caption is processed, independent of the earlier ordinary60FPS tests. Third-person bounds+layout remains median.7/.4ms. First-person initial request itself takes355.8/271.9ms after prewarm, so the cost is posed skinning, not cache construction.

Presentation is measured honestly: dynamic desktop third20/20visible, desktop first4/20, mobile third0/20, mobile first0/20 in these specific moving poses. Earlier deterministic37cliptests can establish their own visible scenarios, but cannot replace this moving performance measurement. This source version is **not approved** despite geometry passing and the previous complete implementation's historical9.18score. Implementer notified immediately. Suggested correction precomputes posed bone/view matrices once and transforms each unique native vertex once per request using flat coordinates/weights; it must preserve complete triangle coverage, then repeat independent dynamic/overhead acceptance. Hiding when no safe slot exists remains valid, but passing by always hiding a feature is not presentation acceptance.
