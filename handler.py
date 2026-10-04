import copy
import ipaddress
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3
import requests
import runpod
import websocket
from PIL import Image

import official_handler


# ============================================================
# WAN2.2 Serverless Adapter
# V2: robust SaveVideo discovery + history-first lookup
#     + safe filesystem fallback + optional workflow hot update
#     + FFmpeg audio mux (bring original video's audio into final)
# ============================================================

COMFY_INPUT = Path("/comfyui/input")
DEFAULT_COMFY_OUTPUT = Path("/comfyui/output")
WORKFLOW_FILE = Path("/opt/wan22/wan22_workflow.json")

MAX_IMAGE_BYTES = int(os.getenv("WAN22_MAX_IMAGE_MB", "25")) * 1024 * 1024
MAX_VIDEO_BYTES = int(os.getenv("WAN22_MAX_VIDEO_MB", "500")) * 1024 * 1024
DOWNLOAD_TIMEOUT = int(os.getenv("WAN22_DOWNLOAD_TIMEOUT", "300"))
EXECUTION_TIMEOUT = int(os.getenv("WAN22_EXECUTION_TIMEOUT", "1800"))
OUTPUT_WAIT_SECONDS = int(os.getenv("WAN22_OUTPUT_WAIT_SECONDS", "45"))
OUTPUT_BUCKET = os.getenv("WAN22_OUTPUT_BUCKET", "").strip()
OUTPUT_URL_EXPIRES = int(os.getenv("WAN22_OUTPUT_URL_EXPIRES", "3600"))
ALLOW_HTTP = os.getenv("WAN22_ALLOW_HTTP", "false").lower() == "true"

# Optional hot-update URL. Leave empty in production if you want the baked workflow.
# Example:
# https://raw.githubusercontent.com/yuanhaiguang92-bot/wan22-comfyui-serverless/main/wan22_workflow.json
WORKFLOW_URL = os.getenv("WAN22_WORKFLOW_URL", "").strip()

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov"}


def _log(message):
    print(f"[WAN22] {message}", flush=True)


