"""Convert an FBX avatar to a browser-ready GLB using Blender.

Run:
    blender --background --python scripts/convert_avatar_to_glb.py -- \
      --input "assets/boxeador mixamo trellis.fbx" \
      --output assets/boxeador_mixamo_trellis.glb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strip-animation", action="store_true")
    parser.add_argument("--rig-fbx", type=Path)
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    source = args.input.resolve()
    output = args.output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(source), use_image_search=True)
    if args.strip_animation:
        for obj in bpy.data.objects:
            obj.animation_data_clear()
            if obj.type == 'ARMATURE':
                for bone in obj.pose.bones:
                    bone.matrix_basis.identity()
        for action in list(bpy.data.actions):
            bpy.data.actions.remove(action)
        bpy.context.view_layer.update()
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        export_image_format="AUTO",
        export_materials="EXPORT",
        export_animations=not args.strip_animation,
        export_skins=True,
    )
    if args.rig_fbx:
        bpy.ops.export_scene.fbx(filepath=str(args.rig_fbx.resolve()),
            object_types={'MESH', 'ARMATURE'}, bake_anim=False,
            add_leaf_bones=False, path_mode='COPY', embed_textures=True)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
