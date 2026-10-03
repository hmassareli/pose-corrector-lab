"""Read-only tracing wrappers for runtime detection/crop dimensions."""
import sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'src'))
import nlf_bbox_track
original=nlf_bbox_track.YoloNanoPerson.detect_xywh
def detect(self,rgb):
    print('DETECT START',rgb.shape,flush=True)
    out=original(self,rgb)
    print('DETECT',rgb.shape,None if out is None else out.tolist(),flush=True)
    return out
nlf_bbox_track.YoloNanoPerson.detect_xywh=detect
import serve_lab
import threading,faulthandler
threading.Timer(25,faulthandler.dump_traceback).start()
serve_lab.main()
