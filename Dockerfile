FROM runpod/worker-comfyui:main-base

# Wan2.2 Animate 所需自定义节点
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git && \
    git clone https://github.com/kijai/ComfyUI-WanAnimatePreprocess.git && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    git clone https://github.com/kijai/ComfyUI-segment-anything-2.git && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git

# 安装各节点依赖
RUN for d in /comfyui/custom_nodes/*; do \
      if [ -f "$d/requirements.txt" ]; then \
        pip install --no-cache-dir -r "$d/requirements.txt"; \
      fi; \
    done

WORKDIR /
