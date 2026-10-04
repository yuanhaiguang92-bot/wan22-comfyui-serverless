FROM runpod/worker-comfyui:5.10.0-base

USER root
WORKDIR /comfyui

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# 1. WanAnimate preprocessing
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git \
      /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && cd /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && git checkout e63d6e71ae4c271f3f81211a7ca7f87607b7e50d

# ============================================================
# 2. Segment Anything 2
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-segment-anything-2.git \
      /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && cd /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && git checkout c59676b008a76237002926f684d0ca3a9b29ac54

# ============================================================
# 3. KJNodes
# ============================================================
RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git \
      /comfyui/custom_nodes/ComfyUI-KJNodes \
    && cd /comfyui/custom_nodes/ComfyUI-KJNodes \
    && git checkout 00da1910634fbf314d407608efb281ae6f7f1ba2

# ============================================================
# 4. VideoHelperSuite
# ============================================================
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite

# ============================================================
# Install dependencies
# ============================================================
RUN set -eux; \
    for req in /comfyui/custom_nodes/*/requirements.txt; do \
        if [ -f "$req" ]; then \
            /opt/venv/bin/python -m pip install --no-cache-dir -r "$req"; \
        fi; \
    done; \
    /opt/venv/bin/python -m pip install --no-cache-dir "click<=8.1.8"

# ============================================================
# ComfyUI model directories
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
# Runtime Cached Model auto-discovery
#
# Important:
# - No model is copied.
# - Only symlinks are created.
# - Search is restricted to likely RunPod cache/mount roots.
# ============================================================
RUN cat > /usr/local/bin/wan22-map-models.sh <<'EOF'
#!/bin/bash
set -u

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
    echo "[WAN22] ERROR: No expected model/cache roots are available."
    exit 0
fi

link_model () {
    filename="$1"
    target_dir="$2"
    target_name="${3:-$filename}"

    echo "[WAN22] Looking for: $filename"

    found=""

    for root in $SEARCH_ROOTS; do
        found="$(find "$root" -type f -name "$filename" -print -quit 2>/dev/null || true)"

        if [ -n "$found" ]; then
            break
        fi
    done

    if [ -n "$found" ]; then
        mkdir -p "$target_dir"
        ln -sf "$found" "$target_dir/$target_name"

        echo "[WAN22] FOUND: $found"
        echo "[WAN22] LINK : $target_dir/$target_name"
    else
        echo "[WAN22] NOT FOUND: $filename"
    fi
}

# 1. WAN2.2 diffusion model
link_model \
    "Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors" \
    "/comfyui/models/diffusion_models"

# 2. UMT5 text encoder
link_model \
    "umt5_xxl_fp8_e4m3fn_scaled.safetensors" \
    "/comfyui/models/text_encoders"

# 3. WAN VAE
link_model \
    "wan_2.1_vae.safetensors" \
    "/comfyui/models/vae"

# 4. CLIP Vision
link_model \
    "clip_vision_h.safetensors" \
    "/comfyui/models/clip_vision"

# 5. LightX2V LoRA
link_model \
    "lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors" \
    "/comfyui/models/loras"

# 6. WanAnimate Relight LoRA
link_model \
    "WanAnimate_relight_lora_fp16.safetensors" \
    "/comfyui/models/loras"

# 7. ViTPose
link_model \
    "vitpose-l-wholebody.onnx" \
    "/comfyui/models/detection"

# 8. YOLO
link_model \
    "yolov10m.onnx" \
    "/comfyui/models/detection"

# 9. SAM2
# Cached repository currently contains the -fp16 filename.
# Expose it using the filename accepted by the workflow node.
link_model \
    "sam2.1_hiera_base_plus-fp16.safetensors" \
    "/comfyui/models/sam2" \
    "sam2.1_hiera_base_plus.safetensors"

echo "============================================================"
echo "[WAN22] Final mapped files"
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
    echo "[WAN22] /comfyui/models/$dir"
    ls -lah "/comfyui/models/$dir" 2>/dev/null || true
done

echo "============================================================"
echo "[WAN22] Cached Model auto-discovery finished"
echo "============================================================"
EOF

RUN chmod +x /usr/local/bin/wan22-map-models.sh

# ============================================================
# Startup wrapper
# First map cached models, then launch official RunPod worker.
# ============================================================
RUN cat > /usr/local/bin/wan22-start.sh <<'EOF'
#!/bin/bash
set -e

/usr/local/bin/wan22-map-models.sh

exec /start.sh
EOF

RUN chmod +x /usr/local/bin/wan22-start.sh

WORKDIR /comfyui

CMD ["/usr/local/bin/wan22-start.sh"]
