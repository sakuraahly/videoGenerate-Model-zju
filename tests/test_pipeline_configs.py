"""pipeline 配置与工作流审计的护栏测试（2026-09-10 统一工作流时新增）。

背景：当天发现两类问题都是"没有测试拦"造成的——
  ① config/pipeline.example.json 被改成**非法 JSON**（备注文字写到字符串外、丢了逗号），
     而它是别人复制成 pipeline.json 的入口，坏了就等于配置入口坏了；
  ② pipeline.json 里 character/keyframes 两个 stage 指向**从未存在过**的模板（死配置）。
所以这里固定住：示例必须合法、stage 指向的模板必须真实存在、审计工具必须能报出缺失。
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "runs"))


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def test_example_pipeline_is_valid_json_and_points_at_mirror():
    ex = _load(REPO / "config" / "pipeline.example.json")
    assert ex["templates_dir"] == "workflows/remote_workflows"
    assert "builtin" in ex["stages"]["t2v"]


def test_example_stage_templates_exist():
    ex = _load(REPO / "config" / "pipeline.example.json")
    tdir = REPO / ex["templates_dir"]
    for name, st in ex["stages"].items():
        if st.get("builtin") or not st.get("template"):
            continue
        assert (tdir / st["template"]).is_file(), "示例 stage %s 的模板不存在: %s" % (name, st["template"])


def test_real_pipeline_matches_example_shape():
    """本机真实配置（不入库）必须与示例同构：目录一致、模板都在。"""
    real = REPO / "config" / "pipeline.json"
    if not real.is_file():
        return
    d = _load(real)
    assert d["templates_dir"] == "workflows/remote_workflows"
    tdir = REPO / d["templates_dir"]
    for name, st in d["stages"].items():
        if st.get("builtin") or not st.get("template"):
            continue
        assert (tdir / st["template"]).is_file(), "stage %s 的模板不存在: %s" % (name, st["template"])


def test_deprecated_config_templates_has_readme():
    """config/templates 已废弃：必须留着说明，否则下一个人还会往那儿改。"""
    assert (REPO / "config" / "templates" / "README.md").is_file()


def test_workflow_audit_reports_ok_for_repo():
    from h3 import workflow_audit as wa

    rep = wa.audit(REPO)
    assert rep["ok"] is True, "注册的模板缺失: %s" % rep.get("missing")
    assert rep["templates_dir"].endswith("remote_workflows")
    # 内置生成器的 stage 不进 missing 也不该被当成文件
    builtins = [r for r in rep["stages"] if r.get("builtin")]
    assert builtins and builtins[0]["stage"] == "t2v"


def test_workflow_audit_detects_missing_template(tmp_path):
    """审计必须能报出"stage 指向的模板不存在"（就是今天那个死配置）。"""
    from h3 import workflow_audit as wa

    (tmp_path / "config").mkdir()
    (tmp_path / "workflows" / "remote_workflows").mkdir(parents=True)
    (tmp_path / "config" / "pipeline.json").write_text(json.dumps({
        "default_stage": "t2v",
        "templates_dir": "workflows/remote_workflows",
        "stages": {"t2v": {"kind": "video", "template": "nope.json", "builtin": None}},
    }, ensure_ascii=False), encoding="utf-8")
    rep = wa.audit(tmp_path)
    assert rep["ok"] is False
    assert rep["missing"] and rep["missing"][0]["template"] == "nope.json"
    assert "FAIL" in wa.render(rep)
