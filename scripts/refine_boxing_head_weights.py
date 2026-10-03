from pathlib import Path
p=Path(__file__).resolve().parents[1]/'viewer'/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("shader.uniforms.cornerHead=a.clip.head;", "shader.uniforms.cornerHead=a.clip.head;shader.uniforms.cornerBones={value:new THREE.Vector2(n.skeleton?.bones.indexOf(a.rig.bones.get('head')?.bone)??-2,n.skeleton?.bones.indexOf(a.rig.bones.get('neck')?.bone)??-2)};")
s=s.replace("'varying vec3 cornerWorld;\\n'+shader.vertexShader", "'varying vec3 cornerWorld;varying float cornerHeadWeight;uniform vec2 cornerBones;\\nfloat cornerBoneWeight(float id,float weight){return (abs(id-cornerBones.x)<0.5||abs(id-cornerBones.y)<0.5)?weight:0.0;}\\n'+shader.vertexShader")
s=s.replace("cornerWorld=(modelMatrix*vec4(transformed,1.0)).xyz;", "cornerWorld=(modelMatrix*vec4(transformed,1.0)).xyz;\\ncornerHeadWeight=-1.0;\\n#ifdef USE_SKINNING\\ncornerHeadWeight=cornerBoneWeight(skinIndex.x,skinWeight.x)+cornerBoneWeight(skinIndex.y,skinWeight.y)+cornerBoneWeight(skinIndex.z,skinWeight.z)+cornerBoneWeight(skinIndex.w,skinWeight.w);\\n#endif\\n")
s=s.replace("'varying vec3 cornerWorld;uniform float cornerClip;", "'varying vec3 cornerWorld;varying float cornerHeadWeight;uniform float cornerClip;")
s=s.replace("if(cornerClip>0.5 && length(cornerWorld.xz-cornerHead.xz)<0.27 && cornerWorld.y>cornerHead.y-0.12) discard;", "if(cornerClip>0.5 && (cornerHeadWeight>0.08 || (cornerHeadWeight<0.0 && length(cornerWorld.xz-cornerHead.xz)<0.36 && cornerWorld.y>cornerHead.y-0.12))) discard;")
s=s.replace('corner-head-clip-v1','corner-head-clip-v2')
p.write_text(s,encoding='utf-8')
