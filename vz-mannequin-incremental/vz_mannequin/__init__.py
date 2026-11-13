"""Additive mannequin nodes. No patches to ComfyUI, old nodes, or global tokenizers.

Conditioning policy matches ComfyUI v0.45.3 MiniMaxH3ImageConditioning for
the single-image, explicit-2048 workflow approved in PF1--PF5.
"""
import copy
import hashlib
import json
import logging
from pathlib import Path
import struct
import zlib

import comfy.utils
import node_helpers
import nodes

VERSION = "vz-mannequin-2048-v1"
ENCODER = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"


def append_png_audit(path, audit):
    """Add one PNG text chunk without decoding or changing any pixel-data bytes.

    The inherited worker runs with --disable-metadata. Keep that global policy;
    only this new output node explicitly saves its own expansion audit.
    """
    raw = path.read_bytes()
    if not raw.startswith(b'\x89PNG\r\n\x1a\n') or raw[-12:] != b'\x00\x00\x00\x00IEND\xaeB`\x82':
        raise ValueError('Expected a complete PNG from SaveImage')
    payload = b'vz_mannequin\x00' + json.dumps(audit, ensure_ascii=True).encode('ascii')
    chunk = b'tEXt' + payload
    encoded = struct.pack('>I', len(payload)) + chunk + struct.pack('>I', zlib.crc32(chunk) & 0xffffffff)
    path.write_bytes(raw[:-12] + encoded + raw[-12:])


def short_edge_size(width, height, low, high):
    scale = min(max(min(width, height), low), high) / min(width, height)
    return tuple(max(32, round(side * scale / 32) * 32) for side in (width, height))


def resize_to(image, size):
    if (image.shape[2], image.shape[1]) == size:
        return image[..., :3]
    data = comfy.utils.common_upscale(image[..., :3].movedim(-1, 1), *size, "lanczos", "disabled")
    return data.movedim(1, -1)


def picture_tokens(clip, prompt, image):
    """Official image token presentation, built locally without changing a tokenizer."""
    tokenizer = clip.tokenizer
    if getattr(tokenizer, "clip", None) != "qwen3vl_32b":
        raise ValueError("VZ mannequin requires the approved MiniMax Qwen3-VL-32B encoder")
    underlying = getattr(tokenizer, tokenizer.clip)
    entries = []
    for text, vision in [("Picture 1: ", image), (prompt, None)]:
        if text:
            batches = underlying.tokenize_with_weights(text, return_word_ids=False, disable_weights=True)
            if len(batches) != 1:
                raise ValueError("MiniMax H3 text segment exceeds the supported prompt length")
            entries.extend(batches[0])
        if vision is not None:
            entries.extend([(151652, 1.0), (tokenizer._vision_entry(vision), 1.0), (151653, 1.0)])
    return {tokenizer.clip: [entries]}


class VZMannequinConditioningV1:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "clip": ("CLIP",), "vae": ("VAE",), "image": ("IMAGE",),
            "prompt": ("STRING", {"multiline": True}),
            "width": ("INT", {"default": 2048, "min": 2048, "max": 2048}),
            "height": ("INT", {"default": 2048, "min": 2048, "max": 2048}),
        }}

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "VAZIRO/mannequin"

    def encode(self, clip, vae, image, prompt, width, height):
        if (width, height) != (2048, 2048):
            raise ValueError("This release validates only 2048 x 2048 mannequin generation")
        if image.shape[0] != 1:
            raise ValueError("This release accepts one product image")
        size = (image.shape[2], image.shape[1])
        vision = resize_to(image[:1], short_edge_size(*size, 1024, 1024))
        reference = resize_to(image[:1], short_edge_size(*size, 1024, 2048))
        z = vae.encode(reference)
        refs = [{"kind": "image", "latent_h": z.shape[-2], "latent_w": z.shape[-1], "latent": z}]
        cond = clip.encode_from_tokens_scheduled(picture_tokens(clip, prompt, vision))
        return (node_helpers.conditioning_set_values(cond, {"minimax_refs": refs}),)


class VZMannequinSaveImageV1(nodes.SaveImage):
    """Output-only audit metadata. Does not alter pixels or old SaveImage nodes."""
    @classmethod
    def INPUT_TYPES(cls):
        types = copy.deepcopy(super().INPUT_TYPES())
        types["required"]["expansion"] = ("STRING", {"multiline": True})
        return types

    def save_images(self, images, filename_prefix="VZMannequin", expansion="", prompt=None, extra_pnginfo=None):
        extra = dict(extra_pnginfo or {})
        extra["vz_mannequin"] = {
            "version": VERSION,
            "actual_expansion": expansion,
            "expansion_sha256": hashlib.sha256(expansion.encode("utf-8")).hexdigest(),
            "conditioning_policy": "official-v0.45.3-single-reference",
            "encoder": ENCODER,
        }
        logging.info("[VZ mannequin] %s expansion_sha256=%s", VERSION, extra["vz_mannequin"]["expansion_sha256"])
        result = super().save_images(images, filename_prefix, prompt, extra)
        for item in result.get('ui', {}).get('images', []):
            output_root = Path(self.output_dir).resolve()
            path = (output_root / item.get('subfolder', '') / item['filename']).resolve()
            if not path.is_relative_to(output_root):
                raise ValueError('Audit output must be inside the ComfyUI output directory')
            append_png_audit(path, extra['vz_mannequin'])
        return result


NODE_CLASS_MAPPINGS = {
    "VZMannequinConditioningV1": VZMannequinConditioningV1,
    "VZMannequinSaveImageV1": VZMannequinSaveImageV1,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "VZMannequinConditioningV1": "VAZIRO mannequin conditioning v1",
    "VZMannequinSaveImageV1": "VAZIRO mannequin output v1",
}
