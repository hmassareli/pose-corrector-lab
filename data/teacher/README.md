# Saídas do teacher (GVHMR)

Cada clip:

```
<data_teacher>/<clip_id>/
  meta.json
  joints3d.npy          # (T, 16, 3) canônico do lab
  joints3d_smpl.npy     # opcional
  smplx_params.npz      # opcional
  viewer_payload.json   # para o HTML viewer
  source.<ext>          # cópia/link do vídeo
  qa.json               # opcional: ok | soft | reject
```

Visualizar:

```bash
python scripts/serve_viewer.py --clip <clip_id>
```
