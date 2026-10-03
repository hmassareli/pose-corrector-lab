from pathlib import Path
root=Path(__file__).resolve().parents[1]/'viewer';p=root/'boxing.js';s=p.read_text(encoding='utf-8')
s=s.replace("if(!cameraOn||now-lastPoseTime>500)", "if(!cameraOn||!f.tracking||now-lastPoseTime>500)")
s=s.replace("cameraOn=true;baseline=null;poseFrameTime=-1;lastPoseTime=performance.now();await bridge.start();", "cameraOn=true;fighters[self].tracking=false;baseline=null;poseFrameTime=-1;lastPoseTime=0;await bridge.start();")
s=s.replace("score:0,pose:neutralPose()", "score:0,tracking:false,pose:neutralPose()")
p.write_text(s,encoding='utf-8')
