"""WAN22 Scene Lab 0.1.2 — offline preparation, no network or GPU calls."""
import argparse
import copy
import hashlib
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path

VERSION = '0.1.2'
ROOT = Path(__file__).resolve().parent

def build(baseline, scene=False, combined=False):
    w = copy.deepcopy(baseline)
    if w['381']['class_type'] != 'WanAnimateToVideo':
        raise ValueError('Expected native WanAnimateToVideo; refusing other implementations')
    if not scene:
        return w
    def node(kind, inputs, title):
        return {'class_type': kind, 'inputs': inputs, '_meta': {'title': title}}
    if combined:
        # This reference already contains the desired person AND scene.
        for name in ('background_video', 'character_mask'):
            w['381']['inputs'].pop(name, None)
        return w
    w['900'] = node('LoadImage', {'image': 'LAB_SCENE.png'}, 'New Scene')
    w['901'] = copy.deepcopy(w['371'])
    w['901']['inputs']['image'] = ['900', 0]
    w['902'] = copy.deepcopy(w['360'])
    w['902']['inputs']['images'] = ['371', 0]
    # Reuse existing pinned detection/SAM2 types, not Wrapper sampling nodes.
    w['903'] = copy.deepcopy(w['361'])
    w['903']['inputs'].update(image=['371', 0], bboxes=['902', 3])
    w['904'] = node('ImageCompositeMasked', {
        'destination': ['901', 0], 'source': ['371', 0],
        'x': 0, 'y': 0, 'resize_source': False, 'mask': ['903', 0]
    }, 'Automatic New Person + New Scene Reference')
    w['905'] = node('SaveImage', {'images': ['904', 0], 'filename_prefix': 'lab/reference'}, 'Inspect Reference Composition')
    w['351']['inputs']['image'] = ['904', 0]
    w['381']['inputs']['reference_image'] = ['904', 0]
    for name in ('background_video', 'character_mask'):
        w['381']['inputs'].pop(name, None)
    # Retain seed, sampler, pose/face, resolution, frame source and original prompt
    # for the first controlled comparison. Product/camera adherence is NOT guaranteed.
    return w

def validate_graph(w):
    for node_id, node in w.items():
        for key, value in node['inputs'].items():
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                if value[0] not in w:
                    raise ValueError(f'Dangling link: {node_id}.{key} -> {value}')
    return len(w)

def plan(frame_count, chunk=121, overlap=5):
    if frame_count < 1 or chunk < 9 or chunk % 4 != 1 or overlap < 1 or overlap % 4 != 1 or overlap >= chunk:
        raise ValueError('Require positive frame count; chunk and overlap must be 4n+1, chunk > overlap')
    result, start = [], 0
    while start < frame_count:
        take = min(chunk, frame_count-start)
        pad = ((take-1+3)//4)*4+1
        drop = 0 if not result else overlap
        result.append({'index': len(result), 'source_start': start, 'source_stop_exclusive': start+take,
                       'source_frames': take, 'model_frames': pad, 'drop_head_overlap': drop,
                       'drop_tail_padding': pad-take, 'keep_frames': take-drop})
        if start+take >= frame_count:
            break
        start += chunk-overlap
    assert sum(x['keep_frames'] for x in result) == frame_count
    return result

def probe(path):
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_frames',
                        '-show_entries', 'stream=nb_read_frames,avg_frame_rate,r_frame_rate,width,height,duration:format=duration',
                        '-of', 'json', str(path)], check=True, capture_output=True, text=True)
    meta = json.loads(p.stdout)
    s = meta['streams'][0]
    n = int(s['nb_read_frames'])
    fps = Fraction(s['avg_frame_rate'])
    if not fps or n <= 0:
        raise ValueError('Cannot determine video frame count/FPS')
    meta['frame_count'] = n
    meta['fps_fraction'] = str(fps)
    meta['timeline_seconds'] = float(n/fps)
    meta['variable_frame_rate_suspected'] = s.get('r_frame_rate') != s.get('avg_frame_rate')
    return meta

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--video', type=Path)
    ap.add_argument('--person', type=Path)
    ap.add_argument('--scene', type=Path)
    ap.add_argument('--baseline-result', type=Path)
    ap.add_argument('--scene-result', type=Path)
    ap.add_argument('--out', type=Path, default=ROOT/'prepared')
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    w = json.loads((ROOT/'baseline/wan22_workflow.json').read_text())
    for label, is_scene in [('A_person_only', False), ('B_person_scene_experimental', True)]:
        graph=build(w,is_scene)
        validate_graph(graph)
        (a.out/(label+'.json')).write_text(json.dumps(graph,ensure_ascii=False,indent=2),encoding='utf-8')
    manifest={'version':VERSION,'stage':'prepared_offline','gpu_task_id':None,
              'paid_generation_submitted':False,'scene_candidate_gpu_validated':False,
              'long_video_status':'frame plan only; continuation runner not implemented or validated', 'assets':{}}
    for name in ['video','person','scene','baseline_result','scene_result']:
        p=getattr(a,name)
        if p:
            manifest['assets'][name]={'filename':p.name,'sha256':sha(p),'bytes':p.stat().st_size}
    if a.video:
        meta=probe(a.video)
        manifest['source_video']=meta
        manifest['chunk_plan']=plan(meta['frame_count'])
        for name in ['baseline_result','scene_result']:
            p=getattr(a,name)
            if p:
                out=probe(p)
                manifest[name]={'probe':out,'same_frame_count':out['frame_count']==meta['frame_count'],
                                'same_fps':out['fps_fraction']==meta['fps_fraction'],
                                'duration_difference':out['timeline_seconds']-meta['timeline_seconds']}
    (a.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'version':VERSION,'status':'prepared_offline','output':str(a.out),'gpu_submitted':False}))

if __name__=='__main__':
    main()
