# 交接文档 · 2026-09-11 第二轮（UI 自动回传断链修复）

> 上一份：`docs/handoff/handoff-2026-09-11.md`（创空间 v3.4 + 本机修复），本文只写本轮：
> **handoff-2026-09-11 §二.1「UI 反查兜底仍返回 None」已结案**。事实权威仍是 `docs/CURRENT-STATE.md`。

## 一、用户诉求

> 「生成好的任务没有自动回传到 UI 界面」

即：任务在 ComfyUI 跑完、成片也已经落到本机 `outputs/`，但 7860 页面结果区一直是「暂无结果」，
必须用户再发一句话（或用工具查）才看得到——「自动回传」这一环断了。

## 二、症状与复现（三条，全部先复现后修）

用临时仓库复刻真实形态（会话档有 prompt_id + `workflows/*/job.json` + `outputs/` 有产物 +
任务日志有 `LOCAL_OUTPUT`），会话产物目录为空：

| 复现 | 修复前 | 修复后 |
|---|---|---|
| 任务日志被更新的 20 个 `run_*.log` 挤出窗口 | `latest_final -> None` | 命中真实路径且 `is_file()` 为真 |
| 会话目录为空、反查命中 | `session_videos -> []`（结果区「暂无结果」） | `[video_85.mp4]` |

（第二条就是"最后一公里"：即使反查拿到了路径，旧代码也会把它丢掉。）

## 三、根因链（五条，按链路顺序）

1. **日志定位错（handoff 实测 None 的直接原因）**：`h3_submit.record_task_start` 写进 `job.json.log_file` 的是
   `os.path.basename(run_log)`，日志真实位置是 `<repo>/logs/<name>`（`_adopt_task_log` 也是这么取回的）。
   反查兜底却拼成 `task_dir / log_name` —— **该文件永远不存在**，于是任务日志里的 `LOCAL_OUTPUT` 永远读不到。
   唯一的补救是"扫最近 20 个 `run_*.log`"，任务自己的日志一旦被挤出窗口就彻底失联。
2. **最后一公里**：`session_videos()` 用 `if f in vids` 才把成品提到首位。反查命中的成品在会话目录**之外**，
   于是 `vids` 仍是空 → UI 直接返回「暂无结果」，反查结果被整个丢掉。
3. **没有自动刷新**：结果区只在 `send` 的每个 yield 与加载会话时刷新。任务若在本轮结束后才完成，
   页面永远停在旧状态——这就是"没有**自动**回传"的字面原因。
4. **watcher 取片没带会话 id**：`ui_app` 里 watcher 的 `h3_submit.py --resume` 子进程未传
   `VIDEOGEN_SESSION_CID` → `_session_place` 读到空 cid 直接 return，产物只落 `outputs/`，
   本来最可靠的那条路（落盘即标成品）被静默跳过。
5. **两条安全红线（顺手修掉，都是真 bug）**：
   - `job.json.videos/audios` 是**输入**参考素材（`--videos` / resume 恢复用，见 `record_task_start` 与
     `--resume` 的 `_jv` 分支），旧反查把它当"产物"返回 → 会把用户上传的素材显示成「生成的视频」；
   - `LOCAL_OUTPUT` 行**不带任务号**，旧实现跨任务裸扫日志 → 会把别人的产物认成本会话成品（串片）。

## 四、改动清单

