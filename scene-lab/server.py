"""WAN22 Scene Lab 0.1.2 — loopback only, isolated disk store, paid gate OFF."""
import argparse,hashlib,http.server,json,os,secrets,subprocess,threading,time,uuid
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from PIL import Image
from lab_core import VERSION,Store,Service,load_config,readonly_credentials,tos_uploader,public_job,require_paid
from prepare import probe,plan
ROOT=Path(__file__).resolve().parent
TOKEN=secrets.token_urlsafe(32)
LOCK=threading.Lock()

def safe_result_download(url,path):
    from urllib.request import urlopen,Request
    import ipaddress,socket
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname:raise ValueError('仅接受HTTPS结果链接')
    for item in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(item[4][0]).is_global:raise ValueError('拒绝私网结果地址')
    part=path.with_suffix('.part')
    try:
        with urlopen(Request(url),timeout=180) as r,part.open('wb') as out:
            final=urlsplit(r.geturl())
            if final.scheme!='https' or final.hostname!=u.hostname:raise ValueError('结果链接发生跨域跳转，停止下载')
            total=0
            while True:
                b=r.read(1024*1024)
                if not b:break
                total+=len(b)
                if total>1024**3:raise ValueError('结果超过1GB限制')
                out.write(b)
        meta=probe(part)
        part.replace(path)
        return meta
    finally:
        part.unlink(missing_ok=True)

def retrieve_result(store,job):
    out=job.get('worker_output') or {}
    if job.get('provider_status')!='COMPLETED' or job.get('result_path'):return job
    if out.get('status')=='failed':return job
    if not out.get('video_url'):return store.update(job['id'],stage='result_missing',error='任务完成但没有返回成品链接')
    path=store.root/(job['id']+'.mp4')
    try:
        meta=safe_result_download(out['video_url'],path)
        src=job['source_probe']
        quality={'same_frame_count':meta['frame_count']==src['frame_count'],'same_fps':meta['fps_fraction']==src['fps_fraction'],
                 'duration_delta':meta['timeline_seconds']-src['timeline_seconds']}
        return store.update(job['id'],stage='saved_local',result_path=str(path),result_probe=meta,timeline_check=quality,error=None)
    except Exception:
        return store.update(job['id'],stage='download_failed',error='成品下载或媒体核验失败；保留任务ID，可重试下载，不会重新生成')

