import functools,http.server,io,json,subprocess,tempfile,threading,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from PIL import Image
from lab_core import Store
from server import make_handler,TOKEN
class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.store=Store(Path(cls.tmp.name)/'data')
        cls.http=http.server.ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.store,{},{}))
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.http.server_port}'
        cls.video=Path(cls.tmp.name)/'test.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=gray:s=64x64:r=30','-frames:v','30','-c:v','libx264','-pix_fmt','yuv420p',str(cls.video)],check=True)
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.tmp.cleanup()
    def call(self,path,data=None,token=TOKEN,raw=False):
        body=None if data is None else data if isinstance(data,bytes) else json.dumps(data).encode()
        req=Request(self.base+path,data=body,headers={'X-Lab-Token':token},method='POST' if data is not None else 'GET')
        with urlopen(req,timeout=20) as r:return r.read() if raw else json.load(r)
    def test_page_and_gate_default(self):
        body=self.call('/',raw=True);self.assertIn(b'V0.1.2',body)
        self.assertFalse(self.call('/api/info')['paid_enabled'])
    def test_upload_prepare_history_and_range(self):
        v=self.call('/api/asset?role=video&name=test.mp4',self.video.read_bytes())
        b=io.BytesIO();Image.new('RGB',(32,32),'white').save(b,format='PNG')
        person=self.call('/api/asset?role=person&name=person.png',b.getvalue())
        scene=self.call('/api/asset?role=scene&name=scene.png',b.getvalue())
        x=self.call('/api/prepare',{'mode':'person_scene','assets':{'video':v['id'],'person':person['id'],'scene':scene['id']},'seed':123})
        self.assertEqual(x['source_probe']['frame_count'],30);self.assertEqual(x['stage'],'prepared_local')
        self.assertIn(x['id'],[r['id'] for r in self.call('/api/history')])
        with self.assertRaises(HTTPError) as ctx:self.call('/api/submit',{'id':x['id'],'confirm_paid':True})
        self.assertEqual(ctx.exception.code,400)
        self.assertEqual(self.store.get(x['id'])['stage'],'prepared_local')
        req=Request(self.base+'/api/media?id='+v['id'],headers={'Range':'bytes=0-31'})
        with urlopen(req) as response:
            self.assertEqual(response.status,206);self.assertEqual(len(response.read()),32)
        restored=Store(Path(self.tmp.name)/'data').get(x['id'])
        self.assertEqual(restored['assets'],x['assets'])
    def test_csrf_rejected(self):
        with self.assertRaises(HTTPError) as ctx:self.call('/api/prepare',{},token='wrong')
        self.assertEqual(ctx.exception.code,403)
