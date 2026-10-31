import copy,hashlib,json,unittest
from pathlib import Path
from prepare import build,plan,validate_graph
from check_schema import check
ROOT=Path(__file__).parent
class OfflineChecks(unittest.TestCase):
    def setUp(self):
        self.w=json.loads((ROOT/'baseline/wan22_workflow.json').read_text())
    def test_backup_matches_github(self):
        evidence=json.loads((ROOT/'evidence/repository_files.json').read_text())
        for name,meta in evidence.items():
            b=(ROOT/'baseline'/name).read_bytes()
            self.assertEqual(hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),meta['blob_sha'])
    def test_control_is_identical_and_copy(self):
        a=build(self.w);self.assertEqual(a,self.w)
        a['381']['inputs'].clear();self.assertTrue(self.w['381']['inputs'])
    def test_only_intended_conditioning_changes(self):
        before=copy.deepcopy(self.w);b=build(self.w,True);self.assertEqual(self.w,before)
        for nid in self.w:
            if nid not in {'351','381'}:self.assertEqual(b[nid],self.w[nid],nid)
        for name in ['pose_video','face_video','length','video_frame_offset']:
            self.assertEqual(b['381']['inputs'][name],self.w['381']['inputs'][name])
        for name in ['background_video','character_mask']:self.assertNotIn(name,b['381']['inputs'])
        self.assertEqual(b['903']['inputs']['image'],['371',0])
        self.assertEqual(b['904']['inputs']['mask'],['903',0])
        self.assertEqual(b['381']['inputs']['reference_image'],['904',0])
        validate_graph(b)
    def test_no_dangling_links(self):
        for scene in [False,True]:validate_graph(build(self.w,scene))
        broken=build(self.w);broken['19']['inputs']['video']=['missing',0]
        with self.assertRaises(ValueError):validate_graph(broken)
    def test_long_plan_exact_coverage(self):
        for n in [1,2,5,120,121,122,237,238,239,300,4096,10000]:
            chunks=plan(n);indices=[]
            for c in chunks:
                indices.extend(range(c['source_start']+c['drop_head_overlap'],c['source_stop_exclusive']))
                self.assertEqual(c['model_frames']%4,1);self.assertGreater(c['keep_frames'],0)
            self.assertEqual(indices,list(range(n)))
    def test_schema_rejects_incompatible_runtime(self):
        graph={'1':{'class_type':'WanAnimateToVideo','inputs':{'background_video':['2',0]}}}
        self.assertTrue(check(graph,{}))
        self.assertTrue(check(graph,{'WanAnimateToVideo':{'input':{'required':{'positive':[]}}}}))
    def test_wrong_implementation_rejected(self):
        self.w['381']['class_type']='WanVideoAnimateEmbeds'
        with self.assertRaises(ValueError):build(self.w,True)
if __name__=='__main__':unittest.main()
