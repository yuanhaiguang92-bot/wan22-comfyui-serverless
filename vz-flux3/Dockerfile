# TEST image: FLUX 3 Image Klein. Same official RunPod ComfyUI worker, with ComfyUI upgraded to a pinned
# master commit that includes FLUX 3 support (Flux3 model, flux3 text encoder, ReferenceMultiLatent).
# Weights come from the RunPod cached model "black-forest-labs/flux-3-image-klein-comfy" (not redistributed).
FROM runpod/worker-comfyui:5.10.0-base
ARG COMFY_SHA=fb2b26fdac507b7da81277c7becaf54c5e46ac6b
RUN set -eux; cd /tmp && git clone -q https://github.com/Comfy-Org/ComfyUI.git cu && cd cu && git checkout -q ${COMFY_SHA} \
 && tar -C /tmp/cu --exclude=./models --exclude=./custom_nodes --exclude=./user --exclude=./input --exclude=./output --exclude=./.git -cf - . | tar -C /comfyui -xf - \
 && grep -v -E '^(torch|torchvision|torchaudio)([<>=~ ].*)?$' requirements.txt > /tmp/req.txt \
 && (pip install --no-cache-dir -r /tmp/req.txt || uv pip install --system --no-cache -r /tmp/req.txt) \
 && rm -rf /tmp/cu && grep -q "class Flux3" /comfyui/comfy/supported_models.py && echo "ComfyUI upgraded to ${COMFY_SHA}"
# SAM 3.1（Meta，SAM License，可商用；ComfyUI 自带 SAM3_Detect 节点）：用于自动识别要换的衣服 / 皮肤区域（精准换装）
# 放在 /opt（/comfyui/models 在基础镜像里可能是数据卷，构建时写进去的文件运行时会丢），启动时由 vz-start.sh 链接过去
ADD https://huggingface.co/Comfy-Org/sam3.1/resolve/main/checkpoints/sam3.1_multiplex_fp16.safetensors /opt/vz-models/checkpoints/sam3.1_multiplex_fp16.safetensors
RUN ls -la /opt/vz-models/checkpoints/ && test -s /opt/vz-models/checkpoints/sam3.1_multiplex_fp16.safetensors && test -f /comfyui/comfy_extras/nodes_sam3.py
# vz-h3lab（临时测试）：RefMod（参考图强度调节）+ Dials（方向旋钮），都不用训练；固定版本
RUN set -eux; cd /comfyui/custom_nodes \
 && git clone -q https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod && git -C ComfyUI-MiniMaxH3Mod checkout -q 517e8c4 \
 && git clone -q https://github.com/matlowai/ComfyUI-Dials && git -C ComfyUI-Dials checkout -q 9b55d62 \
 && ls /comfyui/custom_nodes
COPY vz-start.sh /vz-start.sh
RUN chmod +x /vz-start.sh
CMD ["/vz-start.sh"]
