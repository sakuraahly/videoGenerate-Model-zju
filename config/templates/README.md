# ⚠️ 本目录已废弃（DEPRECATED）——引擎不再读取

**结论先说**：引擎实际使用的模板目录是 **`workflows/remote_workflows/`**（由 `config/pipeline.json` 的
`templates_dir` 指定，并经 `shell/sync_to_spark.ps1` 同步到 spark 后由引擎读取）。

## 这个目录为什么还在

历史遗留：早期把 spark 同事的工作流原件又放了一份到这里当"备份/参考"。2026-09-10 统一核查时确认：

- 本目录的 `video_minimax_h3_*.json` 与镜像目录的**同名文件内容并不一致**（已分叉：镜像里是
  我们按 book-06 改造过的"属性词模板"，这里是旧的原件副本）；
- 代码里唯一提到它的是 `runs/h3/stage.py` 的**回退默认值**（`pipeline.json` 缺失时才会用到），
  该默认值已在 2026-09-10 改为 `workflows/remote_workflows`，与真实配置一致。

## 请这样做

- **要改工作流** → 改 `workflows/remote_workflows/`（唯一权威），然后用
  `bats/workflow/sync_to_spark.bat` 推到 spark；
- **要看当前到底在用哪份** → `python runs/h3/workflow_audit.py`（只读，列出每个 stage 的模板 + sha1 +
  未注册模板 + 本目录与镜像的差异）；
- **同步同事原件** → `bats/workflow/sync_remote_workflows.bat`，但注意：它是**用同事原件覆盖镜像**，
  会冲掉我们的改造，务必先 `git status` / `git stash` 或 `git diff` 确认。

> 本目录文件保留仅为历史对照，**不要**在这里做任何修改。
