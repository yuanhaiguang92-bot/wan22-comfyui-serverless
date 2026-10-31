"""Isolated WAN22 lab worker. Never deployed/submitted by offline checks."""
import json,os,sys,time,uuid
from pathlib import Path
sys.path.insert(0,'/opt/wan22')
import requests,runpod,websocket
import baseline_handler as stable
from lab_prepare import build,probe,validate_graph
from lab_schema import check
VERSION='0.1.2'

def progress(job,stage,**extra):
    payload={'version':VERSION,'stage':stage,'job_id':job.get('id'),**extra}
    print('[WAN22-LAB] '+json.dumps(payload,ensure_ascii=False),flush=True)
    try:runpod.serverless.progress_update(job,payload)
    except Exception:pass  # progress transport failure must not submit again

def run_graph(job,graph):
    """Open WS before POST; on silent WS poll existing prompt history; never resubmit."""
    host=stable.official_handler.COMFY_HOST
    cid=uuid.uuid4().hex;ws=websocket.WebSocket();ws.settimeout(15)
    ws.connect(f'ws://{host}/ws?clientId={cid}',timeout=15)
    started=time.monotonic()
    try:
        reply=requests.post(f'http://{host}/prompt',json={'prompt':graph,'client_id':cid},timeout=60)
        reply.raise_for_status();data=reply.json();pid=data.get('prompt_id')
        if not pid:raise RuntimeError('ComfyUI没有返回prompt_id；不自动重发')
        progress(job,'comfy_accepted',prompt_id=pid)
        while time.monotonic()-started<stable.EXECUTION_TIMEOUT:
            try:raw=ws.recv()
            except websocket.WebSocketTimeoutException:raw=None
            if raw is None:
                history=stable._prompt_history(stable.official_handler.get_history(pid),pid)
                status=history.get('status') or {}
                if status.get('status_str')=='error':raise RuntimeError('ComfyUI执行失败，检查节点日志')
                if status.get('completed') is True:return pid,history
                continue
            if not isinstance(raw,str):continue
            message=json.loads(raw);d=message.get('data') or {}
            if d.get('prompt_id')!=pid:continue
            if message.get('type')=='execution_error':
                raise RuntimeError(f"ComfyUI node {d.get('node_id')}: {d.get('exception_message')}")
            if message.get('type')=='executing':
                node=d.get('node')
                if node is None:
                    return pid,stable._prompt_history(stable.official_handler.get_history(pid),pid)
                kind=graph.get(str(node),{}).get('class_type',str(node))
                progress(job,'executing_node',prompt_id=pid,node_id=node,node_type=kind)
            elif message.get('type')=='progress':
                progress(job,'sampling_progress',prompt_id=pid,value=d.get('value'),max=d.get('max'))
        raise TimeoutError('ComfyUI执行超时；不自动重发')
    finally:ws.close()

def handler(job):
    inp=job.get('input') or {};token=uuid.uuid4().hex;files=[];final=None;started=time.time()
    try:
        # Separate worker latch: deployment should keep this OFF until explicit approval.
        if os.getenv('WAN22_LAB_GPU_ENABLED')!='1':
            raise ValueError('独立worker推理未解锁')
        if inp.get('lab_version')!=VERSION:raise ValueError('独立客户端版本不匹配')
        mode=inp.get('mode')
        if mode not in {'person_only','person_scene','person_scene_combined'}:raise ValueError('无效测试模式')
        roles={'person':'image_url','video':'video_url'}
        if mode=='person_scene':roles['scene']='scene_url'
        if any(not inp.get(k) for k in roles.values()):raise ValueError('缺少必需素材URL')
        progress(job,'downloading_inputs',client_request_id=inp.get('client_request_id'))
        paths={}
        for role,key in roles.items():
            path=stable.COMFY_INPUT/f'lab_{token}_{role}{".mp4" if role=="video" else ".png"}'
            files.append(path);paths[role]=path
            stable._download(inp[key],path,stable.MAX_VIDEO_BYTES if role=='video' else stable.MAX_IMAGE_BYTES)
            if role!='video':stable._validate_image(path)
            progress(job,'input_downloaded',role=role)
        meta=probe(paths['video'])
        if meta['variable_frame_rate_suspected']:raise ValueError('疑似VFR：先核验原始时间轴')
        n=meta['frame_count']
        if n>401 or meta['timeline_seconds']>15:
            raise ValueError('当前版本仅允许≤15秒且≤401帧的独立短片；长视频续接未验收')
        w=build(stable._prepare_workflow(paths['person'].name,paths['video'].name,token,inp.get('seed')),mode!='person_only',combined=mode=='person_scene_combined')
        if mode=='person_scene':
            w['900']['inputs']['image']=paths['scene'].name
            w['905']['inputs']['filename_prefix']=f'wan22/{token}/reference'
        # Same frame correction on A and B lab modes; original deployed workflow is untouched.
        # Round latent window UP, then trim decoded frames to exact source N.
        w['381']['inputs']['length']=((n-1+3)//4)*4+1
        w['384']['inputs']['length']=n
        validate_graph(w)
        progress(job,'validating_runtime_schema',source_frames=n,requested_model_frames=w['381']['inputs']['length'])
        response=requests.get(f'http://{stable.official_handler.COMFY_HOST}/object_info',timeout=30)
        response.raise_for_status();errors=check(w,response.json())
        if errors:raise ValueError('Runtime schema不匹配：'+'; '.join(errors[:8]))
        progress(job,'workflow_validated')
        pid,history=run_graph(job,w)
        progress(job,'resolving_output',prompt_id=pid)
        final=stable._find_final_video(token,history,started)
        progress(job,'muxing_original_audio',prompt_id=pid)
        final=stable._mux_audio(final,paths['video'])
        output=probe(final)
        timeline={'same_frame_count':output['frame_count']==n,'same_fps':output['fps_fraction']==meta['fps_fraction'],
                  'duration_delta':output['timeline_seconds']-meta['timeline_seconds']}
        # Return file for diagnosis even if timeline fails; never call it quality passed.
        progress(job,'uploading_result',timeline_check=timeline)
        url,key=stable._upload_video(job.get('id') or token,final)
        progress(job,'completed',prompt_id=pid,timeline_check=timeline)
        return {'version':VERSION,'status':'completed','job_id':job.get('id'),'prompt_id':pid,
                'client_request_id':inp.get('client_request_id'),'mode':mode,'video_url':url,
                'object_key':key,'source_probe':meta,'output_probe':output,'timeline_check':timeline,
                'quality_accepted':False,'product_camera_continuity':'requires_visual_review',
                'elapsed_seconds':time.time()-started}
    except Exception as e:
        progress(job,'failed',error_type=type(e).__name__)
        return {'version':VERSION,'status':'failed','job_id':job.get('id'),'error':f'{type(e).__name__}: {e}',
                'client_request_id':inp.get('client_request_id'),'elapsed_seconds':time.time()-started}
    finally:
        for path in files:path.unlink(missing_ok=True)
        stable._cleanup_task_outputs(token,final_video=final)

if __name__=='__main__':
    runpod.serverless.start({'handler':handler})
