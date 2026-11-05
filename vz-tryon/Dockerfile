# VAZIRO try-on: FLUX.2 [klein] 4B + FireRed-Image-Edit 1.1 on the official RunPod ComfyUI worker.
# Models are NOT baked in: they come from the RunPod cached model "yuanhaiguang/vz-tryon-models"
# and are symlinked into ComfyUI at start (vz-start.sh).
FROM runpod/worker-comfyui:5.10.0-base
COPY vz-start.sh /vz-start.sh
RUN chmod +x /vz-start.sh && python3 -c "import sys; print('python', sys.version)" && ls /comfyui/main.py
CMD ["/vz-start.sh"]
