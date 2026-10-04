FROM runpod/worker-comfyui:5.10.0-base

USER root
WORKDIR /comfyui

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Custom Nodes
# ============================================================

# ------------------------------------------------------------
# WanAnimatePreprocess
# Keep the already-tested stable commit.
# Then apply ONLY the ONNX detection compatibility fix.
# No cherry-pick. No pyproject.toml changes.
# ------------------------------------------------------------

RUN git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git \
      /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && cd /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && git checkout e63d6e71ae4c271f3f81211a7ca7f87607b7e50d

# ============================================================
# ONNX Detection Compatibility Fix
#
# Root cause:
# Current ComfyUI already has a "detection" model category.
# .onnx must be added to its supported extensions.
# Existing filename caches must then be cleared.
#
# We insert the fix immediately after "import folder_paths".
# ============================================================

RUN /opt/venv/bin/python - <<'PY'
from pathlib import Path

p = Path("/comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess/nodes.py")

text = p.read_text(encoding="utf-8")

marker = "import folder_paths"

if marker not in text:
    raise RuntimeError(
        "WAN22 PATCH ERROR: 'import folder_paths' was not found in nodes.py"
    )

patch = r'''
# ============================================================
# WAN22 / Current ComfyUI ONNX detection compatibility fix
# ============================================================

# Current ComfyUI may already register the "detection" category.
# Make sure ONNX files are included in the allowed extensions.

if "detection" in folder_paths.folder_names_and_paths:
    _det_paths, _det_exts = folder_paths.folder_names_and_paths["detection"]

    _det_exts = set(_det_exts)
    _det_exts.add(".onnx")

    folder_paths.folder_names_and_paths["detection"] = (
        _det_paths,
        _det_exts,
    )
else:
    folder_paths.folder_names_and_paths["detection"] = (
        [folder_paths.get_folder_paths("detection")[0]],
        {".onnx"},
    )

# Clear old detection filename cache after changing extensions.

if hasattr(folder_paths, "filename_list_cache"):
    folder_paths.filename_list_cache.pop("detection", None)

# Current ComfyUI also has cache_helper.
# Clear it so get_filename_list("detection") is rebuilt.

if hasattr(folder_paths, "cache_helper"):
    try:
        folder_paths.cache_helper.clear()
    except Exception:
        pass

# ============================================================
# End WAN22 compatibility fix
# ============================================================
'''

if "WAN22 / Current ComfyUI ONNX detection compatibility fix" in text:
    raise RuntimeError(
        "WAN22 PATCH ERROR: compatibility patch already exists"
    )

text = text.replace(marker, marker + "\n" + patch, 1)

p.write_text(text, encoding="utf-8")

print("============================================================")
print("[WAN22] ONNX detection compatibility patch applied")
print("[WAN22] Patched file:", p)
print("============================================================")
PY

# Verify the patch during Docker build.
# If it is not present, BUILD MUST fail here instead of wasting
# time starting a worker with an unpatched node.

RUN grep -n \
    "WAN22 / Current ComfyUI ONNX detection compatibility fix" \
    /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess/nodes.py \
    && grep -n \
    'filename_list_cache.pop("detection", None)' \
    /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess/nodes.py \
    && grep -n \
    'cache_helper.clear()' \
    /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess/nodes.py

# ------------------------------------------------------------
# Other custom nodes - unchanged
# ------------------------------------------------------------

RUN git clone https://github.com/kijai/ComfyUI-segment-anything-2.git \
      /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && cd /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && git checkout c59676b008a76237002926f684d0ca3a9b29ac54

RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git \
      /comfyui/custom_nodes/ComfyUI-KJNodes \
    && cd /comfyui/custom_nodes/ComfyUI-KJNodes \
    && git checkout 00da1910634fbf314d407608efb281ae6f7f1ba2

RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite

# ============================================================
# Custom Node Requirements
# ============================================================