| 文件 | 改动 |
|---|---|
| `runs/h3/session_outputs.py` | 删掉"模块尾两次覆盖式补丁"的写法，重写为单层反查兜底：`_task_log_paths`（`<repo>/logs/<log_file>` + 旋转档 `.1` + 历史同目录形态）、`_outputs_from_log`（整行取值，支持含空格/中文的产物名）、`_product_of_task`（`output_file` → 任务日志 → 任务目录 mp4；**不再认 videos/audios**）、`_logs_for_prompt`（跨任务扫日志先按 prompt_id 过滤）、`_final_by_reverse`（带 5s TTL 记忆，供 UI 定时轮询）、`adopt_outputs`（反查 + **回写会话目录并打标**）；`session_videos/session_files` 纳入会话目录之外的成品；`latest_final` 保持纯读 |
| `runs/agent/ui_app.py` | `_results_update`：刷新前先 `adopt_outputs`、会话目录为空但反查命中也要显示、预览位只放视频、`quiet` 口径下无变化回 no-op；新增 `_poll_results` + `gr.Timer(5s)`（无 Timer 的旧版 Gradio 回退 `demo.load(every=5)`）；watcher 的 `--resume` 带上 `VIDEOGEN_SESSION_CID`；`allowed_paths` 追加 `outputs/` |
| `tests/test_results_backfill.py` | 新增 15 例回归（见下） |

**为什么必须回写**：Gradio 只服务 `allowed_paths` 内的文件（ui_app 放行的是会话产物目录）。
产物若只躺在 `outputs/`，页面上会「查得到、放不出来」。`adopt_outputs` 把成品复制进会话目录并打
`_final.json`，预览/下载都正常，且下次刷新直接走最快路径（不再反查）。

## 五、验收证据

```bash
py -3 -m pytest tests -q            # 314 passed / 1 skipped（原 299 + 新增 15）
py -3 -m pytest runs/h3/tests -q    # 5 failed / 166 passed —— 与本轮无关的既有失败
                                    #   （test_workflow_registry / test_capabilities_a4：本机缺模板）
```

- **修复前对照**：同一批 15 例，在 `git stash` 掉两处源码改动后 **15/15 失败**，修复后全绿。
- 复现脚本三条（日志挤出窗口 / 最后一公里 / 输入素材与串片）全部由失败转为通过。
- `runs/consistency_check.py`：仅剩本机缺模板等既有提示（与 git 未跟踪=本轮新测试文件）。

## 六、未做 / 下一步（诚实登记）

1. **spark 真机验收**：`runs/sync_to_spark.py` 同步 + 重启 agent（tmux `agent`，**重启=授权项**）后，按两条路径验收：
   (a) 后台完成的任务（`--submit-only` 后不管它）→ 页面自己出现成片；
   (b) 服务重启后打开历史会话 → 结果区自动出现该会话成片。
2. `session_state` 的会话任务表仍是**内存态**：服务重启后 watcher 不再监控"尚未出片"的旧任务。
   已出片的靠本轮反查兜底自动回传；**未出片的**需要用户点一次「继续」重新登记。
   若要彻底自治，下一步可从磁盘恢复待监控任务（`workflows/*/job.json` 中 `state=submitted` 且
   `prompt_id` 出现在某会话档 → 重新登记），但必须加时间窗，否则会为陈年任务误报"任务失败"。
3. Gradio 版本未在仓库固定（`gr.Timer` 需 Gradio ≥ 4.40）：本轮已做 `hasattr` 回退，真机请顺手
   登记 spark 的 gradio 版本号。

## 七、关键文件

| 位置 | 说明 |
|---|---|
| `runs/h3/session_outputs.py` | 会话产物协议 + 本轮重写的反查兜底/回写（`latest_final` / `adopt_outputs`） |
| `runs/agent/ui_app.py` | 结果区（`_results_update` / `_poll_results`）+ watcher 取片调用点 |
| `runs/h3_submit.py` | `_session_place`（落盘侧，依赖 `VIDEOGEN_SESSION_CID`）、`record_task_start`（job.json 字段语义） |
| `tests/test_results_backfill.py` | 本轮回归（三条断链 + 真机日志口径 + 两条安全红线 + watcher 调用点 glue 守卫） |
| `tests/test_breakpoint_clear.py` | 断点陈旧判定 5 例（见 §八.2.3） |

## 八、真机验收（2026-09-11 第三轮，已完成）

**用户指示**：「现在重启测试吧」→ 同步 spark + 重启 agent + 真机验收，并修掉真机暴露的问题。

