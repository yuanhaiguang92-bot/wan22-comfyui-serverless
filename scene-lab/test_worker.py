"""Worker logic via explicit stubs, never actual ComfyUI/GPU validation."""
import copy,importlib.util,json,os,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import prepare,check_schema
ROOT=Path(__file__).parent
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=json.loads((ROOT/'baseline/wan22_workflow.json').read_text())
        self.downloads=[];self.graph=None
        self.stable=types.SimpleNamespace(COMFY_INPUT=Path(self.tmp.name),MAX_VIDEO_BYTES=500,MAX_IMAGE_BYTES=25,
            EXECUTION_TIMEOUT=10,official_handler=types.SimpleNamespace(COMFY_HOST='mock-host'),
            _download=lambda u,p,n:self.downloads.append((u,p,n)),_validate_image=lambda p:None,
            _prepare_workflow=lambda *args:copy.deepcopy(self.w),
            _find_final_video=lambda *args:Path(self.tmp.name)/'result.mp4',
            _mux_audio=lambda final,source:final,_upload_video=lambda *args:('https://example.com/mock-result.mp4','mock-key'),
            _cleanup_task_outputs=lambda *args,**kw:None)
        self.requests=types.SimpleNamespace(get=lambda *a,**kw:types.SimpleNamespace(raise_for_status=lambda:None,json=self.schema))
        stubs={'baseline_handler':self.stable,'lab_prepare':prepare,'lab_schema':check_schema,
            'requests':self.requests,'runpod':types.SimpleNamespace(serverless=types.SimpleNamespace(progress_update=lambda *a:None)),
            'websocket':types.SimpleNamespace()}
        self.patch=patch.dict(sys.modules,stubs);self.patch.start()
        spec=importlib.util.spec_from_file_location('lab_handler_under_test',ROOT/'worker/lab_handler.py')
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.module.progress=lambda *args,**kwargs:None
        def run(job,w):self.graph=w;return 'mock-comfy-prompt',{}
        self.module.run_graph=run
        self.module.probe=lambda p:{'frame_count':300,'fps_fraction':'30','timeline_seconds':10.0,'variable_frame_rate_suspected':False}
        self.env=patch.dict(os.environ,{'WAN22_LAB_GPU_ENABLED':'1'});self.env.start()
    def tearDown(self):self.env.stop();self.patch.stop();self.tmp.cleanup()
    def schema(self):
        b=prepare.build(self.w,True)
        info={}
        for n in [*self.w.values(),*b.values()]:
            info.setdefault(n['class_type'],{'input':{'optional':{}}})['input']['optional'].update({k:[] for k in n['inputs']})
        return info
    def job(self,mode='person_scene'):
        return {'id':'mock-job-only','input':{'mode':mode,'lab_version':'0.1.2','image_url':'https://example.com/person.png',
            'video_url':'https://example.com/video.mp4','scene_url':'https://example.com/scene.png','seed':123}}
    def test_worker_gate_no_download(self):
        with patch.dict(os.environ,{'WAN22_LAB_GPU_ENABLED':'0'}):
            result=self.module.handler(self.job())
        self.assertEqual(result['status'],'failed');self.assertFalse(self.downloads)
    def test_runtime_obsolete_device_widgets_are_removed_before_queue(self):
        info=self.schema()
        for kind in ('BlockifyMask','DrawMaskOnImage'):
            info[kind]['input']['optional'].pop('device')
        self.requests.get=lambda *a,**kw:types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:info)
        result=self.module.handler(self.job('person_scene_combined'))
        self.assertEqual(result['status'],'completed')
        self.assertNotIn('device',self.graph['368']['inputs'])
        self.assertNotIn('device',self.graph['369']['inputs'])
        self.assertEqual(self.w['368']['inputs']['device'],'cpu')
    def test_declared_device_and_other_unknown_inputs_are_not_discarded(self):
        graph=copy.deepcopy(self.w);info=self.schema()
        self.assertEqual(check_schema.normalize_legacy_inputs(graph,info),[])
        graph['368']['inputs']['unrecognized']=True
        check_schema.normalize_legacy_inputs(graph,info)
        self.assertTrue(any('unrecognized' in e for e in check_schema.check(graph,info)))
    def test_candidate_wiring_and_exact_frame_window(self):
        result=self.module.handler(self.job())
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(self.downloads),3)
        self.assertEqual(self.graph['381']['inputs']['length'],301)
        self.assertEqual(self.graph['384']['inputs']['length'],300)
        self.assertNotIn('background_video',self.graph['381']['inputs'])
        self.assertIn('background_video',self.w['381']['inputs'])
        self.assertFalse(result['quality_accepted'])
    def test_control_keeps_original_background(self):
        result=self.module.handler(self.job('person_only'))
        self.assertEqual(result['status'],'completed');self.assertEqual(len(self.downloads),2)
        self.assertIn('background_video',self.graph['381']['inputs'])
        self.assertEqual(self.graph['381']['inputs']['length'],301)
    def test_long_clip_refused_before_queue(self):
        self.module.probe=lambda p:{'frame_count':600,'fps_fraction':'30','timeline_seconds':20.0,'variable_frame_rate_suspected':False}
        result=self.module.handler(self.job())
        self.assertEqual(result['status'],'failed');self.assertIsNone(self.graph)

    def test_combined_reference_uses_two_inputs_no_duplicate_person(self):
        result=self.module.handler(self.job('person_scene_combined'))
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(self.downloads),2)
        self.assertNotIn('900',self.graph)
        self.assertNotIn('904',self.graph)
        self.assertEqual(self.graph['351']['inputs']['image'],['371',0])
        self.assertEqual(self.graph['381']['inputs']['reference_image'],['371',0])
        self.assertNotIn('background_video',self.graph['381']['inputs'])
