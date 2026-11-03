"""wan-perf-lab: per-run attention override using ComfyUI's own registry (ComfyUI >= 0.34).
Only the model returned by this node uses the chosen attention; nothing global is patched."""
import comfy.ldm.modules.attention as A


class WanPerfAttentionOverride:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"model": ("MODEL",), "attention": (["sage", "pytorch"], {"default": "sage"})}}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "patch"
    CATEGORY = "wan-perf-lab"

    def patch(self, model, attention):
        fn = A.get_attention_function(attention, None)
        if fn is None:
            raise RuntimeError(f"attention '{attention}' is not available (is sageattention installed?)")
        m = model.clone()
        to = dict(m.model_options.get("transformer_options", {}))

        def override(func, *args, **kwargs):
            return fn(*args, **kwargs)

        to["optimized_attention_override"] = override
        m.model_options["transformer_options"] = to
        return (m,)


NODE_CLASS_MAPPINGS = {"WanPerfAttentionOverride": WanPerfAttentionOverride}
NODE_DISPLAY_NAME_MAPPINGS = {"WanPerfAttentionOverride": "Wan Perf Attention Override"}


class WanPerfFacingSelect:
    """For one window [start, start+length): if most frames show the person facing away
    (face keypoints not visible AND shoulders left/right swapped), use the back reference."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"pose_data": ("POSEDATA",), "front_image": ("IMAGE",), "back_image": ("IMAGE",),
                             "front_clip": ("CLIP_VISION_OUTPUT",), "back_clip": ("CLIP_VISION_OUTPUT",),
                             "start": ("INT", {"default": 0, "min": 0, "max": 100000}), "length": ("INT", {"default": 77, "min": 1, "max": 100000}),
                             "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0})}}

    RETURN_TYPES = ("IMAGE", "CLIP_VISION_OUTPUT")
    FUNCTION = "pick"
    CATEGORY = "wan-perf-lab"
    OUTPUT_NODE = True

    @staticmethod
    def facing_away(meta):
        """背对镜头 = 两个肩膀都检测清楚，且人的右肩出现在左肩的右边（画面坐标）。
        实测：这个姿态模型对着后脑勺也会给出高置信度的五官，所以不能用“看不到脸”来判断；肩膀左右互换最准。"""
        b = meta.get("keypoints_body") if isinstance(meta, dict) else None
        if b is None:
            return False
        b = [None if p is None else [float(x) for x in list(p)] for p in list(b)]   # 兼容 numpy 数组和列表
        if len(b) < 6 or b[2] is None or b[5] is None or len(b[2]) < 3 or len(b[5]) < 3:
            return False
        r, l = b[2], b[5]                                  # 右肩、左肩（x 为画面横坐标 0~1）
        return r[2] > 0.5 and l[2] > 0.5 and (r[0] - l[0]) > 0.05

    def pick(self, pose_data, front_image, back_image, front_clip, back_clip, start, length, threshold):
        metas = (pose_data or {}).get("pose_metas_original") if isinstance(pose_data, dict) else None
        metas = list(metas) if metas is not None else []
        seg = metas[start:start + length]
        away = sum(1 for m in seg if self.facing_away(m))
        ratio = away / len(seg) if seg else 0.0
        use_back = ratio > threshold
        info = f"frames {start}-{start + len(seg) - 1}: facing away {away}/{len(seg)} -> {'back' if use_back else 'front'}"
        print("[WanPerfFacingSelect] " + info, flush=True)
        if use_back:
            return {"ui": {"text": [info]}, "result": (back_image, back_clip)}
        return {"ui": {"text": [info]}, "result": (front_image, front_clip)}


NODE_CLASS_MAPPINGS["WanPerfFacingSelect"] = WanPerfFacingSelect
NODE_DISPLAY_NAME_MAPPINGS["WanPerfFacingSelect"] = "Wan Perf Facing Select (front/back reference)"
