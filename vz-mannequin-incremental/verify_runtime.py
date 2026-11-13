"""Fail a candidate build if its Python distribution versions drift from baseline."""
import importlib.metadata as metadata
import json,re,sys
normalize=lambda s:re.sub(r'[-_.]+','-',s).lower()
expected={normalize(k):v for k,v in json.load(open(sys.argv[1])).items()}
actual={normalize(d.metadata['Name']):d.version for d in metadata.distributions()}
differences={k:{'expected':v,'actual':actual.get(k)} for k,v in expected.items() if actual.get(k)!=v}
extra={k:v for k,v in actual.items() if k not in expected}
print(json.dumps({'expected_count':len(expected),'actual_count':len(actual),'differences':differences,'extra':extra},sort_keys=True))
if differences or extra:
    raise SystemExit('Original runtime distributions differ; do not release this candidate')
