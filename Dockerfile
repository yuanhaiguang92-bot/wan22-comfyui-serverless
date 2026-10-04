FROM runpod/worker-comfyui:5.10.0-base

USER root
WORKDIR /comfyui

RUN apt-get update && apt-get install -y --no-install-recommends git wget curl ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Custom nodes pinned to the versions detected from the uploaded workflow.
RUN git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && cd /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && git checkout e63d6e71ae4c271f3f81211a7ca7f87607b7e50d

RUN git clone https://github.com/kijai/ComfyUI-segment-anything-2.git /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && cd /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && git checkout c59676b008a76237002926f684d0ca3a9b29ac54

RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git /comfyui/custom_nodes/ComfyUI-KJNodes \
    && cd /comfyui/custom_nodes/ComfyUI-KJNodes \
    && git checkout 00da1910634fbf314d407608efb281ae6f7f1ba2

RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git /comfyui/custom_nodes/ComfyUI-VideoHelperSuite

# Install custom-node Python requirements when present.
RUN set -eux; \
    for d in \
      /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
      /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
      /comfyui/custom_nodes/ComfyUI-KJNodes \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite; do \
        if [ -f "$d/requirements.txt" ]; then pip install --no-cache-dir -r "$d/requirements.txt"; fi; \
    done; \
    pip install --no-cache-dir 'click<=8.1.8'

RUN mkdir -p \
    /comfyui/models/diffusion_models \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/clip_vision \
    /comfyui/models/loras \
    /comfyui/models/detection \
    /comfyui/models/sam2

# Download helper: fail the image build if a required model cannot be downloaded.
RUN cat > /usr/local/bin/get-model <<'SH' && chmod +x /usr/local/bin/get-model
#!/bin/sh
set -eu
url="$1"
out="$2"
mkdir -p "$(dirname "$out")"
wget --https-only --tries=5 --timeout=60 --waitretry=10 --retry-connrefused --progress=dot:giga -O "$out" "$url"
test -s "$out"
SH

# WAN 2.2 Animate + encoders + VAE + CLIP Vision + LoRAs.
RUN set -eux; \
  get-model 'https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/Wan22Animate/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors' '/comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors'; \
  get-model 'https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors' '/comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors'; \
  get-model 'https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors' '/comfyui/models/vae/wan_2.1_vae.safetensors'; \
  get-model 'https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors' '/comfyui/models/clip_vision/clip_vision_h.safetensors'; \
  get-model 'https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors' '/comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors'; \
  get-model 'https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors' '/comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors'

# WanAnimate preprocessing models. The node reads these from ComfyUI/models/detection.
RUN set -eux; \
  get-model 'https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/wholebody/vitpose-l-wholebody.onnx' '/comfyui/models/detection/vitpose-l-wholebody.onnx'; \
  get-model 'https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/resolve/main/process_checkpoint/det/yolov10m.onnx' '/comfyui/models/detection/yolov10m.onnx'

# Native FP16 safetensors checkpoint expected by ComfyUI-segment-anything-2.
RUN get-model 'https://huggingface.co/Kijai/sam2-safetensors/resolve/main/sam2.1_hiera_base_plus-fp16.safetensors' \
  '/comfyui/models/sam2/sam2.1_hiera_base_plus-fp16.safetensors'

# Build-time preflight: all nine required model files must exist and be non-empty.
RUN set -eux; \
  test -s /comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors; \
  test -s /comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors; \
  test -s /comfyui/models/vae/wan_2.1_vae.safetensors; \
  test -s /comfyui/models/clip_vision/clip_vision_h.safetensors; \
  test -s /comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors; \
  test -s /comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors; \
  test -s /comfyui/models/detection/vitpose-l-wholebody.onnx; \
  test -s /comfyui/models/detection/yolov10m.onnx; \
  test -s /comfyui/models/sam2/sam2.1_hiera_base_plus-fp16.safetensors; \
  echo 'WAN2.2 MODEL CHECK PASSED'

WORKDIR /comfyui
