FROM runpod/worker-comfyui:main-base

USER root

# ============================================================
# 1. System packages + WAN2.2 Animate custom nodes
# ============================================================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        wget \
        curl \
        ca-certificates \
        ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    \
    cd /comfyui/custom_nodes && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-segment-anything-2.git && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    \
    for d in /comfyui/custom_nodes/*; do \
        if [ -f "$d/requirements.txt" ]; then \
            echo "Installing requirements: $d"; \
            pip install --no-cache-dir -r "$d/requirements.txt"; \
        fi; \
    done && \
    pip install --no-cache-dir "click<=8.1.8" && \
    pip cache purge || true


# ============================================================
# 2. Model directories
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
# 3. WAN2.2 Animate models
#    - retry downloads
#    - fail immediately on broken URL
# ============================================================
RUN set -eux; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors \
      "https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/Wan22Animate/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
      "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/vae/wan_2.1_vae.safetensors \
      "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/clip_vision/clip_vision_h.safetensors \
      "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors \
      "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors \
      "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/detection/vitpose-l-wholebody.onnx \
      "https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/wholebody/vitpose-l-wholebody.onnx"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/detection/yolov10m.onnx \
      "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/resolve/main/process_checkpoint/det/yolov10m.onnx"; \
    \
    wget --tries=5 --timeout=60 --retry-connrefused \
      -O /comfyui/models/sam2/sam2.1_hiera_base_plus.safetensors \
      "https://huggingface.co/Kijai/sam2-safetensors/resolve/main/sam2.1_hiera_base_plus.safetensors"; \
    \
    \
    test -s /comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors; \
    test -s /comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors; \
    test -s /comfyui/models/vae/wan_2.1_vae.safetensors; \
    test -s /comfyui/models/clip_vision/clip_vision_h.safetensors; \
    test -s /comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors; \
    test -s /comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors; \
    test -s /comfyui/models/detection/vitpose-l-wholebody.onnx; \
    test -s /comfyui/models/detection/yolov10m.onnx; \
    test -s /comfyui/models/sam2/sam2.1_hiera_base_plus.safetensors; \
    \
    echo "========================================"; \
    echo "WAN2.2 MODEL CHECK PASSED"; \
    echo "========================================"; \
    du -sh /comfyui/models


WORKDIR /comfyui
