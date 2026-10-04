FROM runpod/worker-comfyui:5.11.0-base

USER root
WORKDIR /comfyui

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       git ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 1. WanAnimate preprocessing
RUN git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git \
      /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && cd /comfyui/custom_nodes/ComfyUI-WanAnimatePreprocess \
    && git checkout e63d6e71ae4c271f3f81211a7ca7f87607b7e50d

# 2. Segment Anything 2
RUN git clone https://github.com/kijai/ComfyUI-segment-anything-2.git \
      /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && cd /comfyui/custom_nodes/ComfyUI-segment-anything-2 \
    && git checkout c59676b008a76237002926f684d0ca3a9b29ac54

# 3. KJNodes
RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git \
      /comfyui/custom_nodes/ComfyUI-KJNodes \
    && cd /comfyui/custom_nodes/ComfyUI-KJNodes \
    && git checkout 00da1910634fbf314d407608efb281ae6f7f1ba2

# 4. VideoHelperSuite
RUN git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
      /comfyui/custom_nodes/ComfyUI-VideoHelperSuite

# Install dependencies into the Python environment actually used by worker-comfyui.
RUN set -eux; \
    for req in /comfyui/custom_nodes/*/requirements.txt; do \
        if [ -f "$req" ]; then \
            /opt/venv/bin/python -m pip install --no-cache-dir -r "$req"; \
        fi; \
    done; \
    /opt/venv/bin/python -m pip install --no-cache-dir "click<=8.1.8"

# Model directories only. Models are NOT baked into this Docker image.
RUN mkdir -p \
    /comfyui/models/diffusion_models \
    /comfyui/models/text_encoders \
    /comfyui/models/vae \
    /comfyui/models/clip_vision \
    /comfyui/models/loras \
    /comfyui/models/detection \
    /comfyui/models/sam2

WORKDIR /comfyui