def make_handler(store,config,credentials,service=None):
    service=service or Service(store,config,credentials,uploader=tos_uploader(credentials))
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):pass
        def reply(self,value,status=200):
            data=json.dumps(value,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def trusted(self):
            host=self.headers.get('Host','');origin=self.headers.get('Origin')
            return host in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'} and (
                not origin or origin in {'http://'+host})
        def body(self,limit=1024*1024):
            n=int(self.headers.get('Content-Length','0'))
            if n<1 or n>limit:raise ValueError('请求长度无效或超过限制')
            return self.rfile.read(n)
        def do_GET(self):
            if not self.trusted():return self.reply({'error':'本地请求来源无效'},403)
            u=urlsplit(self.path);q=parse_qs(u.query)
            try:
                if u.path=='/api/info':
                    try:require_paid(config);enabled=True
                    except Exception:enabled=False
                    return self.reply({'version':VERSION,'csrf_token':TOKEN,'paid_enabled':enabled,'configured_test_endpoint':config.get('test_endpoint_id',''),'long_video':'not_implemented','credentials_file_readonly':bool(config.get('credentials_file'))})
                if u.path=='/api/history':return self.reply([public_job(x) for x in store.all()])
                if u.path=='/api/status':
                    with LOCK:
                        x=service.status(q['id'][0])
                        x=retrieve_result(store,x)
                    return self.reply(public_job(x))
                if u.path in {'/api/media','/api/result'}:
                    x=store.asset(q['id'][0]) if u.path=='/api/media' else store.get(q['id'][0])
                    path=Path(x['path'] if u.path=='/api/media' else x['result_path'])
                    mime=x.get('mime','video/mp4')
                    return self.serve_file(path,mime)
                if u.path in {'/','/lab.html'}:return self.serve_file(ROOT/'workbench.html','text/html; charset=utf-8')
                return self.reply({'error':'未找到'},404)
            except Exception as e:return self.reply({'error':str(e)[:500]},400)
        def serve_file(self,path,mime):
            size=path.stat().st_size;start=0;end=size-1;partial=False
            value=self.headers.get('Range')
            if value:
                import re
                m=re.fullmatch(r'bytes=(\d+)-(\d*)',value)
                if not m:return self.reply({'error':'不支持此Range'},416)
                start=int(m[1]);end=min(end,int(m[2])) if m[2] else end
                if start>end:return self.reply({'error':'Range超出文件'},416)
                partial=True
            self.send_response(206 if partial else 200);self.send_header('Content-Type',mime)
            self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
            if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            with path.open('rb') as f:
                f.seek(start);remaining=end-start+1
                while remaining:
                    b=f.read(min(1024*1024,remaining))
                    if not b:break
                    self.wfile.write(b);remaining-=len(b)
        def do_POST(self):
            if not self.trusted() or self.headers.get('X-Lab-Token')!=TOKEN:return self.reply({'error':'本地令牌无效'},403)
            u=urlsplit(self.path);q=parse_qs(u.query)
            try:
                if u.path=='/api/asset':
                    role=q.get('role',[''])[0]
                    if role not in {'video','person','scene'}:raise ValueError('素材角色无效')
                    limit=500*1024*1024 if role=='video' else 25*1024*1024
                    n=int(self.headers.get('Content-Length','0'))
                    if n<1 or n>limit:raise ValueError('素材过大或为空')
                    aid=uuid.uuid4().hex;suffix='.mp4' if role=='video' else '.png'
                    path=store.root/(aid+suffix);h=hashlib.sha256()
                    try:
                        with path.open('xb') as f:
                            remaining=n
                            while remaining:
                                b=self.rfile.read(min(1024*1024,remaining))
                                if not b:raise ValueError('素材传输中断')
                                h.update(b);f.write(b);remaining-=len(b)
                        if role=='video':
                            meta=probe(path)
                        else:
                            with Image.open(path) as im:
                                width,height=im.size
                                if width*height>40_000_000:raise ValueError('图片像素过大')
                                im.verify()
                            meta={'width':width,'height':height}
                        value={'id':aid,'path':str(path),'role':role,'bytes':n,'sha256':h.hexdigest(),'meta':meta,
                               'original_name':q.get('name',['素材'])[0][:200],'mime':'video/mp4' if role=='video' else 'image/png'}
                        store.put_asset(value)
                    except Exception:path.unlink(missing_ok=True);raise
                    return self.reply({k:v for k,v in value.items() if k!='path'})
                data=json.loads(self.body())
                if u.path=='/api/prepare':
                    mode=data.get('mode')
                    if mode not in {'person_only','person_scene','person_scene_combined'}:raise ValueError('模式无效')
                    assets=data.get('assets',{});required=['video','person']+(['scene'] if mode=='person_scene' else [])
                    validated={}
                    for role in required:
                        asset=store.asset(assets.get(role,''))
                        if asset['role']!=role:raise ValueError('素材角色不匹配')
                        validated[role]=asset['id']
                    source=store.asset(validated['video'])['meta']
                    if source['variable_frame_rate_suspected']:raise ValueError('当前短片测试拒绝疑似VFR素材；需先核验原时间轴')
                    seed=int(data.get('seed',250416347570032))
                    if not 0<=seed<2**63:raise ValueError('Seed超出范围')
                    x=store.create({'mode':mode,'assets':validated,'seed':seed,'source_probe':source,
                                    'frame_plan':plan(source['frame_count']),
                                    'asset_hashes':{r:store.asset(a)['sha256'] for r,a in validated.items()}})
                    return self.reply(public_job(x))
                if u.path=='/api/submit':
                    with LOCK:
                        return self.reply(public_job(service.submit(data['id'],data.get('confirm_paid'))))
                return self.reply({'error':'未找到'},404)
            except Exception as e:return self.reply({'error':str(e)[:500]},400)
    return Handler

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8172);a=p.parse_args()
    config=load_config(ROOT);creds=readonly_credentials(config);store=Store(ROOT/'lab-data')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',a.port),make_handler(store,config,creds))
    print(f'WAN22 Scene Lab V{VERSION} http://127.0.0.1:{a.port}/ — paid gate defaults OFF',flush=True)
    server.serve_forever()
if __name__=='__main__':main()
