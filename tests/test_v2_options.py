import importlib.util, json, sys, types, unittest, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
for m in ("boto3", "runpod", "websocket", "official_handler", "requests"):   # 测试时用空模块代替运行环境里的依赖
    if m not in sys.modules:
        mod = types.ModuleType(m); mod.serverless = types.SimpleNamespace(start=lambda *a, **k: None); sys.modules[m] = mod
try:
    import PIL  # noqa
except ImportError:
    pil = types.ModuleType("PIL"); pil.Image = types.SimpleNamespace(); sys.modules["PIL"] = pil
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    m.WORKFLOW_FILE = ROOT / "wan22_workflow.json"; return m
H = load(ROOT / "handler.py", "h_new")
ORIG = pathlib.Path("/tmp/wan/handler_orig.py")

def links_ok(wf):
    bad = [(k, a, v[0]) for k, n in wf.items() for a, v in n["inputs"].items() if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and v[0] not in wf]
    return bad

class T(unittest.TestCase):
    def test_default_identical_to_original(self):
        if not ORIG.exists(): self.skipTest("no original")
        O = load(ORIG, "h_orig")
        for seed in (None, 123, -1):
            if seed == -1: continue   # 随机种子两边不同，跳过
            a = json.dumps(O._prepare_workflow("i.png", "v.mp4", "tok", seed), sort_keys=True)
            b = json.dumps(H._prepare_workflow("i.png", "v.mp4", "tok", seed), sort_keys=True)
            self.assertEqual(a, b)
            b2 = json.dumps(H._prepare_workflow("i.png", "v.mp4", "tok", seed, opts={}, total_frames=None), sort_keys=True)
            self.assertEqual(a, b2)
    def test_clean_opts_default_empty(self):
        self.assertEqual(H._clean_opts({"image_url": "x", "video_url": "y", "seed": 1}), {})
    def test_options_applied(self):
        o = H._clean_opts({"width": 720, "height": 960, "prompt": "女模特展示服装", "steps": 4, "relight": False, "mode": "animate", "force_rate": 24, "skip_debug_outputs": True})
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=o)
        self.assertEqual((wf["159"]["inputs"]["value"], wf["160"]["inputs"]["value"]), (720, 960))
        self.assertEqual(wf["376"]["inputs"]["text"], "女模特展示服装")
        self.assertEqual(wf["382"]["inputs"]["steps"], 4)
        self.assertNotIn("350", wf); self.assertEqual(wf["377"]["inputs"]["model"], ["378", 0])
        self.assertNotIn("background_video", wf["381"]["inputs"]); self.assertNotIn("character_mask", wf["381"]["inputs"])
        self.assertEqual(wf["301"]["inputs"]["force_rate"], 24); self.assertEqual(wf["385"]["inputs"]["fps"], 24)
        for k in H.DEBUG_NODES: self.assertNotIn(k, wf)
        self.assertIn("19", wf); self.assertEqual(links_ok(wf), [])
    def test_replace_mode_keeps_mask(self):
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=H._clean_opts({"mode": "replace", "skip_debug_outputs": True}))
        self.assertIn("background_video", wf["381"]["inputs"]); self.assertEqual(links_ok(wf), [])
    def test_window_chain(self):
        o = H._clean_opts({"window_frames": 77, "skip_debug_outputs": True})
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=o, total_frames=300)
        animate = [k for k, n in wf.items() if n["class_type"] == "WanAnimateToVideo"]
        self.assertEqual(len(animate), 5)                         # 1 + ceil((300-77)/(77-5)) = 5
        self.assertEqual(wf["381"]["inputs"]["length"], 77)
        self.assertEqual(wf["899"]["inputs"]["length"], 300); self.assertEqual(wf["385"]["inputs"]["images"], ["899", 0])
        for k in animate[1:]:
            self.assertEqual(wf[k]["inputs"]["video_frame_offset"][1], 5); self.assertIn("continue_motion", wf[k]["inputs"])
        self.assertEqual(links_ok(wf), [])
    def test_window_not_needed_for_short(self):
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=H._clean_opts({"window_frames": 77}), total_frames=60)
        self.assertNotIn("899", wf); self.assertEqual(wf["381"]["inputs"]["length"], ["301", 1])
    def test_sage_and_mask(self):
        o = H._clean_opts({"sage_attention": True, "mask_expand": 24, "window_frames": 77, "skip_debug_outputs": True})
        self.assertEqual(o["sage_attention"], "sage")
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=o, total_frames=200)
        self.assertEqual(wf["880"]["class_type"], "WanPerfAttentionOverride"); self.assertEqual(wf["880"]["inputs"]["model"], ["377", 0])
        ks = [k for k, n in wf.items() if n["class_type"] == "KSampler"]
        self.assertTrue(len(ks) >= 2 and all(wf[k]["inputs"]["model"] == ["880", 0] for k in ks))   # 续接的每一段都用加速
        self.assertEqual(wf["370"]["inputs"]["expand"], 24); self.assertEqual(links_ok(wf), [])
        self.assertNotIn("sage_attention", H._clean_opts({"sage_attention": False}))
        o2 = H._clean_opts({"sage_attention": True, "relight": False})
        wf2 = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=o2); self.assertEqual(wf2["880"]["inputs"]["model"], ["377", 0]); self.assertEqual(links_ok(wf2), [])
    def test_load_resize(self):
        o = H._clean_opts({"width": 400, "height": 720})
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=o, src_size=(1080, 1920))
        self.assertEqual((wf["301"]["inputs"]["custom_width"], wf["301"]["inputs"]["custom_height"]), (408, 720))
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=H._clean_opts({"width": 720, "height": 960}), src_size=(1080, 1920))
        cw, ch = wf["301"]["inputs"]["custom_width"], wf["301"]["inputs"]["custom_height"]
        self.assertTrue(cw >= 720 and ch >= 960 and abs(cw / ch - 1080 / 1920) < 0.02, (cw, ch))
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=H._clean_opts({"width": 400, "height": 720}), src_size=(360, 640))
        self.assertEqual((wf["301"]["inputs"]["custom_width"], wf["301"]["inputs"]["custom_height"]), (0, 0))   # 原视频更小：不缩放
        wf = H._prepare_workflow("i.png", "v.mp4", "tok", 1, opts=H._clean_opts({"steps": 4}), src_size=(1080, 1920))
        self.assertEqual(wf["301"]["inputs"]["custom_width"], 0)                                                 # 没指定尺寸：不动
    def test_invalid(self):
        for bad in ({"width": 500}, {"mode": "x"}, {"window_frames": 80}, {"steps": 99}, {"force_rate": 2}, {"sage_attention": "evil"}, {"mask_expand": 999}):
            with self.assertRaises(ValueError): H._clean_opts(bad)
if __name__ == "__main__":
    unittest.main()
