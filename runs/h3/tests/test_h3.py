"""
h3 包单元测试（纯标准库 unittest，无网络依赖）。

运行方式（在项目根目录）：
  python -m unittest discover -s runs/h3/tests -p "test_*.py" -v
"""
import atexit
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # runs/

# 测试临时目录优先放到工作区内；若沙箱不允许（某些受限环境），
# 文件写入类测试自动跳过，纯逻辑测试仍可运行。
_TEST_TMP = Path(__file__).resolve().parent / ".test_tmp"
_WRITES_OK = True
try:
    _TEST_TMP.mkdir(exist_ok=True)
    tempfile.tempdir = str(_TEST_TMP)
except OSError:
    _WRITES_OK = False
    tempfile.tempdir = None


@atexit.register
def _cleanup_test_tmp():
    if _WRITES_OK:
        shutil.rmtree(_TEST_TMP, ignore_errors=True)


needs_fs = unittest.skipUnless(_WRITES_OK, "沙箱不允许子进程写文件，跳过文件类测试")


from h3 import comfy, jobstate, params, prompts, stage, templates, workflow  # noqa: E402


# ---------------------------------------------------------------------------
# 帧数/分辨率（极限与网格约束）
# ---------------------------------------------------------------------------
class TestSnapLength(unittest.TestCase):
    def check_grid(self, seconds):
        n = workflow.snap_length(seconds)
        self.assertGreaterEqual(n, 5)
        self.assertEqual((n - 5) % 17, 0, f"seconds={seconds} -> {n}")

    def test_any_input_lands_on_grid(self):
        for s in (0.1, 0.5, 1, 2.7, 5, 5.01, 9.9, 15, 23.3, 59.9):
            self.check_grid(s)

    def test_extremes(self):
        self.assertEqual(workflow.snap_length(5.0, 24.0), 124)  # 120 -> +4
        self.assertGreaterEqual(workflow.snap_length(0.01, 24.0), 5)
        self.assertLessEqual(workflow.snap_length(1000, 24.0), 1000 * 24 + 16)

    def test_fps_variants(self):
        n30 = workflow.snap_length(1.5, 30.0)
        n24 = workflow.snap_length(1.5, 24.0)
        self.assertGreater(n30, n24)


class TestResolutionPresets(unittest.TestCase):
    def test_all_presets_valid_and_multiple_of_8(self):
        self.assertIn("480p", workflow.RESOLUTION_PRESETS)
        for name, (w, h) in workflow.RESOLUTION_PRESETS.items():
            self.assertEqual(w % 8, 0)
            self.assertEqual(h % 8, 0)
            self.assertLess(w, 4096)
            self.assertLess(h, 4096)


