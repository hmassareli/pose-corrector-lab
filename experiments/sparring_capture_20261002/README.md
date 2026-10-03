# Recorded sparring strikes — 2026-10-02

Source: `C:/Users/Henrique/Pictures/Camera Roll/WIN_20261002_10_07_06_Pro.mp4`.
The container advertises 60 Hz, but its average decoded frame rate is 30.03069 Hz.
The four selected recordings retain this actual frame rate and interpolate during playback.

| Motion | Source seconds |
| --- | --- |
| Right hook | 8.025–8.924 |
| Left jab | 12.554–13.153 |
| Right straight | 14.485–15.118 |
| Left hook | 21.511–22.211 |

`*.mp4` are the cut source videos; `*_game.png` show in-game playback.
`raw.npz` caches NLF camera-space joints; `frames.json` contains canonical poses.
`manifest.json` records clip timing, active hand and measured wrist speed.
The runtime asset is `viewer/sparring_mocap.json`; no inference runs for the bot.

Rebuild from the lab directory:

```powershell
python scripts/build_sparring_library.py --refine --video 'C:/Users/Henrique/Pictures/Camera Roll/WIN_20261002_10_07_06_Pro.mp4'
node scripts/test_sparring_mocap.mjs
python scripts/test_sparring_mocap_browser.py
```

The existing local lab server must be running on port 8780 for browser validation.
Offline inference uses the existing NLF CUDA model with a fixed person crop,
a fixed hip-facing correction, canonical torso scale and mild symmetric smoothing.
Feet are partly cropped in the source, so the game keeps its existing procedural
foot placement. The AI selects the recorded clips automatically in local training;
online players continue to supply their own motion. Missing/invalid clip assets
fall back to the existing procedural bot.

Validation: four-clip timeline and wrist-auxiliary tests passed; actual browser
playback and blocked retraction passed without browser errors; existing combat
end-to-end suite passed. Subjective naturalness still requires human review.
