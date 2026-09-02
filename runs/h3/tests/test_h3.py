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


from h3 import comfy, jobstate, params, stage, templates, workflow  # noqa: E402


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

    def run_cli(self, *argv):
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(self.CLI), *argv],
            capture_output=True, text=True, timeout=60,
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

    def run_cli(self, *argv):
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(self.CLI), *argv],
            capture_output=True, text=True, timeout=60,
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
