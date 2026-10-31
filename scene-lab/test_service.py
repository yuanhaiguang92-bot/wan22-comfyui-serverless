import json,os,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from lab_core import Store,Service,Blocked,SubmissionUnknown,VERSION,public_job
class FakeProvider:
    calls=[]
    response={'id':'test-job-12345678','status':'IN_QUEUE'}
    error=None
    def __init__(self,key):pass
    def call(self,ep,path,data=None):
        self.calls.append((ep,path,data))
        if self.error:raise self.error
        return self.response
class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.store.put_asset({'id':'v','path':'video.mp4','sha256':'video'})
        self.store.put_asset({'id':'p','path':'person.png','sha256':'person'})
        self.store.put_asset({'id':'s','path':'scene.png','sha256':'scene'})
        self.job=self.store.create({'mode':'person_scene','assets':{'video':'v','person':'p','scene':'s'},'seed':123})
        self.config={'test_endpoint_id':'isolated-test-only','paid_generation_enabled':True,'expected_worker_version':VERSION}
        FakeProvider.calls=[];FakeProvider.error=None
        FakeProvider.response={'id':'test-job-12345678','status':'IN_QUEUE'}
        self.uploads=[]
        self.service=Service(self.store,self.config,{'runpod_api_key':'test-only'},FakeProvider,self.upload)
        self.env=patch.dict(os.environ,{'WAN22_LAB_ALLOW_PAID':'1'});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def upload(self,p):self.uploads.append(p);return 'https://example.com/'+p.name
    def test_default_gate_before_any_upload(self):
        self.config['paid_generation_enabled']=False
        with self.assertRaises(Blocked):self.service.submit(self.job['id'],True)
        self.assertEqual(self.uploads,[]);self.assertEqual(FakeProvider.calls,[])
        self.assertEqual(self.store.get(self.job['id'])['stage'],'prepared_local')
    def test_stable_endpoint_always_blocked(self):
        for ep in ['u9qssevhtj66ej','kfvxb9x78cvi8s']:
            self.config['test_endpoint_id']=ep
            with self.assertRaises(Blocked):self.service.submit(self.job['id'],True)
        self.assertFalse(FakeProvider.calls);self.assertFalse(self.uploads)
    def test_per_job_confirm_required(self):
        with self.assertRaises(Blocked):self.service.submit(self.job['id'],False)
        self.assertFalse(FakeProvider.calls)
    def test_three_asset_payload_and_duplicate_guard(self):
        x=self.service.submit(self.job['id'],True)
        self.assertEqual(len(self.uploads),3)
        payload=FakeProvider.calls[0][2]['input']
        self.assertEqual(payload['scene_url'],'https://example.com/scene.png')
        self.assertEqual(payload['client_request_id'],self.job['id'])
        self.assertEqual(x['gpu_task_id'],'test-job-12345678')
        with self.assertRaises(Blocked):self.service.submit(self.job['id'],True)
        self.assertEqual(len(FakeProvider.calls),1)
    def test_uncertain_post_never_retries(self):
        FakeProvider.error=TimeoutError()
        with self.assertRaises(SubmissionUnknown):self.service.submit(self.job['id'],True)
        with self.assertRaises(Blocked):self.service.submit(self.job['id'],True)
        self.assertEqual(len(FakeProvider.calls),1)
        self.assertEqual(Store(self.tmp.name).get(self.job['id'])['stage'],'submission_unknown')
    def test_query_failure_preserves_id(self):
        x=self.service.submit(self.job['id'],True);FakeProvider.error=TimeoutError()
        r=self.service.status(x['id'])
        self.assertEqual(r['gpu_task_id'],x['gpu_task_id'])
        self.assertTrue(r['last_query_error'])
        self.assertEqual(sum(c[1]=='run' for c in FakeProvider.calls),1)
    def test_worker_failure_not_success(self):
        x=self.service.submit(self.job['id'],True)
        FakeProvider.response={'status':'COMPLETED','output':{'status':'failed','error':'schema mismatch'}}
        x=self.service.status(x['id'])
        self.assertEqual(x['stage'],'worker_failed');self.assertEqual(x['error'],'schema mismatch')
    def test_public_status_hides_signed_urls(self):
        x=self.store.update(self.job['id'],worker_output={'video_url':'https://example.com/?secret=test','object_key':'test','stage':'ok'})
        self.assertNotIn('video_url',public_job(x)['worker_output'])

    def test_duplicate_new_record_is_blocked_after_unknown(self):
        FakeProvider.error=TimeoutError()
        with self.assertRaises(SubmissionUnknown):self.service.submit(self.job['id'],True)
        duplicate=self.store.create({'mode':'person_scene','assets':{'video':'v','person':'p','scene':'s'},'seed':123})
        with self.assertRaises(Blocked):self.service.submit(duplicate['id'],True)
        self.assertEqual(len(FakeProvider.calls),1)
