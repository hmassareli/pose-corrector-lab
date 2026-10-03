"""Export the Prism boxer as FBX and a textured OBJ ZIP for Mixamo."""
from pathlib import Path
import zipfile
import json
import bpy

root = Path(__file__).resolve().parents[1]
out = root / 'assets' / 'boxer_mixamo'
out.mkdir(exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(root / 'assets' / 'boxer_prism31.glb'))
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
before = [(len(o.data.vertices), len(o.data.polygons)) for o in meshes]
for image in bpy.data.images:
    if image.type == 'IMAGE' and image.size[0]:
        image.filepath_raw = str(out / 'boxer_texture.png')
        image.file_format = 'PNG'
        image.save()
        if image.packed_file:
            image.unpack(method='USE_ORIGINAL')
        image.filepath = str(out / 'boxer_texture.png')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.fbx(filepath=str(out / 'boxer_mixamo.fbx'),
    object_types={'MESH'}, bake_anim=False, path_mode='COPY', embed_textures=True,
    axis_forward='-Z', axis_up='Y', add_leaf_bones=False)
bpy.ops.wm.obj_export(filepath=str(out / 'boxer_mixamo.obj'),
    export_materials=True, path_mode='STRIP', forward_axis='NEGATIVE_Z', up_axis='Y')
with zipfile.ZipFile(out / 'boxer_mixamo.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ['boxer_mixamo.obj', 'boxer_mixamo.mtl', 'boxer_texture.png']:
        archive.write(out / name, name)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=str(out / 'boxer_mixamo.fbx'))
after = [(len(o.data.vertices), len(o.data.polygons)) for o in bpy.context.scene.objects if o.type == 'MESH']
assert before == after, (before, after)
assert any(i.size[0] > 0 for i in bpy.data.images), 'Missing texture after FBX import'
print(json.dumps({'geometry': after, 'output': str(out), 'fbx_roundtrip': 'passed'}))
