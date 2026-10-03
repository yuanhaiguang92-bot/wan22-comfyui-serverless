FROM runpod/worker-comfyui:main-base

USER root

# ---------------------------------------------------------
# 1. 基础工具
# ---------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# 2. Wan2.2 Animate 所需自定义节点
# ---------------------------------------------------------
RUN cd /comfyui/custom_nodes && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-segment-anything-2.git && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git

# ---------------------------------------------------------
# 3. 安装自定义节点依赖
# ---------------------------------------------------------
RUN for d in /comfyui/custom_nodes/*; do \
      if [ -f "$d/requirements.txt" ]; then \
        echo "Installing requirements for $d"; \
        pip install --no-cache-dir -r "$d/requirements.txt"; \
      fi; \
    done

# ---------------------------------------------------------
# 4. 创建模型目录
# ---------------------------------------------------------
RUN mkdir -p \
    /comfyui/models/diffusion_models \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/clip_vision \
    /comfyui/models/loras \
    /comfyui/models/detection \
    /comfyui/models/sam2

# ---------------------------------------------------------
# 5. Wan2.2 Animate 14B FP8 主模型
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy_fp8_scaled/resolve/main/Wan22Animate/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors"

# ---------------------------------------------------------
# 6. UMT5 Text Encoder
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors"

# ---------------------------------------------------------
# 7. Wan VAE
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/vae/wan_2.1_vae.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/vae/wan_2.1_vae.safetensors"

# ---------------------------------------------------------
# 8. CLIP Vision
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/clip_vision/clip_vision_h.safetensors \
    "https://huggingface.co/Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files/clip_vision/clip_vision_h.safetensors"

# ---------------------------------------------------------
# 9. LightX2V LoRA
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/Lightx2v/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors"

# ---------------------------------------------------------
# 10. Wan Animate Relight LoRA
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors \
    "https://huggingface.co/Kijai/WanVideo_comfy/resolve/main/LoRAs/Wan22_relight/WanAnimate_relight_lora_fp16.safetensors"

# ---------------------------------------------------------
# 11. ViTPose Large Wholebody
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/detection/vitpose-l-wholebody.onnx \
    "https://huggingface.co/JunkyByte/easy_ViTPose/resolve/main/onnx/wholebody/vitpose-l-wholebody.onnx"

# ---------------------------------------------------------
# 12. YOLOv10m
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/detection/yolov10m.onnx \
    "https://huggingface.co/Wan-AI/Wan2.2-Animate-14B/resolve/main/process_checkpoint/det/yolov10m.onnx"

# ---------------------------------------------------------
# 13. SAM2.1 Base Plus
# ---------------------------------------------------------
RUN wget -q --show-progress \
    -O /comfyui/models/sam2/sam2.1_hiera_base_plus.safetensors \
    "https://huggingface.co/Kijai/sam2-safetensors/resolve/main/sam2.1_hiera_base_plus.safetensors"

# ---------------------------------------------------------
# 14. 最后检查关键文件，Build 时缺任何一个直接失败
# ---------------------------------------------------------
RUN test -s /comfyui/models/diffusion_models/Wan2_2-Animate-14B_fp8_e4m3fn_scaled_KJ.safetensors && \
    test -s /comfyui/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors && \
    test -s /comfyui/models/vae/wan_2.1_vae.safetensors && \
    test -s /comfyui/models/clip_vision/clip_vision_h.safetensors && \
    test -s /comfyui/models/loras/lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors && \
    test -s /comfyui/models/loras/WanAnimate_relight_lora_fp16.safetensors && \
    test -s /comfyui/models/detection/vitpose-l-wholebody.onnx && \
    test -s /comfyui/models/detection/yolov10m.onnx && \
    test -s /comfyui/models/sam2/sam2.1_hiera_base_plus.safetensors

WORKDIR /comfyui
