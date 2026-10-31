"""Isolated local job store and single-submit transport. No network at import."""
import hashlib,json,os,re,sqlite3,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
VERSION='0.1.2'
STABLE_ENDPOINTS={'u9qssevhtj66ej','hd3hzk3z9tp83k','lgncsmkv300llz','0yd7a20zjfwkyq','kfvxb9x78cvi8s','o1lw7b64dp3w4c'}
TERMINAL={'COMPLETED','FAILED','CANCELLED','TIMED_OUT'}
class Blocked(ValueError):pass
class SubmissionUnknown(RuntimeError):pass

def load_config(root):
    path=Path(root)/'lab-config.json'
    cfg=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return cfg

def readonly_credentials(config):
    """Read an explicitly configured successful tool settings file; NEVER write it."""
    out={}
    path=config.get('credentials_file','')
    if path:
        raw=json.loads(Path(os.path.expandvars(path)).expanduser().read_text(encoding='utf-8-sig'))
        out={k:raw.get(k,'') for k in ('runpod_api_key','tos_access_key','tos_secret_key','tos_bucket','tos_prefix')}
    for name in ('runpod_api_key','tos_access_key','tos_secret_key','tos_bucket','tos_prefix'):
        value=os.getenv('WAN22_LAB_'+name.upper())
        if value:out[name]=value
    return out

def require_paid(config):
    ep=str(config.get('test_endpoint_id','')).strip()
    if not ep or ep in STABLE_ENDPOINTS or not re.fullmatch('[a-zA-Z0-9_-]{8,64}',ep):
        raise Blocked('必须配置独立测试Endpoint；禁止使用现有稳定版端点')
    if config.get('paid_generation_enabled') is not True or os.getenv('WAN22_LAB_ALLOW_PAID')!='1':
        raise Blocked('付费生成未解锁；当前仅允许本地准备')
    if config.get('expected_worker_version')!=VERSION:
        raise Blocked('独立worker版本未确认')
    return ep

class Store:
    def __init__(self,root):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'jobs.sqlite3'
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    def db(self):return sqlite3.connect(self.path,timeout=30)
    def put_asset(self,meta):
        with self.db() as c:c.execute('INSERT INTO assets VALUES (?,?)',(meta['id'],json.dumps(meta)))
    def asset(self,aid):
        with self.db() as c:r=c.execute('SELECT payload FROM assets WHERE id=?',(aid,)).fetchone()
        if not r:raise ValueError('素材不存在')
        return json.loads(r[0])
    def create(self,payload):
        x={'id':'prep-'+uuid.uuid4().hex,'version':VERSION,'created_at':time.time(),'updated_at':time.time(),
           'stage':'prepared_local','provider_status':None,'gpu_task_id':None,'error':None,**payload}
        with self.db() as c:c.execute('INSERT INTO jobs VALUES (?,?)',(x['id'],json.dumps(x)))
        return x
    def get(self,jid):
        with self.db() as c:r=c.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
        if not r:raise ValueError('本地记录不存在')
        return json.loads(r[0])
    def update(self,jid,**patch):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
            if not r:raise ValueError('本地记录不存在')
            x=json.loads(r[0]);x.update(patch,updated_at=time.time())
            c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(x),jid))
        return x
    def claim_submission(self,jid):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT payload FROM jobs WHERE id=?',(jid,)).fetchone()
            if not r:raise ValueError('记录不存在')
            x=json.loads(r[0])
            if x['stage']!='prepared_local':raise Blocked('此记录已提交或状态待核实，禁止重复提交')
            def signature(item):
                hashes={}
                for role,aid in item.get('assets',{}).items():
                    r=c.execute('SELECT payload FROM assets WHERE id=?',(aid,)).fetchone()
                    hashes[role]=json.loads(r[0]).get('sha256',aid) if r else aid
                return (item.get('mode'),item.get('seed'),tuple(sorted(hashes.items())))
            sig=signature(x)
            others=[json.loads(r[0]) for r in c.execute('SELECT payload FROM jobs WHERE id != ?',(jid,)).fetchall()]
            for other in others:
                if other['stage'] not in {'prepared_local','upload_failed','saved_local','worker_failed','result_missing','download_failed'} and other.get('provider_status') not in TERMINAL and signature(other)==sig:
                    raise Blocked('相同素材和Seed已有任务或提交状态待核实；请恢复原记录，禁止重复扣费')
            x.update(stage='uploading_assets',submitted_at=time.time(),updated_at=time.time())
            c.execute('UPDATE jobs SET payload=? WHERE id=?',(json.dumps(x),jid))
        return x
    def all(self):
        with self.db() as c:return [json.loads(r[0]) for r in c.execute('SELECT payload FROM jobs ORDER BY rowid DESC')]

