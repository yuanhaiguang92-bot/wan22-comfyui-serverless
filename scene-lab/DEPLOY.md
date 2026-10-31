# Isolated WAN22 Scene Lab v0.1.2
Branch: wan22-scene-lab-v0.1.2
RunPod repository build: Dockerfile /scene-lab/Dockerfile.lab ; build context /scene-lab.
New endpoint only. Preserve production main and all existing endpoints.
Active Workers 0, Max Workers 1. No Network Volume. Keep existing Hugging Face Cached Model revision.
Image inference gate defaults OFF. Deployment may allocate a GPU even without an inference request, so do not create endpoint until explicit budget authorization.
No selected user image, original video, credentials, or live account snapshots are included in this branch.
Local app: python server.py --port 8172 from scene-lab directory. Install requirements-lab.txt and ffprobe first.
Current test: person_scene_combined uses original driving video plus one composed character/scene reference.
Native conditioning changes only. Product/camera fidelity and long-video continuity are not GPU validated.
Long-video execution is not implemented; current worker rejects >15 seconds or >401 frames.
Default paid switches remain OFF.