def _safe_url(url):
    if not isinstance(url, str) or not url.strip():
        raise ValueError("image_url/video_url must be a non-empty URL")

    p = urlparse(url.strip())
    allowed = {"https"} | ({"http"} if ALLOW_HTTP else set())

    if p.scheme.lower() not in allowed:
        raise ValueError("Only HTTPS input URLs are allowed")

    if not p.hostname:
        raise ValueError("Input URL has no hostname")

    try:
        infos = socket.getaddrinfo(
            p.hostname,
            p.port or (443 if p.scheme.lower() == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as e:
        raise ValueError(f"Cannot resolve input host: {p.hostname}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("Private/local input URLs are not allowed")

    return url.strip()


def _download(url, dst, max_bytes):
    url = _safe_url(url)
    dst.parent.mkdir(parents=True, exist_ok=True)
    total = 0

    with requests.get(
        url,
        stream=True,
        timeout=(20, DOWNLOAD_TIMEOUT),
        allow_redirects=True,
        headers={"User-Agent": "WAN22-RunPod-Adapter/2.0"},
    ) as r:
        r.raise_for_status()

        length = r.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise ValueError(
                f"Input file exceeds limit: {max_bytes // (1024 * 1024)} MB"
            )

        with dst.open("wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if not chunk:
                    continue

                total += len(chunk)
                if total > max_bytes:
                    raise ValueError(
                        f"Input file exceeds limit: {max_bytes // (1024 * 1024)} MB"
                    )

                f.write(chunk)

    if total == 0:
        raise ValueError("Downloaded input file is empty")

    return total


def _validate_image(path):
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception as e:
        raise ValueError("image_url did not produce a valid image") from e


def _probe_video(path):
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name,width,height,duration",
        "-show_entries",
        "format=duration,format_name",
        "-of",
        "json",
        str(path),
    ]

    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        data = json.loads(p.stdout or "{}")
    except Exception as e:
        raise ValueError(f"Unreadable video file: {path}") from e

    if not (data.get("streams") or []):
        raise ValueError(f"Video contains no video stream: {path}")

    return data


def _validate_video(path):
    return _probe_video(path)


def _mux_audio(silent_video, source_video):
    """
    Bring the ORIGINAL driving video's (source_video) audio track into the
    silent final result (silent_video).

    - source has no audio track -> return the silent version (no error)
    - mux fails / verify fails  -> return the silent version (keep original, do not delete)
    - success                   -> return the new muxed file path (video + audio)
    """
    silent_video = Path(silent_video)
    source_video = Path(source_video)

    # 1) Does the source driving video have an audio stream?
    try:
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(source_video),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        has_audio = "audio" in (probe.stdout or "")
    except Exception as e:
        _log(f"mux: probe source audio failed, keep silent: {e}")
        return silent_video

    if not has_audio:
        _log("mux: source video has no audio track, keep silent output")
        return silent_video

    # 2) Mux: copy video stream (no re-encode), encode audio to AAC, shortest.
    out_path = silent_video.with_name(silent_video.stem + "_audio.mp4")
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(silent_video),
                "-i",
                str(source_video),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as e:
        _log(f"mux: ffmpeg failed, keep silent: {e}")
        return silent_video

    if not out_path.is_file() or out_path.stat().st_size < 2000:
        _log("mux: output missing/too small, keep silent")
        return silent_video

    # 3) Verify the muxed file really has both a video and an audio stream.
    try:
        v = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        a = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "csv=p=0",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception as e:
        _log(f"mux: verify failed, keep silent: {e}")
        return silent_video

    if "video" in v and "audio" in a:
        _log(f"mux: success, final with audio -> {out_path}")
        return out_path

    _log("mux: verify did not pass, keep silent")
    return silent_video


def _load_workflow():
    """
    Order:
    1) WAN22_WORKFLOW_URL (optional hot-update mode)
    2) baked /opt/wan22/wan22_workflow.json
    """
    if WORKFLOW_URL:
        _log(f"Loading workflow from WAN22_WORKFLOW_URL: {WORKFLOW_URL}")
        url = _safe_url(WORKFLOW_URL)

        r = requests.get(
            url,
            timeout=(15, 60),
            allow_redirects=True,
            headers={
                "User-Agent": "WAN22-RunPod-Adapter/2.0",
                "Cache-Control": "no-cache",
            },
        )
        r.raise_for_status()

        if len(r.content) > 5 * 1024 * 1024:
            raise ValueError("Remote workflow JSON is unexpectedly larger than 5 MB")

        wf = r.json()
        if not isinstance(wf, dict):
            raise ValueError("Remote workflow JSON must be an object")
        return wf

    wf = json.loads(WORKFLOW_FILE.read_text(encoding="utf-8"))
    if not isinstance(wf, dict):
        raise ValueError("Baked workflow JSON must be an object")
    return wf


def _prepare_workflow(image_name, video_name, token, seed=None):
    wf = copy.deepcopy(_load_workflow())

    wf["10"]["inputs"]["image"] = image_name
    wf["301"]["inputs"]["video"] = video_name

    preview = wf["301"]["inputs"].get("videopreview")
    if isinstance(preview, dict) and isinstance(preview.get("params"), dict):
        preview["params"]["filename"] = video_name
        preview["params"]["type"] = "input"

    # Keep every output isolated by this request token.
    for node_id, label in {
        "19": "final",
        "353": "pose",
        "354": "mask",
        "359": "detect",
    }.items():
        if node_id in wf and wf[node_id].get("class_type") == "SaveVideo":
            wf[node_id]["inputs"]["filename_prefix"] = (
                f"wan22/{token}/{label}"
            )

    if seed is not None:
        seed = int(seed)
        if seed < 0:
            seed = int.from_bytes(os.urandom(8), "big") & ((1 << 63) - 1)

        if "379" not in wf:
            raise ValueError("Seed was supplied but workflow node 379 is missing")

        wf["379"]["inputs"]["value"] = seed

    return wf


def _wait(prompt_id, client_id):
    ws = websocket.WebSocket()
    ws.settimeout(30)
    started = time.monotonic()

    try:
        ws.connect(
            f"ws://{official_handler.COMFY_HOST}/ws?clientId={client_id}",
            timeout=10,
        )

        while True:
            if time.monotonic() - started > EXECUTION_TIMEOUT:
                raise TimeoutError(
                    f"WAN22 execution exceeded {EXECUTION_TIMEOUT} seconds"
                )

            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue

            if not isinstance(raw, str):
                continue

            msg = json.loads(raw)
            data = msg.get("data") or {}

            if (
                msg.get("type") == "execution_error"
                and data.get("prompt_id") == prompt_id
            ):
                raise RuntimeError(
                    f"ComfyUI node {data.get('node_id')} "
                    f"({data.get('node_type')}): "
                    f"{data.get('exception_message')}"
                )

            if (
                msg.get("type") == "executing"
                and data.get("prompt_id") == prompt_id
                and data.get("node") is None
            ):
                return

    finally:
        try:
            ws.close()
        except Exception:
            pass


def _prompt_history(history, prompt_id):
    if not isinstance(history, dict):
        return {}

    ph = history.get(prompt_id)
    if isinstance(ph, dict):
        return ph

    # Some wrappers may already return the single prompt payload.
    if "outputs" in history or "status" in history:
        return history

    return {}


def _output_roots():
    """
    Build a small list of plausible ComfyUI output roots.
    The official worker can expose COMFY_OUTPUT_PATH depending on release.
    """
    roots = []

    env_path = os.getenv("COMFY_OUTPUT_PATH", "").strip()
    if env_path:
        roots.append(Path(env_path))

    official_path = getattr(official_handler, "COMFY_OUTPUT_PATH", None)
    if isinstance(official_path, str) and official_path.strip():
        roots.append(Path(official_path.strip()))

    roots.extend(
        [
            DEFAULT_COMFY_OUTPUT,
            Path("/runpod-volume/ComfyUI/output"),
            Path("/workspace/ComfyUI/output"),
        ]
    )

    unique = []
    seen = set()

    for root in roots:
        try:
            key = str(root.resolve(strict=False))
        except Exception:
            key = str(root)

        if key not in seen:
            seen.add(key)
            unique.append(root)

    return unique


def _walk_saved_results(obj):
    """
    Recursively collect ComfyUI UI output descriptors.
    SaveVideo currently reports filename/subfolder/type metadata,
    but this intentionally does not depend on a specific wrapper key.
    """
    found = []

    if isinstance(obj, dict):
        filename = obj.get("filename")

        if isinstance(filename, str) and filename.strip():
            found.append(
                {
                    "filename": filename.strip(),
                    "subfolder": str(obj.get("subfolder") or "").strip(),
                    "type": str(obj.get("type") or "output").strip().lower(),
                }
            )

        for value in obj.values():
            found.extend(_walk_saved_results(value))

    elif isinstance(obj, list):
        for value in obj:
            found.extend(_walk_saved_results(value))

    return found


def _safe_subfolder(value):
    if not value:
        return Path()

    p = Path(value)

    if p.is_absolute() or ".." in p.parts:
        return Path()

    return p


def _paths_from_history_node(ph, node_id="19"):
    outputs = ph.get("outputs") if isinstance(ph, dict) else None

    if not isinstance(outputs, dict):
        return []

    node_output = outputs.get(str(node_id))
    if node_output is None:
        node_output = outputs.get(node_id)

    if node_output is None:
        return []

    descriptors = _walk_saved_results(node_output)
    paths = []

    for item in descriptors:
        filename = Path(item["filename"]).name
        if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        subfolder = _safe_subfolder(item.get("subfolder"))
        item_type = item.get("type", "output")

        if item_type == "output":
            bases = _output_roots()
        elif item_type == "temp":
            bases = [Path("/comfyui/temp")]
        elif item_type == "input":
            bases = [COMFY_INPUT]
        else:
            bases = _output_roots()

        for base in bases:
            paths.append(base / subfolder / filename)

    # Preserve order but deduplicate.
    result = []
    seen = set()

    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            result.append(p)

    return result


def _wait_for_stable_file(path, timeout=15):
    """
    Wait until a file exists, is non-empty and its size is stable across
    consecutive checks. This prevents uploading a partially flushed MP4.
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_hits = 0

    while time.monotonic() < deadline:
        try:
            if path.is_file():
                size = path.stat().st_size

                if size > 0 and size == last_size:
                    stable_hits += 1
                else:
                    stable_hits = 0

                last_size = size

                if size > 0 and stable_hits >= 2:
                    return path
        except FileNotFoundError:
            pass

        time.sleep(0.5)

    return None


def _recent_video_files(since_wall, limit=40):
    rows = []

    for root in _output_roots():
        if not root.exists():
            continue

        try:
            iterator = root.rglob("*")
        except Exception:
            continue

        for p in iterator:
            try:
                if (
                    p.is_file()
                    and p.suffix.lower() in VIDEO_EXTENSIONS
                    and p.stat().st_size > 0
                    and p.stat().st_mtime >= since_wall - 10
                ):
                    rows.append(
                        (
                            p.stat().st_mtime,
                            p.stat().st_size,
                            p,
                        )
                    )
            except (FileNotFoundError, PermissionError, OSError):
                continue

    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return rows[:limit]


def _score_video_candidate(path, token):
    s = str(path).replace("\\", "/").lower()
    name = path.name.lower()
    score = 0

    if token.lower() in s:
        score += 1000

    if "/final" in s or name.startswith("final") or "_final" in name:
        score += 500

    if "/pose" in s or "/mask" in s or "/detect" in s:
        score -= 600

    if "pose" in name or "mask" in name or "detect" in name:
        score -= 600

    return score


def _find_final_video(token, ph, started_wall):
    """
    Discovery strategy:
    1) Exact Node 19 output metadata from ComfyUI history.
    2) Filesystem fallback across known output roots.
    3) Never silently return pose/mask/detect debug outputs.
    """
    _log("Resolving final video from ComfyUI Node 19 history metadata")

    history_paths = _paths_from_history_node(ph, "19")

    for path in history_paths:
        stable = _wait_for_stable_file(path, timeout=8)
        if stable:
            _log(f"Final video found from Node 19 history: {stable}")
            return stable

    _log(
        "Node 19 history did not resolve to an existing file; "
        "starting filesystem fallback scan"
    )

    deadline = time.monotonic() + OUTPUT_WAIT_SECONDS
    last_recent = []

    while time.monotonic() < deadline:
        recent = _recent_video_files(started_wall)
        last_recent = recent

        ranked = []

        for mtime, size, path in recent:
            score = _score_video_candidate(path, token)
            if score > 0:
                ranked.append((score, mtime, size, path))

        if ranked:
            ranked.sort(
                key=lambda x: (x[0], x[1], x[2]),
                reverse=True,
            )

            for score, _, _, path in ranked:
                # Require a strong "final" identity. This prevents returning
                # pose/mask/detect if only debug videos exist.
                if score < 500:
                    continue

                stable = _wait_for_stable_file(path, timeout=5)
                if stable:
                    _log(
                        f"Final video found by filesystem fallback "
                        f"(score={score}): {stable}"
                    )
                    return stable

        time.sleep(1)

    history_summary = [
        str(p) for p in history_paths[:20]
    ]

    recent_summary = [
        {
            "path": str(path),
            "size": size,
            "score": _score_video_candidate(path, token),
        }
        for _, size, path in last_recent[:20]
    ]

    raise FileNotFoundError(
        "Node 19 final video could not be resolved. "
        f"token={token}; "
        f"output_roots={[str(x) for x in _output_roots()]}; "
        f"history_candidates={history_summary}; "
        f"recent_video_candidates={recent_summary}"
    )


def _content_type_for_video(path):
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("video/"):
        return guessed

    if path.suffix.lower() == ".webm":
        return "video/webm"

    if path.suffix.lower() == ".mkv":
        return "video/x-matroska"

    if path.suffix.lower() == ".mov":
        return "video/quicktime"

    return "video/mp4"


def _upload_video(job_id, path):
    endpoint_url = os.getenv("BUCKET_ENDPOINT_URL", "").strip()
    access_key = os.getenv("BUCKET_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("BUCKET_SECRET_ACCESS_KEY", "").strip()
    region = os.getenv("BUCKET_REGION", "auto").strip() or "auto"

    if not (
        endpoint_url
        and access_key
        and secret_key
        and OUTPUT_BUCKET
    ):
        raise RuntimeError(
            "S3 output is not configured. Set BUCKET_ENDPOINT_URL, "
            "BUCKET_ACCESS_KEY_ID, BUCKET_SECRET_ACCESS_KEY and "
            "WAN22_OUTPUT_BUCKET."
        )

    key = f"wan22/{job_id}/{path.name}"
    content_type = _content_type_for_video(path)

    _log(
        f"Uploading final video to bucket={OUTPUT_BUCKET}, "
        f"key={key}, content_type={content_type}"
    )

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
    )

    s3.upload_file(
        str(path),
        OUTPUT_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type},
    )

    # Bucket is private. Return a temporary signed GET URL so the local
    # HTML tester can play the result immediately without making R2 public.
    signed_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": OUTPUT_BUCKET,
            "Key": key,
        },
        ExpiresIn=OUTPUT_URL_EXPIRES,
    )

    return signed_url, key


def _cleanup_task_outputs(token, final_video=None):
    """
    Only remove files belonging to this request token.
    Never wipe the whole ComfyUI output directory.
    """
    for root in _output_roots():
        token_dir = root / "wan22" / token
        if token_dir.exists():
            shutil.rmtree(token_dir, ignore_errors=True)

    if final_video is not None:
        try:
            s = str(final_video).replace("\\", "/")
            if token in s and final_video.exists():
                final_video.unlink(missing_ok=True)
        except Exception:
            pass


def handler(job):
    inp = job.get("input") or {}
    job_id = str(job.get("id") or uuid.uuid4())

    image_url = inp.get("image_url")
    video_url = inp.get("video_url")
    seed = inp.get("seed")

    if not image_url or not video_url:
        return {
            "error": "Both input.image_url and input.video_url are required"
        }

    if not official_handler.check_server(
        f"http://{official_handler.COMFY_HOST}/",
        official_handler.COMFY_API_AVAILABLE_MAX_RETRIES,
        official_handler.COMFY_API_AVAILABLE_INTERVAL_MS,
    ):
        return {"error": "ComfyUI server is not reachable"}

    token = uuid.uuid4().hex
    image_path = COMFY_INPUT / f"wan22_{token}.png"
    video_path = COMFY_INPUT / f"wan22_{token}.mp4"

    final_video = None
    started_wall = time.time()

    try:
        _log(f"Job started: job_id={job_id}, token={token}")
        _log(f"Output roots: {[str(x) for x in _output_roots()]}")

        ib = _download(
            image_url,
            image_path,
            MAX_IMAGE_BYTES,
        )
        _validate_image(image_path)

        vb = _download(
            video_url,
            video_path,
            MAX_VIDEO_BYTES,
        )
        input_meta = _validate_video(video_path)

        workflow = _prepare_workflow(
            image_path.name,
            video_path.name,
            token,
            seed,
        )

        client_id = str(uuid.uuid4())

        queued = official_handler.queue_workflow(
            workflow,
            client_id,
        )

        prompt_id = queued.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(
                f"ComfyUI returned no prompt_id: {queued}"
            )

        _log(f"Queued ComfyUI prompt_id={prompt_id}")

        _wait(
            prompt_id,
            client_id,
        )

        history = official_handler.get_history(prompt_id)
        ph = _prompt_history(history, prompt_id)

        status = ph.get("status") or {}
        if status.get("status_str") == "error":
            raise RuntimeError(
                f"ComfyUI execution failed: {status}"
            )

        _log(
            "ComfyUI execution finished; resolving Node 19 final SaveVideo output"
        )

        final_video = _find_final_video(
            token,
            ph,
            started_wall,
        )

        # Mux the original driving video's audio back into the final video.
        # On any failure (no audio / mux error) this safely returns the
        # original silent final_video, so the task never fails because of audio.
        final_video = _mux_audio(final_video, video_path)

        final_meta = _probe_video(final_video)
        size = final_video.stat().st_size

        _log(
            f"Validated final video: path={final_video}, "
            f"size={size} bytes"
        )

        url, object_key = _upload_video(
            job_id,
            final_video,
        )

        _log("Final video upload completed")

        return {
            "status": "completed",
            "job_id": job_id,
            "prompt_id": prompt_id,
            "video_url": url,
            "object_key": object_key,
            "size_bytes": size,
            "input_image_bytes": ib,
            "input_video_bytes": vb,
            "input_video_probe": input_meta,
            "output_video_probe": final_meta,
        }

    except Exception as e:
        _log(f"ERROR: {type(e).__name__}: {e}")
        return {
            "error": f"{type(e).__name__}: {e}",
            "job_id": job_id,
            "token": token,
        }

    finally:
        for p in (image_path, video_path):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

        _cleanup_task_outputs(
            token,
            final_video=final_video,
        )


if __name__ == "__main__":
    print(
        "WAN22 adapter V2 - starting RunPod handler",
        flush=True,
    )
    runpod.serverless.start({"handler": handler})
