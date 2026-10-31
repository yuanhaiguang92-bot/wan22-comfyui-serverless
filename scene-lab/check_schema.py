"""Offline candidate graph input-name check against exported target object_info."""
import argparse,json
from pathlib import Path
def normalize_legacy_inputs(graph, info):
    """Remove only the two obsolete device widgets confirmed by runtime schema.

    The caller passes its own graph copy. Never modify the baseline file, and
    never discard required/optional/hidden inputs declared by the installed node.
    """
    changes=[]
    for nid,node in graph.items():
        kind=node['class_type']
        if kind not in {'BlockifyMask','DrawMaskOnImage'} or kind not in info:
            continue
        spec=info[kind].get('input',{})
        declared=set().union(*(set(spec.get(group,{}) or {}) for group in ('required','optional','hidden')))
        if 'device' in node['inputs'] and 'device' not in declared:
            node['inputs'].pop('device')
            changes.append({'node_id':nid,'node_type':kind,'removed_input':'device'})
    return changes

def check(graph, info):
    errors=[]
    for nid,n in graph.items():
        kind=n['class_type']
        if kind not in info:
            errors.append(f'{nid}: missing node {kind}')
            continue
        spec=info[kind].get('input',{})
        required=spec.get('required',{}); optional=spec.get('optional',{})
        for key in required:
            if key not in n['inputs']: errors.append(f'{nid}.{key}: missing required input')
        for key in n['inputs']:
            if key not in required and key not in optional and key not in {'videopreview','format.codec'}:
                errors.append(f'{nid}.{key}: unknown input for {kind}')
    return errors
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('graph',type=Path);p.add_argument('object_info',type=Path)
    a=p.parse_args();errors=check(json.loads(a.graph.read_text()),json.loads(a.object_info.read_text()))
    print(json.dumps({'schema_passed':not errors,'errors':errors,'gpu_validated':False},ensure_ascii=False,indent=2))
    raise SystemExit(bool(errors))
