import copy, ipaddress, json, os, shutil, socket, subprocess, time, uuid
from pathlib import Path
from urllib.parse import urlparse
import requests, runpod, websocket
from PIL import Image
from runpod.serverless.utils import rp_upload
import official_handler

COMFY_INPUT=Path('/comfyui/input'); COMFY_OUTPUT=Path('/comfyui/output')
WORKFLOW_FILE=Path('/opt/wan22/wan22_workflow.json')
MAX_IMAGE_BYTES=int(os.getenv('WAN22_MAX_IMAGE_MB','25'))*1024*1024
MAX_VIDEO_BYTES=int(os.getenv('WAN22_MAX_VIDEO_MB','500'))*1024*1024
DOWNLOAD_TIMEOUT=int(os.getenv('WAN22_DOWNLOAD_TIMEOUT','300'))
EXECUTION_TIMEOUT=int(os.getenv('WAN22_EXECUTION_TIMEOUT','1800'))
OUTPUT_BUCKET=os.getenv('WAN22_OUTPUT_BUCKET','').strip()
ALLOW_HTTP=os.getenv('WAN22_ALLOW_HTTP','false').lower()=='true'
VIDEO_EXTENSIONS={'.mp4','.webm','.mkv','.mov'}

def _safe_url(url):
    if not isinstance(url,str) or not url.strip(): raise ValueError('image_url/video_url must be a non-empty URL')
    p=urlparse(url.strip()); allowed={'https'}|({'http'} if ALLOW_HTTP else set())
    if p.scheme.lower() not in allowed: raise ValueError('Only HTTPS input URLs are allowed')
    if not p.hostname: raise ValueError('Input URL has no hostname')
    try: infos=socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)
    except socket.gaierror as e: raise ValueError(f'Cannot resolve input host: {p.hostname}') from e
    for info in infos:
        ip=ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            raise ValueError('Private/local input URLs are not allowed')
    return url.strip()

def _download(url,dst,max_bytes):
    url=_safe_url(url); dst.parent.mkdir(parents=True,exist_ok=True); total=0
    with requests.get(url,stream=True,timeout=(20,DOWNLOAD_TIMEOUT),allow_redirects=True,headers={'User-Agent':'WAN22-RunPod-Adapter/1.0'}) as r:
        r.raise_for_status(); length=r.headers.get('Content-Length')
        if length and int(length)>max_bytes: raise ValueError(f'Input file exceeds limit: {max_bytes//(1024*1024)} MB')
        with dst.open('wb') as f:
            for chunk in r.iter_content(1024*1024):
                if not chunk: continue
                total+=len(chunk)
                if total>max_bytes: raise ValueError(f'Input file exceeds limit: {max_bytes//(1024*1024)} MB')
                f.write(chunk)
    if total==0: raise ValueError('Downloaded input file is empty')
    return total

def _validate_image(path):
    try:
        with Image.open(path) as im: im.verify()
    except Exception as e: raise ValueError('image_url did not produce a valid image') from e

def _validate_video(path):
    cmd=['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=codec_name,width,height,duration','-show_entries','format=duration','-of','json',str(path)]
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=60,check=True); data=json.loads(p.stdout or '{}')
    except Exception as e: raise ValueError('video_url did not produce a readable video') from e
    if not (data.get('streams') or []): raise ValueError('video_url contains no video stream')
    return data

def _load_workflow():
    return json.loads(WORKFLOW_FILE.read_text(encoding='utf-8'))

def _prepare_workflow(image_name,video_name,token,seed=None):
    wf=copy.deepcopy(_load_workflow()); wf['10']['inputs']['image']=image_name; wf['301']['inputs']['video']=video_name
    preview=wf['301']['inputs'].get('videopreview')
    if isinstance(preview,dict) and isinstance(preview.get('params'),dict):
        preview['params']['filename']=video_name; preview['params']['type']='input'
    for node_id,label in {'19':'final','353':'pose','354':'mask','359':'detect'}.items():
        if node_id in wf and wf[node_id].get('class_type')=='SaveVideo': wf[node_id]['inputs']['filename_prefix']=f'wan22/{token}/{label}'
    if seed is not None:
        seed=int(seed)
        if seed<0: seed=int.from_bytes(os.urandom(8),'big')&((1<<63)-1)
        wf['379']['inputs']['value']=seed
    return wf