RUN set -eux; \
    for req in /comfyui/custom_nodes/*/requirements.txt; do \
        if [ -f "$req" ]; then \
            /opt/venv/bin/python -m pip install --no-cache-dir -r "$req"; \
        fi; \
    done; \
    /opt/venv/bin/python -m pip install --no-cache-dir "click<=8.1.8"; \
    /opt/venv/bin/python -m pip uninstall -y onnxruntime onnxruntime-gpu || true; \
    /opt/venv/bin/python -m pip install --no-cache-dir "onnxruntime-gpu==1.26.0"

# Fail the Docker build if ORT is not the CUDA 12.8-compatible build we expect.
RUN /opt/venv/bin/python - <<'PY'
import onnxruntime as ort

print("============================================================")
print("[WAN22] ONNX Runtime build-time verification")
print("[WAN22] ORT version:", ort.__version__)
print("[WAN22] Providers:", ort.get_available_providers())
print("============================================================")

if ort.__version__ != "1.26.0":
    raise RuntimeError(f"WAN22 ORT ERROR: expected 1.26.0, got {ort.__version__}")

if "CUDAExecutionProvider" not in ort.get_available_providers():
    raise RuntimeError(
        "WAN22 ORT ERROR: CUDAExecutionProvider is not registered"
    )
PY

# ============================================================
# Model Directories
# ============================================================

RUN mkdir -p \
    /comfyui/models/diffusion_models \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/clip_vision \
    /comfyui/models/loras \
    /comfyui/models/detection \
    /comfyui/models/sam2

# ============================================================
# RunPod Cached Model Auto Discovery
# ============================================================

RUN cat > /usr/local/bin/wan22-map-models.sh <<'EOF'
#!/bin/bash
set -eu

echo "============================================================"
echo "[WAN22] Cached Model auto-discovery starting"
echo "============================================================"

SEARCH_ROOTS=""

for root in \
    /runpod-volume \
    /workspace \
    /root/.cache/huggingface \
    /huggingface-cache
do
    if [ -d "$root" ]; then
        SEARCH_ROOTS="$SEARCH_ROOTS $root"
        echo "[WAN22] Search root available: $root"
    fi
done

if [ -z "$SEARCH_ROOTS" ]; then
    echo "[WAN22] ERROR: No expected model/cache roots available."
    exit 1
fi

link_model () {
    filename="$1"
    target_dir="$2"
    target_name="${3:-$filename}"

    echo "[WAN22] Looking for: $filename"

    found=""

    for root in $SEARCH_ROOTS; do
        found="$(find "$root" -name "$filename" -print -quit 2>/dev/null || true)"

        if [ -n "$found" ]; then
            break
        fi
    done

    if [ -z "$found" ]; then
        echo "[WAN22] NOT FOUND: $filename"
        return 1
    fi

    mkdir -p "$target_dir"

    resolved="$(readlink -f "$found" 2>/dev/null || true)"

    if [ -n "$resolved" ]; then
        ln -sf "$resolved" "$target_dir/$target_name"
        echo "[WAN22] FOUND   : $found"
        echo "[WAN22] RESOLVED: $resolved"
    else
        ln -sf "$found" "$target_dir/$target_name"
        echo "[WAN22] FOUND   : $found"
    fi

    echo "[WAN22] LINK    : $target_dir/$target_name"

    if [ ! -e "$target_dir/$target_name" ]; then
        echo "[WAN22] ERROR: link verification failed: $target_dir/$target_name"
        return 1
    fi
}

# ============================================================
# Main WAN2.2 Models
# ============================================================

link_model \
    "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors" \
    "/comfyui/models/diffusion_models"

link_model \
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    "/comfyui/models/text_encoders"

link_model \
    "wan_2.1_vae.safetensors" \
    "/comfyui/models/vae"

link_model \
    "clip_vision_h.safetensors" \
    "/comfyui/models/clip_vision"

# ============================================================
# LoRA
# ============================================================

link_model \
    "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" \
    "/comfyui/models/loras"

link_model \
    "WanAnimate_relight_lora_fp16.safetensors" \
    "/comfyui/models/loras"

# ============================================================
# ONNX Detection
# ============================================================

link_model \
    "vitpose-l-wholebody.onnx" \
    "/comfyui/models/detection"

link_model \
    "yolov10m.onnx" \
    "/comfyui/models/detection"

# ============================================================
# SAM2
# ============================================================

link_model \
    "sam2.1_hiera_base_plus-fp16.safetensors" \
    "/comfyui/models/sam2" \
    "sam2.1_hiera_base_plus.safetensors"

# ============================================================
# Final Verification
# ============================================================

echo "============================================================"
echo "[WAN22] Final model mapping verification"
echo "============================================================"

for dir in \
    diffusion_models \
    text_encoders \
    vae \
    clip_vision \
    loras \
    detection \
    sam2
do
    echo ""
    echo "[WAN22] /comfyui/models/$dir"
    ls -lah "/comfyui/models/$dir" || true
done

echo ""
echo "[WAN22] Detection verification"

test -e "/comfyui/models/detection/vitpose-l-wholebody.onnx"
test -e "/comfyui/models/detection/yolov10m.onnx"

echo "[WAN22] vitpose OK"
echo "[WAN22] yolov10m OK"

echo "============================================================"
echo "[WAN22] Cached Model mapping completed BEFORE ComfyUI startup"
echo "============================================================"
EOF

RUN chmod +x /usr/local/bin/wan22-map-models.sh

# ============================================================
# Startup
# ============================================================

RUN cat > /usr/local/bin/wan22-start.sh <<'EOF'
#!/bin/bash
set -e

echo "============================================================"
echo "[WAN22] PRE-COMFYUI STARTUP"
echo "============================================================"

/usr/local/bin/wan22-map-models.sh

echo ""
echo "[WAN22] ONNX Runtime GPU startup verification:"
/opt/venv/bin/python - <<'PY'
import onnxruntime as ort

print("[WAN22] ORT version:", ort.__version__)
print("[WAN22] Available providers:", ort.get_available_providers())

if ort.__version__ != "1.26.0":
    raise RuntimeError(f"WAN22 ORT ERROR: expected 1.26.0, got {ort.__version__}")

if "CUDAExecutionProvider" not in ort.get_available_providers():
    raise RuntimeError("WAN22 ORT ERROR: CUDAExecutionProvider unavailable")
PY

echo ""
echo "[WAN22] Detection files immediately before /start.sh:"
ls -lah /comfyui/models/detection

echo ""
echo "[WAN22] Starting official RunPod ComfyUI worker..."
echo "============================================================"

exec /start.sh
EOF

RUN chmod +x /usr/local/bin/wan22-start.sh

# ============================================================
# Start Worker
# ============================================================

WORKDIR /comfyui

CMD ["/usr/local/bin/wan22-start.sh"]
