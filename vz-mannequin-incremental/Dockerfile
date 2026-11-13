# Build context: vz-mannequin-incremental/ (directory containing this Dockerfile).
# Additive candidate: preserve current ComfyUI, dependencies, handler and startup.
FROM registry.runpod.net/yuanhaiguang92-bot-wan22-comfyui-serverless-vz-flux3-vz-flux3-dockerfile_1402948263_b70ed4d2b4feefc4e12b:d6a0a5a43

COPY inherited-files.sha256 /tmp/vz-inherited-files.sha256
RUN cd /comfyui && sha256sum -c /tmp/vz-inherited-files.sha256
COPY vz_mannequin /comfyui/custom_nodes/vz_mannequin
RUN python -m py_compile /comfyui/custom_nodes/vz_mannequin/__init__.py

# Fixed upstream revision; no tokens, pip upgrades or changes to old model files.
ADD https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/54472221d27c695fca9621b0c3ed52f06c4af707/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors /opt/vz-models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
RUN echo 'bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923  /opt/vz-models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors' | sha256sum -c -

# /vz-start.sh already links /opt/vz-models/*/ to ComfyUI on worker start.
# Inherit original ENTRYPOINT, CMD and environment without replacement.
LABEL org.vaziro.mannequin.version="vz-mannequin-2048-v1"