class Provider:
    def __init__(self,key):self.key=key
    def call(self,ep,path,data=None):
        url=f'https://api.runpod.ai/v2/{ep}/{path}'
        headers={'Authorization':'Bearer '+self.key}
        body=None
        if data is not None:headers['Content-Type']='application/json';body=json.dumps(data).encode()
        req=Request(url,data=body,headers=headers,method='POST' if body else 'GET')
        try:
            with urlopen(req,timeout=45) as r:return json.load(r)
        except HTTPError as e:
            # Do not surface full response bodies that might include signed URLs.
            raise RuntimeError(f'RunPod HTTP {e.code}；请保留记录排查') from e

class Service:
    def __init__(self,store,config,credentials,provider_factory=Provider,uploader=None):
        self.store=store;self.config=config;self.credentials=credentials;self.provider_factory=provider_factory;self.uploader=uploader
    def submit(self,jid,confirm):
        ep=require_paid(self.config) # Gate before upload or external request
        if confirm is not True:raise Blocked('缺少本次付费提交确认')
        key=self.credentials.get('runpod_api_key','')
        if not key:raise Blocked('缺少RunPod API Key')
        x=self.store.claim_submission(jid)
        try:
            if not self.uploader:raise RuntimeError('素材上传器不可用')
            uploaded={}
            for role,aid in x['assets'].items():
                self.store.update(jid,stage='uploading_'+role)
                asset=self.store.asset(aid)
                uploaded[role]=self.uploader(Path(asset['path']))
        except Exception:
            # No GPU POST occurred; do not automatically retry uploads or submission.
            self.store.update(jid,stage='upload_failed',error='素材上传未完成，未提交GPU任务')
            raise
        inp={'lab_version':VERSION,'mode':x['mode'],'image_url':uploaded['person'],'video_url':uploaded['video'],
             'seed':x['seed'],'client_request_id':jid}
        if x['mode']=='person_scene':inp['scene_url']=uploaded['scene']
        # Persist intent BEFORE the one and only external POST.
        self.store.update(jid,stage='submitting_once',endpoint_id=ep)
        try:
            reply=self.provider_factory(key).call(ep,'run',{'input':inp})
            task_id=reply.get('id')
            if not isinstance(task_id,str) or not re.fullmatch('[a-zA-Z0-9_-]{8,128}',task_id):
                raise ValueError('RunPod未返回可用任务ID')
        except Exception as e:
            self.store.update(jid,stage='submission_unknown',error='提交结果不确定；禁止重新点击，需在RunPod Requests按本地准备ID核对')
            raise SubmissionUnknown('提交结果待核实；本工具不会自动重发') from e
        return self.store.update(jid,stage='provider_accepted',gpu_task_id=task_id,provider_status=reply.get('status','IN_QUEUE'),error=None)
    def status(self,jid):
        x=self.store.get(jid)
        if not x.get('gpu_task_id') or x.get('provider_status') in TERMINAL:return x
        ep=x['endpoint_id']
        if ep in STABLE_ENDPOINTS:raise Blocked('不查询稳定版任务')
        try:
            r=self.provider_factory(self.credentials['runpod_api_key']).call(ep,'status/'+x['gpu_task_id'])
        except Exception:
            return self.store.update(jid,last_query_error='查询网络异常；任务ID已保留，未重新提交',last_query_at=time.time())
        state=r.get('status')
        if state not in {'IN_QUEUE','IN_PROGRESS',*TERMINAL}:
            return self.store.update(jid,last_query_error='未知provider状态；原任务信息已保留')
        patch={'provider_status':state,'stage':state.lower(),'last_query_error':None,'last_query_at':time.time(),
               'delay_ms':r.get('delayTime'),'execution_ms':r.get('executionTime')}
        if isinstance(r.get('output'),dict):
            patch['worker_output']=r['output']
            if state=='COMPLETED' and r['output'].get('status')=='failed':
                patch.update(stage='worker_failed',error=r['output'].get('error','worker失败'))
        if r.get('error'):patch['error']=str(r['error'])[:1000]
        return self.store.update(jid,**patch)

def tos_uploader(credentials):
    """Construct locally only; actual upload occurs only after Service.submit gate."""
    def upload(path):
        import tos
        from tos.enum import HttpMethodType
        required=['tos_access_key','tos_secret_key','tos_bucket']
        if not all(credentials.get(k) for k in required):raise ValueError('TOS配置不完整')
        cli=tos.TosClientV2(credentials['tos_access_key'],credentials['tos_secret_key'],'tos-cn-beijing.volces.com','cn-beijing')
        key='wan22-scene-lab/'+uuid.uuid4().hex+path.suffix
        cli.put_object_from_file(credentials['tos_bucket'],key,str(path))
        return cli.pre_signed_url(HttpMethodType.Http_Method_Get,credentials['tos_bucket'],key,expires=7200).signed_url
    return upload

def public_job(x):
    x=dict(x);x.pop('endpoint_id',None)
    out=dict(x.get('worker_output') or {})
    for k in ('video_url','reference_url','object_key'):out.pop(k,None)
    x['worker_output']=out
    x['elapsed_seconds']=time.time()-x.get('submitted_at',x['created_at'])
    x['result_available']=bool(x.get('result_path'))
    return x
