# TEST image: FLUX 3 Image Klein. Same official RunPod ComfyUI worker, with ComfyUI upgraded to a pinned
# master commit that includes FLUX 3 support (Flux3 model, flux3 text encoder, ReferenceMultiLatent).
# Weights come from the RunPod cached model "black-forest-labs/flux-3-image-klein-comfy" (not redistributed).
FROM runpod/worker-comfyui:5.10.0-base@sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538
COPY runtime-constraints.txt /tmp/vz-runtime-constraints.txt
COPY expected-runtime.json verify_runtime.py /opt/vz-audit/
ARG COMFY_SHA=fb2b26fdac507b7da81277c7becaf54c5e46ac6b
RUN set -eux; cd /tmp && git clone -q https://github.com/Comfy-Org/ComfyUI.git cu && cd cu && git checkout -q ${COMFY_SHA} \
 && tar -C /tmp/cu --exclude=./models --exclude=./custom_nodes --exclude=./user --exclude=./input --exclude=./output --exclude=./.git -cf - . | tar -C /comfyui -xf - \
 && grep -v -E '^(torch|torchvision|torchaudio)([<>=~ ].*)?$' requirements.txt > /tmp/req.txt \
 && (pip install --no-cache-dir -c /tmp/vz-runtime-constraints.txt -r /tmp/req.txt || uv pip install --system --no-cache -c /tmp/vz-runtime-constraints.txt -r /tmp/req.txt) \
 && rm -rf /tmp/cu && grep -q "class Flux3" /comfyui/comfy/supported_models.py && echo "ComfyUI upgraded to ${COMFY_SHA}"
# SAM 3.1（Meta，SAM License，可商用；ComfyUI 自带 SAM3_Detect 节点）：用于自动识别要换的衣服 / 皮肤区域（精准换装）
# 放在 /opt（/comfyui/models 在基础镜像里可能是数据卷，构建时写进去的文件运行时会丢），启动时由 vz-start.sh 链接过去
ADD https://huggingface.co/Comfy-Org/sam3.1/resolve/7bb8374780a725b4353ed31f3a9395c9742b5621/checkpoints/sam3.1_multiplex_fp16.safetensors /opt/vz-models/checkpoints/sam3.1_multiplex_fp16.safetensors
RUN ls -la /opt/vz-models/checkpoints/ && test -s /opt/vz-models/checkpoints/sam3.1_multiplex_fp16.safetensors && test -f /comfyui/comfy_extras/nodes_sam3.py
COPY vz-start.sh /vz-start.sh
RUN chmod +x /vz-start.sh
CMD ["/vz-start.sh"]


# Fixed-runtime rebuild: fail if original runtime versions or source drift.
RUN python /opt/vz-audit/verify_runtime.py /opt/vz-audit/expected-runtime.json
COPY inherited-files.sha256 /tmp/vz-inherited-files.sha256
RUN cd /comfyui && sha256sum -c /tmp/vz-inherited-files.sha256
RUN echo "9ba99c92703c2e8b4f47de2d34a539bb8e18923049e238b780d70dbe6368eb03  /opt/vz-models/checkpoints/sam3.1_multiplex_fp16.safetensors" | sha256sum -c -

# Only new mannequin nodes and one additional encoder below this line.
COPY vz_mannequin /comfyui/custom_nodes/vz_mannequin
RUN python -m py_compile /comfyui/custom_nodes/vz_mannequin/__init__.py
ADD https://huggingface.co/Comfy-Org/MiniMax-H3/resolve/54472221d27c695fca9621b0c3ed52f06c4af707/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors /opt/vz-models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
RUN echo "bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923  /opt/vz-models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors" | sha256sum -c -
LABEL org.vaziro.mannequin.version="vz-mannequin-2048-v1"
