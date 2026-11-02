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