### 8.1 验收结果（全部通过）

| 验收项 | 结果 |
|---|---|
| ① handoff §2.1 验收标准（会话 `20260911_013310_24b9`） | 修复前 `latest_final -> None`；修复后 → `outputs/video_623_pp.mp4`，`is_file()=True` |
| ② UI 结果区（活体 HTTP 事件接口） | 标签「本轮结果视频（成品 · 含配音/字幕）」；下载列表成品排第一；页面取片 **HTTP 200** |
| ③ 自动回传轮询真的注册了 | `/config`：timer 组件 `value=5, active=True`；依赖 `_poll_results` ← `targets=[[timer,'tick']]`、`outputs=[26,27]`（=res_video/res_files） |
| ④ 新任务全链（经 UI `send` 真实提交一次 360p/5s t2v） | agent 提交 → 完成 → **watcher 自动取片落会话目录**（用户零操作）→ 结果区自动出现 `video_625_pp.mp4`（1,152,901 B，HTTP 200） |
| ⑤ 服务重启后打开历史会话 | 同上自动出现（验收路径 b） |
| ⑥ 同步一致性 | `session_outputs.py / ui_app.py / h3_submit.py` 两端 sha1 一致 |

### 8.2 真机暴露并修掉的三处问题（都不在原先的判断里）

1. **日志里根本没有 `LOCAL_OUTPUT:` 行**（handoff §2.1 的假设不成立）：那行是子进程 stdout，被
   `run_script` / watcher 的 `capture_output` 吞掉，**不会写进日志文件**。真机日志里落盘的是
   `_log_event` 的 key=value 行：`local_output file=video_N.mp4`、`tts_done file=video_N_pp.mp4`、
   `postprocess_done / mix_ref_done / upscale_done file=…`。→ 反查改为认这些事件行（**白名单事件名**；用贪心
   前缀会把事件名吞成单字母，实测踩到）+ `logs/quality.jsonl` 的 pid→文件名直连映射；成品优先
   （`_pp/_final/_mix/tts`），否则会把队列直出当成品回传。
2. **watcher 重复取片**：现场 5 分钟内对同一已完成任务 `--resume` 了 5 次，产出 video_620..624_pp.mp4
   五份重复成品。原因：取片排在上报去重门**之外** → 每 15s 轮询周期重下 + 重跑 TTS。已把取片移进去重门内
   （注释里的「幂等」即本意）。
3. **陈旧断点把新任务全堵死**：`last_job.json` 残留旧 pid → 新生成被「检测到上次任务尚未完成」拦下
   （用户看到的就是"点了没反应"）。原因：watcher 的 `--resume` 被服务重启打断时 `save_root_state` 已写、
   结尾的 `clear_root_state` 没跑到。新增 `h3_submit._breakpoint_is_stale()`（任务记录
   `state=completed`，或质量看板已有该 pid 产物 ⇒ 陈旧），守卫**先判陈旧再决定拦不拦**，陈旧即自动清理放行。

### 8.3 环境登记

- spark **gradio 5.23.1**（`gr.Timer` 可用 → `hasattr` 回退分支未启用；§六.3 条待办可勾掉）。
- 重启命令：`python3 runs/agent/svc_main.py restart-agent`（本轮执行 3 次，每次 ~10s 起，7860 立即可用）。
- 测试：**323 passed / 1 skipped**（本轮 +24 例；`runs/h3/tests` 仍是那 5 个与本轮无关的既有失败）。

### 8.4 遗留（下一轮）

- 早期重复取片留下的 `outputs/video_620..624*.mp4`（10 个文件，内容重复）需人工确认后清理——本轮未动用户产物。
- 本轮验收产生的会话：`20260911_040300_a535`（真机成片，可作样片）、`20260911_035959_e2e1`（断点拦截那次，agent 提了问）。
- 服务重启后 watcher 仍不监控"尚未出片"的旧任务（`session_state` 是内存态）——已出片的靠反查兜底自动回传（§六.2）。