def _wait(prompt_id,client_id):
    ws=websocket.WebSocket(); ws.settimeout(30); started=time.monotonic()
    try:
        ws.connect(f'ws://{official_handler.COMFY_HOST}/ws?clientId={client_id}',timeout=10)
        while True:
            if time.monotonic()-started>EXECUTION_TIMEOUT: raise TimeoutError(f'WAN22 execution exceeded {EXECUTION_TIMEOUT} seconds')
            try: raw=ws.recv()
            except websocket.WebSocketTimeoutException: continue
            if not isinstance(raw,str): continue
            msg=json.loads(raw); data=msg.get('data') or {}
            if msg.get('type')=='execution_error' and data.get('prompt_id')==prompt_id:
                raise RuntimeError(f"ComfyUI node {data.get('node_id')} ({data.get('node_type')}): {data.get('exception_message')}")
            if msg.get('type')=='executing' and data.get('prompt_id')==prompt_id and data.get('node') is None: return
    finally:
        try: ws.close()
        except Exception: pass

def _find_final_video(token):
    d=COMFY_OUTPUT/'wan22'/token; deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        c=[p for p in d.glob('final*') if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and p.stat().st_size>0]
        if c: return max(c,key=lambda p:p.stat().st_size)
        time.sleep(.5)
    raise FileNotFoundError(f'Node 19 final video was not found under {d}')

def _upload_video(job_id,path):
    if not (os.getenv('BUCKET_ENDPOINT_URL') and os.getenv('BUCKET_ACCESS_KEY_ID') and os.getenv('BUCKET_SECRET_ACCESS_KEY') and OUTPUT_BUCKET):
        raise RuntimeError('S3 output is not configured. Set BUCKET_ENDPOINT_URL, BUCKET_ACCESS_KEY_ID, BUCKET_SECRET_ACCESS_KEY and WAN22_OUTPUT_BUCKET.')
    return rp_upload.upload_file_to_bucket(file_name=path.name,file_location=str(path),bucket_name=OUTPUT_BUCKET,prefix=f'wan22/{job_id}',extra_args={'ContentType':'video/mp4'})

def handler(job):
    inp=job.get('input') or {}; job_id=str(job.get('id') or uuid.uuid4()); image_url=inp.get('image_url'); video_url=inp.get('video_url'); seed=inp.get('seed')
    if not image_url or not video_url: return {'error':'Both input.image_url and input.video_url are required'}
    if not official_handler.check_server(f'http://{official_handler.COMFY_HOST}/',official_handler.COMFY_API_AVAILABLE_MAX_RETRIES,official_handler.COMFY_API_AVAILABLE_INTERVAL_MS): return {'error':'ComfyUI server is not reachable'}
    token=uuid.uuid4().hex; image_path=COMFY_INPUT/f'wan22_{token}.png'; video_path=COMFY_INPUT/f'wan22_{token}.mp4'; output_dir=COMFY_OUTPUT/'wan22'/token
    try:
        ib=_download(image_url,image_path,MAX_IMAGE_BYTES); _validate_image(image_path)
        vb=_download(video_url,video_path,MAX_VIDEO_BYTES); meta=_validate_video(video_path)
        workflow=_prepare_workflow(image_path.name,video_path.name,token,seed)
        client_id=str(uuid.uuid4()); queued=official_handler.queue_workflow(workflow,client_id); prompt_id=queued.get('prompt_id')
        if not prompt_id: raise RuntimeError(f'ComfyUI returned no prompt_id: {queued}')
        _wait(prompt_id,client_id)
        history=official_handler.get_history(prompt_id); ph=history.get(prompt_id,{})
        if (ph.get('status') or {}).get('status_str')=='error': raise RuntimeError(f"ComfyUI execution failed: {ph.get('status')}")
        final_video=_find_final_video(token); size=final_video.stat().st_size; url=_upload_video(job_id,final_video)
        return {'status':'completed','job_id':job_id,'prompt_id':prompt_id,'video_url':url,'size_bytes':size,'input_image_bytes':ib,'input_video_bytes':vb,'video_probe':meta}
    except Exception as e: return {'error':str(e),'job_id':job_id}
    finally:
        for p in (image_path,video_path):
            try: p.unlink(missing_ok=True)
            except Exception: pass
        if output_dir.exists(): shutil.rmtree(output_dir,ignore_errors=True)

if __name__=='__main__':
    print('WAN22 adapter - starting RunPod handler')
    runpod.serverless.start({'handler':handler})
