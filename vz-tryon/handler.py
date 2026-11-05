# The real handler is provided by the base image (runpod/worker-comfyui: /handler.py),
# which calls runpod.serverless.start({"handler": handler}). This file only documents that
# and lets RunPod's repository scan find the entry point; it is not copied into the image.
import runpod  # noqa: F401

if __name__ == "__main__":
    from importlib import import_module
    runpod.serverless.start({"handler": import_module("handler").handler})
