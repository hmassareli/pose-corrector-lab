# Avatar pose bench (first pass)

- **goal**: First-pass NLF→Mixamo avatar bake for visual judgment
- **judge_priority**: ['trunk-from-waist-down fidelity', 'shoulder shrug/drop (raised/lowered) — avatar often feels locked']
- **selfie_mirror**: False
- **selfie_note**: OFF for still photos (WIN camera stills are not mirrored). Live webcam path in live.html defaults selfie ON to match CSS scaleX(-1).
- **viewer_transform**: OpenCV-ish → negate Y and Z; optional selfie negate-X + L/R swap
- **nlf_path**: YOLOv8n sticky crop → estimate_joints24 num_aug=1 → root-center metres
- **avatar**: assets/Ch28_nonPBR.fbx
- **retarget**: viewer/mikapo_mixamo_solver.js via viewer/avatar_bake.html + Playwright