# ---------------------------------------------------------------------------
# 参数文件解析（BOM/CRLF/大小写/未知键/越界）
# ---------------------------------------------------------------------------
@needs_fs
class TestKeyValueParsing(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def write(self, text):
        p = self.dir / "video.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_bom_crlf_comments_and_case(self):
        content = ("\ufeff# 注释行\r\n"
                   "; 分号注释\r\n"
                   "RESOLUTION=720p\r\n"
                   "Seconds =  7 \r\n"
                   "\r\n"
                   "seed=auto\r\n")
        raw = params.parse_keyvalue_file(self.write(content))
        self.assertEqual(raw["resolution"], "720p")
        self.assertEqual(raw["seconds"], "7")
        self.assertEqual(raw["seed"], "auto")
        self.assertNotIn("comment", raw)

    def test_missing_file_returns_empty(self):
        self.assertEqual(params.parse_keyvalue_file(self.dir / "nope.txt"), {})

    def test_unknown_keys_preserved_in_raw(self):
        raw = params.parse_keyvalue_file(self.write("future_feature=42\nresolution=480p\n"))
        self.assertEqual(raw["future_feature"], "42")


class TestResolveParams(unittest.TestCase):
    def test_defaults_when_file_minimal(self):
        gp = params.resolve_params({"resolution": "480p", "seconds": "5"})
        self.assertEqual((gp.width, gp.height), (864, 480))
        self.assertEqual(gp.steps, workflow.DEFAULT_STEPS)
        self.assertEqual(gp.fps, workflow.DEFAULT_FPS)
        self.assertEqual(gp.length, workflow.snap_length(5.0))
        self.assertIsInstance(gp.seed, int)

    def test_unknown_resolution_raises(self):
        with self.assertRaises(params.ParamError):
            params.resolve_params({"resolution": "8k", "seconds": "5"})

    def test_bad_seconds_raises(self):
        with self.assertRaises(params.ParamError):
            params.resolve_params({"resolution": "480p", "seconds": "abc"})
        with self.assertRaises(params.ParamError):
            params.resolve_params({"resolution": "480p", "seconds": "0"})

    def test_width_height_require_multiple_of_8(self):
        with self.assertRaises(params.ParamError):
            params.resolve_params({"resolution": "480p", "seconds": "5",
                                   "width": "100", "height": "480"})

    def test_cli_override_wins(self):
        gp = params.resolve_params(
            {"resolution": "480p", "seconds": "5"},
            cli_overrides={"resolution": "768p", "seconds": "8"},
        )
        self.assertEqual((gp.width, gp.height), (1344, 768))
        self.assertEqual(gp.seconds, 8.0)

    def test_seed_auto_is_random_int(self):
        gp = params.resolve_params({"resolution": "480p", "seconds": "5", "seed": "auto"})
        self.assertIsInstance(gp.seed, int)
        self.assertTrue(0 <= gp.seed < 2**31)

    def test_timeout_bounds(self):
        with self.assertRaises(params.ParamError):
            params.resolve_params({"resolution": "480p", "seconds": "5", "timeout": "10"})


# ---------------------------------------------------------------------------
# 工作流构建 / UI 转换 / 保存
# ---------------------------------------------------------------------------
class TestWorkflowBuild(unittest.TestCase):
    def test_graph_shape_and_negative_optional(self):
        wf = workflow.build_workflow("cat", 864, 480, 124, 1, negative_prompt="")
        self.assertEqual(len(wf), 14)
        self.assertNotIn("negative_prompt", wf["5"]["inputs"])
        self.assertEqual(wf["8"]["inputs"]["steps"], workflow.DEFAULT_STEPS)
        self.assertEqual(wf["13"]["inputs"]["fps"], workflow.DEFAULT_FPS)

    def test_negative_and_custom_params(self):
        wf = workflow.build_workflow("cat", 864, 480, 124, 7,
                                     negative_prompt="ugly", steps=30, fps=12.0)
        self.assertEqual(wf["5"]["inputs"]["negative_prompt"], "ugly")
        self.assertEqual(wf["8"]["inputs"]["steps"], 30)
        self.assertEqual(wf["13"]["inputs"]["fps"], 12.0)

    def test_ui_conversion_has_links_and_all_nodes(self):
        wf = workflow.build_workflow("cat", 864, 480, 124, 1)
        ui = workflow.workflow_to_ui(wf)
        self.assertEqual(len(ui["nodes"]), len(wf))
        # 所有 API 连接都应转换为 link
        api_links = sum(
            1 for node in wf.values()
            for v in node["inputs"].values()
            if isinstance(v, list)
        )
        self.assertEqual(len(ui["links"]), api_links)

    @needs_fs
    def test_save_pair_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            wf = workflow.build_workflow("cat", 864, 480, 124, 1)
            api = workflow.save_workflow_api(wf, folder / "workflow_api.json")
            ui = workflow.save_workflow_ui(wf, folder / "workflow_ui.json")
            self.assertTrue(api.exists())
            self.assertTrue(ui is not None and ui.exists())
            self.assertEqual(json.loads(api.read_text(encoding="utf-8")), wf)

    def test_task_folder_name_has_ms_and_unique(self):
        import datetime

        a = workflow.make_task_folder_name(
            datetime.datetime(2026, 9, 2, 13, 41, 21, 123000)
        )
        b = workflow.make_task_folder_name(
            datetime.datetime(2026, 9, 2, 13, 41, 21, 456000)
        )
        self.assertNotEqual(a, b)
        self.assertRegex(a, r"^h3_\d{8}_\d{6}_\d{3}$")


class TestUiLitegraphFormat(unittest.TestCase):
    """workflow_ui.json 必须包含标准 LiteGraph 连线信息（links 数组 + 引用）。"""

    @classmethod
    def setUpClass(cls):
        cls.wf = workflow.build_workflow("cat", 864, 480, 124, 1, negative_prompt="ugly")
        cls.ui = workflow.workflow_to_ui(cls.wf)

    def test_links_are_litegraph_arrays(self):
        for link in self.ui["links"]:
            self.assertIsInstance(link, list)
            self.assertEqual(len(link), 6)
            lid, oid, oslot, tid, tslot, typ = link
            self.assertIsInstance(lid, int)
            self.assertIsInstance(oid, int)
            self.assertIsInstance(oslot, int)
            self.assertIsInstance(tid, int)
            self.assertIsInstance(tslot, int)
            self.assertEqual(typ, "*")

    def test_link_ids_contiguous(self):
        self.assertEqual([l[0] for l in self.ui["links"]],
                         list(range(1, len(self.ui["links"]) + 1)))

    def test_every_input_connection_has_matching_link(self):
        by_id = {n["id"]: n for n in self.ui["nodes"]}
        for lid, oid, oslot, tid, tslot, _ in self.ui["links"]:
            target = by_id[tid]
            self.assertLess(tslot, len(target["inputs"]))
            self.assertEqual(target["inputs"][tslot]["link"], lid)
            origin = by_id[oid]
            self.assertLess(oslot, len(origin["outputs"]))
            self.assertIn(lid, origin["outputs"][oslot]["links"])

    def test_output_arities(self):
        by_type = {n["id"]: n["type"] for n in self.ui["nodes"]}
        node5 = next(n for n in self.ui["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
        self.assertEqual(len(node5["outputs"]), 2)   # conditioning(0) + latent(1)
        save = next(n for n in self.ui["nodes"] if n["type"] == "SaveVideo")
        self.assertEqual(len(save["outputs"]), 0)

    def test_widgets_exclude_connected_values(self):
        for node in self.ui["nodes"]:
            wf_node = self.wf[str(node["id"])]
            n_widgets = sum(
                1 for v in wf_node["inputs"].values()
                if not (isinstance(v, list) and len(v) == 2)
            )
            self.assertEqual(len(node["widgets_values"]), n_widgets)


class TestComboNormalize(unittest.TestCase):
    """uiapi COMBO widget 值规范化（空串/陈旧值 → 枚举内合法值）。"""

    def test_legacy_options_list_format(self):
        from h3 import uiapi
        spec = [["match", "max"], {"default": "match"}]
        opts = uiapi._combo_options_of(spec, spec[1])
        self.assertEqual(opts, ["match", "max"])
        self.assertEqual(uiapi._normalize_combo(opts, spec[1], ""), "match")
        self.assertEqual(uiapi._normalize_combo(opts, spec[1], "max"), "max")

    def test_combo_type_with_options_in_cfg(self):
        # 新版 spec：["COMBO", {"options": [...], "default": "match"}]
        from h3 import uiapi
        cfg = {"options": ["match", "max"], "default": "match"}
        spec = ["COMBO", cfg]
        opts = uiapi._combo_options_of(spec, cfg)
        self.assertEqual(opts, ["match", "max"])
        self.assertEqual(uiapi._normalize_combo(opts, cfg, ""), "match")
        self.assertEqual(uiapi._normalize_combo(opts, cfg, "bogus"), "match")

    def test_invalid_value_falls_back_to_first_option(self):
        from h3 import uiapi
        cfg = {"options": ["match", "max"]}  # 无 default
        opts = uiapi._combo_options_of(["COMBO", cfg], cfg)
        self.assertEqual(uiapi._normalize_combo(opts, cfg, "bogus"), "match")
        self.assertEqual(uiapi._normalize_combo(opts, cfg, "max"), "max")

    def test_non_combo_spec_returns_none(self):
        from h3 import uiapi
        self.assertIsNone(uiapi._combo_options_of(["INT", {}], {}))
        self.assertIsNone(uiapi._combo_options_of(["IMAGE", {}], {}))


class TestIdea2PromptsHttp(unittest.TestCase):
    """idea2prompts.chat_once：api_key 为空时不发 Authorization（spark 本地 vLLM/Ollama）。"""

    def _fake_resp(self):
        data = json.dumps({"choices": [{"message": {"content": '{"positive": "x", "negative": ""}'}}]}).encode("utf-8")
        resp = mock.Mock()
        resp.read.return_value = data
        resp.__enter__ = mock.Mock(return_value=resp)
        resp.__exit__ = mock.Mock(return_value=False)
        return resp

    def test_no_auth_header_when_key_empty(self):
        from h3 import idea2prompts
        cfg = {"kind": "openai_compatible", "base_url": "http://127.0.0.1:8000/v1",
               "api_key": "", "model": "Qwen/Qwen3-8B", "temperature": 0.7, "timeout": 30}
        with mock.patch("urllib.request.urlopen", return_value=self._fake_resp()) as m:
            out = idea2prompts.chat_once(cfg, [{"role": "user", "content": "hi"}])
        self.assertEqual(out, '{"positive": "x", "negative": ""}')
        req = m.call_args[0][0]
        self.assertNotIn("Authorization", req.headers)
        self.assertTrue(req.full_url.endswith("/v1/chat/completions"))

    def test_auth_header_when_key_present(self):
        from h3 import idea2prompts
        cfg = {"kind": "openai_compatible", "base_url": "http://127.0.0.1:8000/v1",
               "api_key": "sk-local-1", "model": "Qwen/Qwen3-27B", "temperature": 0.7, "timeout": 30}
        with mock.patch("urllib.request.urlopen", return_value=self._fake_resp()) as m:
            idea2prompts.chat_once(cfg, [{"role": "user", "content": "hi"}])
        req = m.call_args[0][0]
        self.assertEqual(req.headers.get("Authorization"), "Bearer sk-local-1")

    def test_max_tokens_in_payload_when_configured(self):
        import json as _json
        from h3 import idea2prompts
        cfg = {"kind": "openai_compatible", "base_url": "http://127.0.0.1:8000/v1",
               "api_key": "", "model": "Qwen3.8-27B", "temperature": 0.7, "timeout": 30,
               "max_tokens": 1500}
        with mock.patch("urllib.request.urlopen", return_value=self._fake_resp()) as m:
            idea2prompts.chat_once(cfg, [{"role": "user", "content": "hi"}])
        body = _json.loads(m.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(body["max_tokens"], 1500)


class TestSubgraphFlatten(unittest.TestCase):
    """UUID 子图解组：基于真实 remote_workflows 模板（离线，无需 client）。"""

    RUNS = Path(__file__).resolve().parent.parent.parent
    ROOT = RUNS.parent
    MIRROR = ROOT / "workflows" / "remote_workflows"

    def _load(self, name):
        import json as _json
        return _json.loads((self.MIRROR / name).read_text(encoding="utf-8-sig"))

    def _flat(self, name):
        from h3 import subgraph
        return subgraph.flatten_subgraphs(self._load(name))

    def test_t2v_flatten_shape(self):
        from h3 import subgraph
        ui = self._load("video_minimax_h3_t2v.json")
        self.assertTrue(subgraph.collect_subgraph_ids(ui))  # 确有子图
        flat = subgraph.flatten_subgraphs(ui)
        self.assertNotEqual(flat, ui)
        self.assertTrue(flat.get("_flattened_subgraphs"))
        by_id = {int(n["id"]): n for n in flat["nodes"]}
        # 无 UUID 残留、无悬空连线
        self.assertFalse([n for n in flat["nodes"]
                          if len(str(n["type"])) == 36 and "-" in str(n["type"])])
        for l in flat["links"]:
            self.assertIn(int(l[1]), by_id)
            self.assertIn(int(l[3]), by_id)
        # 内部真实节点已搬入
        mini = next(n for n in flat["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
        self.assertIn("SaveVideo", {n["type"] for n in flat["nodes"]})

    def test_no_subgraph_returns_same_object(self):
        from h3 import subgraph
        ui = self._load("video_minimax_h3_r2v.json")  # 开放图无子图
        self.assertEqual(subgraph.flatten_subgraphs(ui), ui)

    def test_i2v_first_frame_wired_and_prompt_injected(self):
        flat = self._flat("video_minimax_h3_i2v.json")
        mini = next(n for n in flat["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
        ins = {i["name"]: i for i in mini["inputs"]}
        load = next(n for n in flat["nodes"] if n["type"] == "LoadImage")
        # 首帧来自顶层 LoadImage（默认图名是用户可改内容，这里不断言具体文件名）
        self.assertIsNotNone(ins["first_frame"]["link"])
        self.assertTrue(str(load["widgets_values"][0]).endswith(".png"))
        # prompt 注入为 UUID 节点 widgets_values[0]
        uuid_node = next(n for n in self._load("video_minimax_h3_i2v.json")["nodes"]
                         if len(str(n["type"])) == 36)
        self.assertEqual(mini["widgets_values"][0], uuid_node["widgets_values"][0])
        # width/height 仍由 ResolutionSelector 提供（顶层连线优先于陈旧 widget 值）
        wlink = ins["width"]["link"]
        src = next(l for l in flat["links"] if l[0] == wlink)[1]
        src_node = next(n for n in flat["nodes"] if int(n["id"]) == src)
        self.assertEqual(src_node["type"], "ResolutionSelector")

    def test_t2v_prompt_injected_no_images(self):
        flat = self._flat("video_minimax_h3_t2v.json")
        mini = next(n for n in flat["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
        ins = {i["name"]: i for i in mini["inputs"]}
        self.assertIsNone(ins["first_frame"]["link"])
        self.assertIsNone(ins["last_frame"]["link"])
        uuid_node = next(n for n in self._load("video_minimax_h3_t2v.json")["nodes"]
                         if len(str(n["type"])) == 36)
        self.assertEqual(mini["widgets_values"][0], uuid_node["widgets_values"][0])
        # duration 注入 PrimitiveFloat
        pf = next(n for n in flat["nodes"] if n["type"] == "PrimitiveFloat")
        self.assertEqual(pf["widgets_values"][0], 5)


    def test_flf2v_dual_frame_wiring(self):
        from h3 import subgraph
        ui = self._load("video_minimax_h3_flf2v.json")
        flat = subgraph.flatten_subgraphs(ui)
        mini = next(n for n in flat["nodes"] if n["type"] == "MiniMaxH3ImageToVideo")
        ins = {i["name"]: i for i in mini["inputs"]}
        by_id = {int(n["id"]): n for n in flat["nodes"]}
        imgs = {}
        for k in ("first_frame", "last_frame"):
            lk = ins[k]["link"]
            self.assertIsNotNone(lk, k)
            src_id = next(l for l in flat["links"] if l[0] == lk)[1]
            src = by_id[src_id]
            self.assertEqual(src["type"], "LoadImage")
            imgs[k] = src["widgets_values"][0]
        # 默认图名是用户可改内容：不断言具体文件名，只要求两端为不同图片（首帧≠末帧）
        self.assertTrue(str(imgs["first_frame"]).endswith(".png"))
        self.assertTrue(str(imgs["last_frame"]).endswith(".png"))
        self.assertNotEqual(imgs["first_frame"], imgs["last_frame"])
        for l in flat["links"]:  # 无悬空
            self.assertIn(int(l[1]), by_id)
            self.assertIn(int(l[3]), by_id)


class TestPruneDeadNodes(unittest.TestCase):
    """uiapi.prune_dead_output_nodes：清理无人消费且非输出类的死链节点。"""

    def test_dead_chain_removed_output_kept(self):
        from h3 import uiapi
        api = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "2": {"class_type": "ImageScaleToTotalPixels", "inputs": {}},  # 缺输入
            "3": {"class_type": "GetImageSize", "inputs": {"image": ["2", 0]}},
            "4": {"class_type": "SaveVideo", "inputs": {"video": ["9", 0]}},
        }
        out = uiapi.prune_dead_output_nodes(dict(api))
        # 死链 2→3 整条清除；1 只为死链供图也被清；4 为文件输出类保留
        self.assertNotIn("1", out)
        self.assertNotIn("2", out)
        self.assertNotIn("3", out)
        self.assertIn("4", out)

    def test_consumed_nodes_kept(self):
        from h3 import uiapi
        api = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "2": {"class_type": "MiniMax", "inputs": {"image": ["1", 0]}},
            "3": {"class_type": "SaveVideo", "inputs": {"video": ["2", 0]}},
        }
        out = uiapi.prune_dead_output_nodes(dict(api))
        self.assertEqual(set(out.keys()), {"1", "2", "3"})


class TestRunLog(unittest.TestCase):
    """h3_submit 运行日志：无 H3_LOG_FILE 注入时自动建 logs\\run_*.log，有则沿用。"""

    def setUp(self):
        self._old = os.environ.get("H3_LOG_FILE")
        os.environ.pop("H3_LOG_FILE", None)
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("H3_LOG_FILE", None)
        else:
            os.environ["H3_LOG_FILE"] = self._old
        self._td.cleanup()

    def test_auto_creates_run_log(self):
        import h3_submit
        path, created = h3_submit._ensure_run_log(self.dir)
        self.assertTrue(created)
        p = Path(path)
        self.assertEqual(p.parent.name, "logs")
        self.assertTrue(p.name.startswith("run_") and p.name.endswith(".log"))
        self.assertIn("run start", p.read_text(encoding="utf-8"))
        # 二次调用沿用同一文件
        path2, created2 = h3_submit._ensure_run_log(self.dir)
        self.assertEqual(path2, path)
        self.assertFalse(created2)

    def test_env_injected_log_reused(self):
        import h3_submit
        f = self.dir / "injected.log"
        f.write_text("", encoding="utf-8")
        os.environ["H3_LOG_FILE"] = str(f)
        path, created = h3_submit._ensure_run_log(self.dir)
        self.assertFalse(created)
        self.assertEqual(Path(path), f)

    def test_log_event_writes_py_prefix(self):
        import h3_submit
        f = self.dir / "e.log"
        f.write_text("", encoding="utf-8")
        os.environ["H3_LOG_FILE"] = str(f)
        h3_submit._log_event("hello 事件")
        self.assertIn("py: hello 事件", f.read_text(encoding="utf-8"))

    def test_err_writes_log_too(self):
        """回归：提前退出路径(断点拦截/参数错/拒绝)只 _err 不落日志，
        会留下只有 run start 两行的“粗略日志”。_err 必须同步写日志。"""
        import h3_submit
        f = self.dir / "err.log"
        f.write_text("", encoding="utf-8")
        os.environ["H3_LOG_FILE"] = str(f)
        h3_submit._err("检测到上次任务尚未完成（断点存在）")
        text = f.read_text(encoding="utf-8")
        self.assertIn("py: err 检测到上次任务尚未完成", text)

    def test_adopt_task_log_merges_and_switches(self):
        import json as _json
        import h3_submit
        # 本次会话自举的新日志（孤儿）
        new_log, created = h3_submit._ensure_run_log(self.dir)
        self.assertTrue(created)
        h3_submit._log_event("start argv=--resume x")
        # 原任务日志（job.json 里记录过）
        logs_dir = self.dir / "logs"
        orig = logs_dir / "run_oldtask.log"
        orig.write_text("[old] === 原任务 start ===\n", encoding="utf-8")
        task_dir = self.dir / "workflows" / "h3_oldtask"
        task_dir.mkdir(parents=True)
        (task_dir / "job.json").write_text(
            _json.dumps({"log_file": "run_oldtask.log"}), encoding="utf-8")
        # 续传采用原日志：孤儿并入后被删，env 切到原日志
        h3_submit._adopt_task_log(self.dir, task_dir)
        self.assertFalse(Path(new_log).exists())
        self.assertEqual(os.environ.get("H3_LOG_FILE"), str(orig))
        h3_submit._log_event("completed ok")
        text = orig.read_text(encoding="utf-8")
        self.assertIn("completed ok", text)
        self.assertIn("start argv=", text)  # 本次会话起始行已并入


class TestCapabilities(unittest.TestCase):
    """能力注册表 config/capabilities.json：加载/查询/LLM digest/文档生成。"""

    RUNS = Path(__file__).resolve().parent.parent.parent
    ROOT = RUNS.parent

    def test_load_and_workflow_lookup(self):
        from h3 import capabilities
        cap = capabilities.load_capabilities(self.ROOT)
        self.assertTrue(cap.get("workflows"))
        self.assertTrue(cap.get("tools"))
        w = capabilities.workflow_by_id(cap, "video_r2v")
        self.assertIsNotNone(w)
        self.assertEqual(w.get("engine"), "local")
        self.assertEqual(w.get("slot"), "video_r2v")
        self.assertIsNone(capabilities.workflow_by_id(cap, "no_such"))

    def test_llm_digest_is_compact_and_informative(self):
        from h3 import capabilities
        cap = capabilities.load_capabilities(self.ROOT)
        d = capabilities.llm_digest(cap)
        self.assertIn("video_r2v", d)
        self.assertIn("h3_submit.py --stage", d)
        self.assertIn("h3_text2img_flux.py", d)
        self.assertIn("prompt_blueprints.json", d)
        self.assertLess(len(d), 1200)  # 小模型友好：保持精简

    def test_markdown_doc_generates_table(self):
        from h3 import capabilities
        cap = capabilities.load_capabilities(self.ROOT)
        md = capabilities.markdown_doc(cap)
        self.assertIn("| id |", md)
        for wid in ("video_t2v", "video_i2v", "video_r2v", "video_flf2v"):
            self.assertIn(wid, md)


class TestDeploy(unittest.TestCase):
    """运行形态 deploy.json：读取/校验/切换 + llm.json base_url 同步。"""

    RUNS = Path(__file__).resolve().parent.parent.parent
    ROOT = RUNS.parent

    def test_current_site_and_props(self):
        from h3 import deploy
        d = deploy.load_deploy(self.ROOT)
        self.assertIn(d.get("site"), ("win-remote", "spark-local"))
        p = deploy.site_props(d, deploy.current_site(self.ROOT))
        self.assertIn("tunnel", p)
        self.assertIn(p.get("fetch"), ("scp", "local_cp"))

    def test_set_site_switches_and_syncs_llm(self):
        from h3 import deploy
        import json as _json
        td = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(td, ignore_errors=True))
        cfg = td / "config"
        cfg.mkdir()
        base = {
            "site": "win-remote",
            "sites": {
                "win-remote": {"label": "A", "tunnel": True, "fetch": "scp",
                               "llm_base_url": "http://127.0.0.1:8011/v1"},
                "spark-local": {"label": "B", "tunnel": False, "fetch": "local_cp",
                                "llm_base_url": "http://127.0.0.1:8000/v1"},
            },
        }
        (cfg / "deploy.json").write_text(_json.dumps(base), encoding="utf-8")
        (cfg / "llm.json").write_text(_json.dumps({"base_url": "http://127.0.0.1:8011/v1"}),
                                     encoding="utf-8")
        site, props, old = deploy.set_site(td, "spark-local")
        self.assertEqual(site, "spark-local")
        self.assertFalse(props["tunnel"])
        self.assertEqual(deploy.current_site(td), "spark-local")
        llm = _json.loads((cfg / "llm.json").read_text(encoding="utf-8"))
        self.assertEqual(llm["base_url"], "http://127.0.0.1:8000/v1")
        self.assertTrue((cfg / "llm.json.bak").exists())
        # 回切
        deploy.set_site(td, "win-remote")
        llm2 = _json.loads((cfg / "llm.json").read_text(encoding="utf-8"))
        self.assertEqual(llm2["base_url"], "http://127.0.0.1:8011/v1")

    def test_invalid_site_rejected(self):
        from h3 import deploy
        with self.assertRaises(ValueError):
            deploy.set_site(self.ROOT, "mars")


# ---------------------------------------------------------------------------
# 输出文件解析 / 远程路径
# ---------------------------------------------------------------------------
class TestOutputParsing(unittest.TestCase):
    def test_images_key(self):
        files = comfy.extract_output_files(
            {"images": [{"filename": "a.mp4", "subfolder": "video", "type": "output"}]}
        )
        self.assertEqual(files[0]["filename"], "a.mp4")

    def test_gifs_key_and_fallback_unknown(self):
        files = comfy.extract_output_files(
            {"gifs": [{"filename": "b.mp4", "subfolder": "video", "format": "mp4"}]}
        )
        self.assertEqual(files[0]["format"], "mp4")
        files2 = comfy.extract_output_files(
            {"custom_list": [{"filename": "c.webm"}]}
        )
        self.assertEqual(files2[0]["filename"], "c.webm")

    def test_empty_and_garbage(self):
        self.assertEqual(comfy.extract_output_files(None), [])
        self.assertEqual(comfy.extract_output_files("nope"), [])
        self.assertEqual(comfy.extract_output_files({}), [])
        self.assertEqual(comfy.extract_output_files({"images": [{"foo": 1}]}), [])

    def test_remote_path_building(self):
        self.assertEqual(
            comfy.build_remote_path("~/ai/ComfyUI/output",
                                    {"filename": "a.mp4", "subfolder": "video"}),
            "~/ai/ComfyUI/output/video/a.mp4",
        )
        self.assertEqual(
            comfy.build_remote_path("~/x", {"filename": "a.mp4", "subfolder": ""}),
            "~/x/a.mp4",
        )


# ---------------------------------------------------------------------------
# Comfy 客户端重试语义
# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class TestComfyClientRetries(unittest.TestCase):
    def test_retries_transient_then_succeeds(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(req)
            if len(calls) < 3:
                raise urllib.error.URLError("conn reset")
            return FakeResp(b'{"ok": true}')

        with mock.patch("h3.comfy._urlopen", side_effect=fake_urlopen):
            client = comfy.ComfyClient(retries=3, base_delay=0.01)
            result = client.request("GET", "/system_stats")
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_http_rejection_is_not_retried(self):
        calls = []

        def fake_urlopen(req, timeout):
            calls.append(req)
            return FakeResp(b'{"error":"bad"}')

        # HTTPError 只能由真实 urlopen 语义触发，这里直接模拟抛出
        def raise_http(req, timeout):
            calls.append(req)
            hdrs = {}
            fp = io.BytesIO(b'{"error":"bad"}')
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", hdrs, fp)

        with mock.patch("h3.comfy._urlopen", side_effect=raise_http):
            client = comfy.ComfyClient(retries=5, base_delay=0.01)
            with self.assertRaises(comfy.ComfyRejected) as ctx:
                client.request("POST", "/prompt", {"prompt": {}})
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(len(calls), 1)  # 不重试

    def test_all_fail_raises_unreachable(self):
        def always_fail(req, timeout):
            raise urllib.error.URLError("down")

        with mock.patch("h3.comfy._urlopen", side_effect=always_fail):
            client = comfy.ComfyClient(retries=2, base_delay=0.01)
            with self.assertRaises(comfy.ComfyUnreachable):
                client.request("GET", "/history/x")


# ---------------------------------------------------------------------------
# 状态文件（原子写 / 损坏容错 / 旧版迁移）
# ---------------------------------------------------------------------------
@needs_fs
class TestJobState(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_roundtrip_and_clear(self):
        jobstate.save_root_state(self.dir, prompt_id="abc", remote_path="~/x/a.mp4")
        st = jobstate.load_root_state(self.dir)
        self.assertEqual(st["prompt_id"], "abc")
        self.assertEqual(st["remote_path"], "~/x/a.mp4")
        self.assertTrue(jobstate.clear_root_state(self.dir))
        self.assertEqual(jobstate.load_root_state(self.dir)["prompt_id"], "")

    def test_corrupt_json_treated_as_empty(self):
        p = jobstate.root_state_path(self.dir)
        p.write_text("{not json!!", encoding="utf-8")
        st = jobstate.load_root_state(self.dir)
        self.assertEqual(st["prompt_id"], "")

    def test_legacy_plaintext_migrates_and_is_removed_on_save(self):
        legacy = self.dir / "last_prompt_id.txt"
        legacy.write_text("legacy-id-123\n", encoding="utf-8")
        st = jobstate.load_root_state(self.dir)
        self.assertEqual(st["prompt_id"], "legacy-id-123")
        jobstate.save_root_state(self.dir, prompt_id="new-id")
        self.assertFalse(legacy.exists())
        self.assertEqual(jobstate.load_root_state(self.dir)["prompt_id"], "new-id")

    def test_task_record_lifecycle(self):
        folder = self.dir / "workflows" / "h3_t"
        folder.mkdir(parents=True)
        jobstate.record_task_start(self.dir, folder, {"prompt_id": "", "params": {"a": 1}})
        jobstate.update_task_record(self.dir, folder, {"prompt_id": "p1", "state": "completed"})
        job = json.loads((folder / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(job["prompt_id"], "p1")
        self.assertEqual(job["state"], "completed")
        self.assertEqual(job["params"]["a"], 1)


@needs_fs
class TestEnvironmentFallback(unittest.TestCase):
    def test_defaults_when_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            env = params.load_environment(Path(td))
        self.assertEqual(env["remote_host"], "spark")
        self.assertEqual(env["local_port"], 8188)

    def test_custom_values_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            cfg = d / "config"
            cfg.mkdir()
            (cfg / "environment.json").write_text(
                json.dumps({"remote_host": "other", "max_attempts": 7}),
                encoding="utf-8",
            )
            env = params.load_environment(d)
        self.assertEqual(env["remote_host"], "other")
        self.assertEqual(env["max_attempts"], 7)
        self.assertEqual(env["local_port"], 8188)  # 默认值保留


# ---------------------------------------------------------------------------
# CLI 层冒烟（仅跑不写盘的 dry-run / 确定性报错路径）
# ---------------------------------------------------------------------------
class TestCliSmoke(unittest.TestCase):
    RUNS = Path(__file__).resolve().parent.parent.parent  # runs/
    CLI = RUNS / "h3_submit.py"

    def setUp(self):
        # CLI 以真实项目根为工作目录：清理运行期瞬态文件，避免互相干扰
        root = self.RUNS.parent
        for name in ("last_job.json", "last_prompt_id.txt", ".run.lock", ".tunnel.json"):
            p = root / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        # 注入临时日志文件：避免 CLI 自举日志写入真实 logs\
        self.log_file = _TEST_TMP / f"cli_smoke_{os.getpid()}.log"

    def run_cli(self, *argv):
        import subprocess
        env = dict(os.environ)
        env["H3_LOG_FILE"] = str(self.log_file)
        proc = subprocess.run(
            [sys.executable, str(self.CLI), *argv],
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_dry_run_ok(self):
        code, out, _ = self.run_cli("--prompt", "sunset", "--resolution", "480p",
                                    "--seconds", "5", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn('"class_type": "SaveVideo"', out)

    def test_missing_prompt_is_deterministic_failure(self):
        code, _, err = self.run_cli()
        self.assertEqual(code, 3)
        self.assertIn("需要 --prompt", err)

    def test_bad_resolution_is_deterministic_failure(self):
        code, _, err = self.run_cli("--prompt", "x", "--resolution", "9999p",
                                    "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("invalid choice", err)

    # ---- 直接提交已保存工作流（--workflow-file，只读已有样例文件） ----
    def _sample_api(self):
        wfroot = self.RUNS.parent / "workflows"
        cands = sorted(wfroot.glob("h3_*/workflow_api.json"))
        return str(cands[0]) if cands else ""

    def test_workflow_file_dry_run_ok(self):
        wf = self._sample_api()
        if not wf:
            self.skipTest("仓库中无样例工作流")
        code, out, _ = self.run_cli("--workflow-file", wf, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn('"class_type": "SaveVideo"', out)

    def test_workflow_file_missing_is_deterministic(self):
        code, _, err = self.run_cli("--workflow-file", "no_such_wf.json", "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("工作流文件不存在", err)

    def test_workflow_file_conflicts_with_prompt(self):
        wf = self._sample_api()
        if not wf:
            self.skipTest("仓库中无样例工作流")
        code, _, err = self.run_cli("--workflow-file", wf, "--prompt", "x", "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("不能与", err)


# ---------------------------------------------------------------------------
# 模板占位符 / 阶段注册表 / multipart 上传
# ---------------------------------------------------------------------------
class TestTemplateTokens(unittest.TestCase):
    def test_collect_and_substitute_recursive(self):
        obj = {"1": {"class_type": "X", "inputs": {"a": "{{prompt}} 到 {{ prompt }}",
                                                    "b": ["2", 0]}},
               "prompt": "{{unknown_custom}}"}
        toks = templates.collect_tokens(obj)
        self.assertIn("prompt", toks)
        self.assertIn("unknown_custom", toks)

        new, missing = templates.substitute(obj, {"prompt": "猫 与 夕阳"})
        self.assertEqual(new["1"]["inputs"]["a"], "猫 与 夕阳 到 猫 与 夕阳")
        self.assertIn("unknown_custom", missing)

        new2, missing2 = templates.substitute(obj, {"prompt": "x"}, ignore_missing=["unknown_custom"])
        self.assertEqual(missing2, [])

    def test_missing_only_in_unknown(self):
        obj = {"text": "hello {{image0}}"}
        _, missing = templates.substitute(obj, {"prompt": "x"})
        self.assertEqual(missing, ["image0"])

    def test_validate_workflow_formats(self):
        api = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{image0}}"}}}
        templates.validate_workflow(api)
        self.assertEqual(templates.api_to_submittable(api)["1"]["class_type"], "LoadImage")
        ui = {"nodes": [{"id": 1, "type": "LoadImage"}], "links": []}
        templates.validate_workflow(ui)
        with self.assertRaises(ValueError):
            templates.api_to_submittable(ui)
        with self.assertRaises(ValueError):
            templates.validate_workflow({"weird": 1})


class TestPromptPathFallback(unittest.TestCase):
    """pick_prompt_paths：槽位/阶段默认文件为空时必须视为未设置并继续回退。"""

    RUNS = Path(__file__).resolve().parent.parent.parent
    ROOT = RUNS.parent

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        pd = self.dir / "prompts"
        wd = pd / "workflows"
        wd.mkdir(parents=True)
        manifest = {
            "prompt_dir": "prompts/workflows",
            "default": {
                "positive": "prompts/def_pos.txt",
                "negative": "prompts/def_neg.txt",
            },
            "slots": {
                "video_r2v": {
                    "positive": "prompts/workflows/video_r2v.positive.txt",
                    "negative": "prompts/workflows/video_r2v.negative.txt",
                }
            },
            "workflow_files": {"video_minimax_h3_r2v.json": "video_r2v"},
        }
        (pd / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.slot_pos = wd / "video_r2v.positive.txt"
        self.slot_neg = wd / "video_r2v.negative.txt"
        self.stage_pos = pd / "stage_pos.txt"
        self.stage_neg = pd / "stage_neg.txt"
        self.def_pos = pd / "def_pos.txt"
        self.def_neg = pd / "def_neg.txt"
        self.stage_cfg = {
            "prompt_files": {
                "positive": "prompts/stage_pos.txt",
                "negative": "prompts/stage_neg.txt",
            }
        }

    def tearDown(self):
        self._td.cleanup()

    def test_empty_slot_file_falls_back_to_stage_default(self):
        # 槽位文件为空/纯空白 -> 回退阶段默认文件
        for p in (self.slot_pos, self.slot_neg):
            p.write_text("   \n", encoding="utf-8")
        self.stage_pos.write_text("STAGE-POS", encoding="utf-8")
        self.stage_neg.write_text("STAGE-NEG", encoding="utf-8")
        self.def_pos.write_text("DEF-POS", encoding="utf-8")
        self.def_neg.write_text("DEF-NEG", encoding="utf-8")
        pos, neg = prompts.pick_prompt_paths(
            self.dir, self.stage_cfg, Path("video_minimax_h3_r2v.json"), None, None)
        self.assertEqual(pos.resolve(), self.stage_pos.resolve())
        self.assertEqual(neg.resolve(), self.stage_neg.resolve())

    def test_all_empty_falls_back_to_manifest_default(self):
        # 槽位空 + 阶段默认空 -> manifest default
        for p in (self.slot_pos, self.slot_neg, self.stage_pos, self.stage_neg):
            p.write_text("", encoding="utf-8")
        self.def_pos.write_text("DEF-POS", encoding="utf-8")
        self.def_neg.write_text("DEF-NEG", encoding="utf-8")
        pos, neg = prompts.pick_prompt_paths(
            self.dir, self.stage_cfg, Path("video_minimax_h3_r2v.json"), None, None)
        self.assertEqual(pos.resolve(), self.def_pos.resolve())
        self.assertEqual(neg.resolve(), self.def_neg.resolve())

    def test_nonempty_slot_wins(self):
        # 槽位非空 -> 槽位优先于阶段默认
        self.slot_pos.write_text("SLOT-POS", encoding="utf-8")
        self.slot_neg.write_text("SLOT-NEG", encoding="utf-8")
        self.stage_pos.write_text("STAGE-POS", encoding="utf-8")
        self.stage_neg.write_text("STAGE-NEG", encoding="utf-8")
        self.def_pos.write_text("DEF-POS", encoding="utf-8")
        self.def_neg.write_text("DEF-NEG", encoding="utf-8")
        pos, neg = prompts.pick_prompt_paths(
            self.dir, self.stage_cfg, Path("video_minimax_h3_r2v.json"), None, None)
        self.assertEqual(pos.resolve(), self.slot_pos.resolve())
        self.assertEqual(neg.resolve(), self.slot_neg.resolve())

    def test_unregistered_template_uses_stage_then_default(self):
        # 模板未注册槽位：阶段默认 > manifest default（都不允许空文件当选）
        self.stage_pos.write_text("STAGE-POS", encoding="utf-8")
        self.stage_neg.write_text("", encoding="utf-8")
        self.def_pos.write_text("DEF-POS", encoding="utf-8")
        self.def_neg.write_text("DEF-NEG", encoding="utf-8")
        pos, neg = prompts.pick_prompt_paths(
            self.dir, self.stage_cfg, Path("unknown_template.json"), None, None)
        self.assertEqual(pos.resolve(), self.stage_pos.resolve())
        self.assertEqual(neg.resolve(), self.def_neg.resolve())


class TestStageConfig(unittest.TestCase):
    """基于真实 config/pipeline.json（只读）与临时文件行为测试。"""
    RUNS = Path(__file__).resolve().parent.parent.parent
    ROOT = RUNS.parent

    def setUp(self):
        cfg = stage.load_pipeline_config(self.ROOT)
        self.assertIn("t2v", cfg["stages"])
        self.cfg = cfg

    def test_default_and_registry(self):
        self.assertEqual(stage.default_stage_id(self.cfg), "t2v")
        ids = {s["id"] for s in stage.list_stages(self.cfg)}
        for expect in ("t2v", "i2v", "r2v", "flf2v"):
            self.assertIn(expect, ids)

    def test_unknown_stage_raises(self):
        with self.assertRaises(params.ParamError):
            stage.resolve_stage(self.cfg, "not_a_stage")

    def test_prompt_paths_priority(self):
        st = stage.resolve_stage(self.cfg, "t2v")
        pos, neg = stage.gather_prompt_paths(self.ROOT, st, None, None)
        self.assertEqual(pos.resolve(), (self.ROOT / "prompts" / "positive_prompts.txt").resolve())
        custom = self.ROOT / "prompts" / "my_prompt.txt"
        pos2, _ = stage.gather_prompt_paths(self.ROOT, st, str(custom), None)
        self.assertEqual(pos2.resolve(), custom.resolve())

    def test_images_defaults_and_missing(self):
        st = stage.resolve_stage(self.cfg, "r2v")
        self.assertEqual(stage.gather_images(self.ROOT, st, None), [])
        st["default_images"] = ["no_such_character.png"]
        with self.assertRaises(params.ParamError):
            stage.gather_images(self.ROOT, st, None)
        with self.assertRaises(params.ParamError):
            stage.gather_images(self.ROOT, st, ["also_missing.png"])

    def test_text_map(self):
        gp = params.resolve_params({"resolution": "480p", "seconds": "5", "seed": "7"})
        m = stage.text_token_map(gp)
        self.assertEqual(m["seed"], "7")
        self.assertEqual(m["width"], "864")


class TestImageUploadBody(unittest.TestCase):
    def test_body_contains_file_and_fields(self):
        body, boundary = comfy.build_image_upload_body(
            "ref.png", b"\x89PNG-fake", subfolder="video", overwrite="true",
            boundary="BOUND123",
        )
        text = body.decode("latin1")
        self.assertIn('name="image"; filename="ref.png"', text)
        self.assertIn("--BOUND123--\r\n", text)
        self.assertIn('name="overwrite"\r\n\r\ntrue', text)
        self.assertIn('name="subfolder"\r\n\r\nvideo', text)

    def test_boundary_generated_when_missing(self):
        body, boundary = comfy.build_image_upload_body("a.png", b"x")
        self.assertTrue(boundary.startswith("----H3Boundary"))
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode("latin1")))


class TestStageCli(unittest.TestCase):
    RUNS = Path(__file__).resolve().parent.parent.parent  # runs/
    CLI = RUNS / "h3_submit.py"

    def setUp(self):
        root = self.RUNS.parent
        for name in ("last_job.json", "last_prompt_id.txt", ".run.lock", ".tunnel.json"):
            p = root / name
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
        # 注入临时日志文件：避免 CLI 自举日志写入真实 logs\
        self.log_file = _TEST_TMP / f"cli_stage_{os.getpid()}.log"

    def run_cli(self, *argv):
        import subprocess
        env = dict(os.environ)
        env["H3_LOG_FILE"] = str(self.log_file)
        proc = subprocess.run(
            [sys.executable, str(self.CLI), *argv],
            capture_output=True, text=True, timeout=60,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def test_explicit_stage_t2v_dry_run(self):
        code, out, _ = self.run_cli("--stage", "t2v", "--prompt", "sunset", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn('"class_type": "SaveVideo"', out)
        self.assertIn("阶段: t2v", out)

    def _comfy_online(self) -> bool:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def test_stage_r2v_template_availability(self):
        code, _, err = self.run_cli("--stage", "r2v", "--prompt", "sunset", "--dry-run")
        if code == 3:
            # 离线或无法转换且无内置 -> 确定性失败并给出指引
            self.assertTrue(
                any(x in err for x in ("模板缺失", "需要在线", "无法读取节点定义",
                                       "不是有效的扁平 API")),
                msg=err)
        else:
            self.assertEqual(code, 0)  # 在线 ComfyUI 可把官方 UI 模板转换为 API

    def test_official_t2v_ui_converted_online(self):
        if not self._comfy_online():
            self.skipTest("本机没有在线 ComfyUI，跳过 UI->API 在线转换用例")
        wf = self.RUNS.parent / "config" / "templates" / "api_minimax_h3_t2v.json"
        code, out, _ = self.run_cli("--template", str(wf), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("MinimaxHailuo03TextToVideoNode", out)
        self.assertIn("model.prompt", out)   # 动态组合子输入键（服务器期望格式）

    def test_unknown_stage_is_deterministic(self):
        code, _, err = self.run_cli("--stage", "bogus", "--prompt", "x", "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("未知的生成阶段", err)

    def test_template_tokens_replaced(self):
        # 用临时 API 模板验证占位符替换（dry-run 输出即替换后的 JSON）
        import tempfile as _tf

        api = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "{{image0}}"}},
            "2": {"class_type": "SomeText", "inputs": {"text": "{{prompt}}", "seed": "{{seed}}"}},
        }
        with _tf.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(api, f)
            tmp = f.name
        try:
            code, out, _ = self.run_cli("--template", tmp, "--prompt", "一只猫",
                                        "--seed", "42", "--image",
                                        str(self.RUNS.parent / "my_video.mp4"), "--dry-run")
            self.assertEqual(code, 0)
            data = json.loads(out[out.index("{"):])
            self.assertEqual(data["2"]["inputs"]["text"], "一只猫")
            self.assertEqual(data["2"]["inputs"]["seed"], "42")
            self.assertEqual(data["1"]["inputs"]["image"], "my_video.mp4")  # dry-run:本地名
        finally:
            try:
                Path(tmp).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
