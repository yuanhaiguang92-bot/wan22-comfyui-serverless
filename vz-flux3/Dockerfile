# TEST image: FLUX 3 Image Klein. Same official RunPod ComfyUI worker, with ComfyUI upgraded to a pinned
# master commit that includes FLUX 3 support (Flux3 model, flux3 text encoder, ReferenceMultiLatent).
# Weights come from the RunPod cached model "black-forest-labs/flux-3-image-klein-comfy" (not redistributed).
FROM runpod/worker-comfyui:5.10.0-base
ARG COMFY_SHA=fb2b26fdac507b7da81277c7becaf54c5e46ac6b
RUN set -eux; cd /tmp && git clone -q https://github.com/Comfy-Org/ComfyUI.git cu && cd cu && git checkout -q ${COMFY_SHA} \
 && rsync -a --exclude models --exclude custom_nodes --exclude user --exclude input --exclude output ./ /comfyui/ \
 && grep -v -E '^(torch|torchvision|torchaudio)([<>=~ ].*)?$' requirements.txt > /tmp/req.txt \
 && (pip install --no-cache-dir -r /tmp/req.txt || uv pip install --system --no-cache -r /tmp/req.txt) \
 && rm -rf /tmp/cu && grep -q "class Flux3" /comfyui/comfy/supported_models.py && echo "ComfyUI upgraded to ${COMFY_SHA}"
COPY vz-start.sh /vz-start.sh
RUN chmod +x /vz-start.sh
CMD ["/vz-start.sh"]
