# 阶段 4 — 资源隔离 / 租户（每会话只见自己的素材）

> 状态：计划(未实施) | 目标：每个会话（cid）只能看到『本会话上传/本会话产生』的资源，模型能明确知道『哪些是最新、哪些是本任务所需』，且不默认暴露其他任务/旧项目的产物 |
> 主负责人：后端/素材链 | 依赖：book-01(基线) | 对后端影响：中 | 优先级：🟠 中

---

## 1. 问题背景（用户可见现象 + 模型输出片段）
- agent 列出素材出现 117 项，包括**上一个任务/旧项目**的视频（如 `我的叔叔于勒_成片_00001_.mp4`），并困惑『哪些是最新的』。
- 模型输出：『There is no batch data... I cannot identify which images are the latest.』；『The out pool has 117 items, including videos like 我的叔叔于勒_成片...』。
- 用户要求：修复『租户资源管理问题』，限制模型只能访问**本次这个对话对应的上传资源**；考虑模型部署模式是否因过去对话有记忆/权限访问不同对话资源；让模型知道哪些是最新文件、哪些是本任务所需文件；并限制访问其他任务生成的资源。

---

## 2. 根因分析（实测，详见 batch/resource deep-dive）

### 2.1 当前 batch_id 是『上传事件级、全局』的，不是『会话级』的
- `ui_app.py:355`：`batch_id = b_ + secrets.token_hex(4)`——每次上传事件随机生成，与**会话 cid 无关**。
- `refimage.py:211-213`：`latest` 是 **`all_batches` 中 mtime 最大**的那个批次（跨整个仓库的**全局**最大值），不是当前会话的。
- `refimage.py` 全文件**没有任何 cid/session 键**。

### 2.2 常见『看到全量/旧项目』的两条路径
- **路径 A（无批次数据回退）**：`upload_watch`（Open WebUI 上传）写入 `uploads/log.jsonl` 时**不含 batch_id**（`upload_watch.py:142-144`），于是这类素材不进 `refimage._load_batch_map` 的 `all_batches`。当 `batch==latest` 且无批次数据时走 `refimage.py:215-216` 的 else，`rows` = 三个池的**全量扫描**（含历史 `out` 池视频）。
- **路径 B（全局 latest）**：即便有批次，也可能选到另一个会话/任务的批次（全局 mtime 最大）。
- `out` 池 = ComfyUI `output/` 的**全部历史生成产物**（跨任务，`refimage.py:132-135`）——只要没被『批次桶』精确过滤到，就会整池暴露。

### 2.3 会话 id（cid）存在但其实『管不到』资源
- `ui_app.py:662`：`cid_state = gr.State("")`；cid 用于任务跟踪（`clear_tasks/add_tasks`）、轮次校验（`check_turn_valid`）、停止事件（`get_stop_event`）、会话存档（`logs/agent_chats/<cid>.jsonl`）。
- 但 cid **从没传入** `refimage`、`ingest_upload`、`upload_watch` 或 `list_references` 的参数。
- `turn_state._active_batch`（`:16`,`:22-25`,`:52-54`）本意做『回合+批次』隔离，但 `get_active_batch()` **无任何调用者**——是『死隔离』。

### 2.4 模型『部署模式/记忆』问题
- 调度器模型（本地 Qwen）本身**没有**跨会话记忆：不同会话的聊天在 `logs/agent_chats/<cid>.jsonl` 分开存档，模型不共享。
- 但**磁盘上的素材池是共享、无会话边界的**。所以『模型能否访问其他对话资源』取决于**工具返回什么**，而非模型记忆。
- 结论：**必须把隔离做在工具/素材链层**（`list_references`/`refimage`/`upload_watch`），而不是指望模型自觉。

---

## 3. 目标与范围

**目标**：
- 每会话（cid）有**自己的资产作用域**：`list_references` 默认只返回『本会话』的素材（上传或本会话生成的）。
- 『最新』= 本会话内最新的（而非全局）。
- 旧任务/其他会话/ComfyUI 历史产物**默认不可见**，除非用户明确要求（如 `batch=all`/`--scope all`）。
- 模型能清楚看到两类：`本会话素材` 与 `其他任务产物（需显式引用）`，并知道哪个是新、哪个是本任务所需。

**做**：
- 把 cid 作为『资源作用域』贯穿：`ingest_upload` → 给本 cid 打批次；`upload_watch` → 分配会话/批次；`refimage list` → 按 cid/批次过滤；`list_references` 接受 cid，默认当前会话。
- 建立『会话资产索引』：cid → {uploads:[...], outputs:[...]}，落盘可查（如 `uploads/sessions/<cid>/index.json` 或在 log.jsonl 增加 cid 字段）。
- `out` 池默认按『本会话产生的输出』过滤（用该 cid 的任务文件夹/`job.json` 的 prompt_id ↔ ComfyUI output 对应关系），而非全量。
- 『最新/本任务所需』识别：给素材标注 {上传时间、来源会话、用途标签(角色/场景/道具/首帧/末帧)、是否已被 use}，并给『最近上传 N 条』快捷入口。
- 评估模型部署模式影响：在工具描述/系统提示里明确『素材 = 当前会话专用；如需其他任务产物，需用户明确授权并指明』。

**不做**：不物理删除/移动他人产物；不跨会话共享隐私内容；不把隔离做成『全局禁用 out 池』而影响合法的『复用历史产物』需求（改为『默认隐藏+显式开启』）。

---

## 4. 改动点清单（拟议）

| 文件 | 拟改内容 | 目的 |
|---|---|---|
| `runs/agent/ui_app.py` | `ingest_upload` 把当前 cid 写入 `uploads/log.jsonl`（新增 `cid` 字段），并建 `uploads/sessions/<cid>/index.json`；`send` 把 cid 传给 `list_references` | 会话级资产登记 |
| `runs/h3/upload_watch.py` | `_record` 增加 `batch_id`/会话来源字段（若非界面直传，记为『外部上传，无会话归属』） | 消除『无批次数据』回退 |
| `runs/h3/refimage.py` | `cmd_list`/`_rows` 增加按 cid/会话过滤；`latest` 改为『本会话内 mtime 最大』；新增 `--scope all` 才暴露其他会话/历史产物；`_load_batch_map` 读 `cid` 字段 | 真正按会话隔离 |
| `runs/agent/tools.py` | `ListReferences` 增加 `session/cid` 参数（默认取当前会话），并把『本会话 vs 其他』标注进返回文案；区分上传素材与生成产物 | 让模型知道『哪些是当前任务』 |
| `runs/agent/turn_state.py` | 让 `_active_batch` 真正被消费（或被清理），避免『死隔离』 | 消除假隔离 |
| `runs/agent/task_watch.py` | 实现 `poll_batch`（读 manifest）；按 cid 跟踪批量任务 | 会话级批量跟踪 |
| `runs/agent/scheduler.py` | `SYSTEM_MESSAGE` 明确『素材=当前会话专用；复用历史产物需用户明确许可并指明』 | 模型侧边界 |
| `docs/agent-reading/01-tools-reference.md` | `list_references` 说明『默认仅当前会话；`batch=all` 才查全部』 | 口径一致 |

---

## 5. 实施步骤

### 步骤 1：登记会话 → 资产映射
- 在 `uploads/log.jsonl` 每行增加 `cid`；对 `upload_watch` 落盘的标记『外部上传/无会话』。
- 建 `uploads/sessions/<cid>/index.json`：记录该会话上传的 {sha, 路径, 缩略图, 时间, kind}。

### 步骤 2：让 `refimage list` 按会话过滤
- `cmd_list`：`--session <cid>`（或复用 `--batch <cid-batch>`）；无会话标识的素材归到『无归属』，默认不列；`latest` 取『本会话内最新』。
- 保留 `--scope all` / `batch=all` 显式全量。

### 步骤 3：把 cid 传入工具层
- `send` 在调用 `list_references` 时带上 cid；`ListReferences` 工具参数增加 `session`（默认当前 cid），并按其过滤。

### 步骤 4：`out` 池会话化（本会话产物识别）
- 用『该会话任务文件夹 `workflows/h3_<ts>/job.json` 的 prompt_id / 产物名 ↔ ComfyUI output 文件』建立映射，只把**本会话产出的视频**列为『本会话产物』；其他 `out` 默认归『其他任务产物（需显式引用）』。

### 步骤 5：给模型的『最新/必需』线索
- `list_references` 返回按时间倒序 + 标注：`本会话最新上传：<文件>；本会话已生成：<产物>；其他任务产物（需用户指明）：<可选>`。
- 在系统提示/工具描述里说明这些语义。

### 步骤 6：批量与会话联动（可选，配合 book-07）
- 批量 manifest 绑定 cid；`task_watch.poll_batch` 按 cid 读取；`turn_state._active_batch` 接 cid 消费。

---

## 6. 验收标准（真实环境可复现）

- [ ] 会话 A 上传素材后，`list_references` 只见 A 的素材；会话 B 上传后，B 只见 B 的素材；互不泄露。
- [ ] 『最新』= 本会话内最新；不再出现『上一个任务的视频』排在最新。
- [ ] 无会话归属的外部上传（Open WebUI）不默认为任何会话的素材（或归『可复用历史』，需显式 `scope=all`）。
- [ ] 旧的 `out` 池历史产物不默认出现在本会话素材列表中；仅当明确 `scope=all`/`batch=all` 时可见。
- [ ] 界面文案可见『本会话专属』等边界提示（配合 book-02）。
- [ ] 模型能明确知道『哪个是本会话最新/本任务所需』，并在生成时使用正确素材（端到端）。

---

## 7. 风险与回滚
- **风险：过度隔离导致『复用历史产物』变难**（用户可能想复用之前生成的某个参考图）——提供 `scope=all` 显式开关 + 用户确认，而非一刀切。
- **风险：会话映射影响 upload_watch 外部上传路径**——对无 cid 的上传标记『无归属』，不破坏现有看门狗入池。
- **回滚**：隔离逻辑以『默认关闭/仅新增过滤参数』为设计，可一键回到『全局 latest』；不迁移/删除任何现有产物。

---

## 8. 与其它册/红线的关系
- 与 book-02（前端『本会话专属』文案）、book-07（批量/引擎契约）联动；是 book-06（工作流注入用图）的前提——注入时应只取本会话素材。
- 红线：不动其他产物文件；不跨会话泄露；不迁移/删除 ComfyUI 现有产物。

---

## 9. 待用户输入 / 待定项
- 隔离策略：默认『仅本会话』，还是『本会话 + 可复用历史（需明确引用）』；建议『默认仅本会话 + scope=all 显式』。
- 是否给『跨会话复用』提供白名单（如指定某一个旧产物可复用）。
- 外部上传（Open WebUI）归属：是『无会话』还是『归最近使用会话』——建议『无会话，需显式引用』。

---

## 10. 实施记录（2026-09-04 第一批）

- ✅ **会话归属落盘**：ui_app `ingest_upload(paths, cid)` 在 `uploads/log.jsonl` 每行写 `cid`；`_upload` 传 `cid_state.value`；`send()` 每轮设置 `tools.CURRENT_SESSION = cid`。
- ✅ **refimage 会话过滤**：`_load_batch_map` 记录 sha→(bid,cid)；新增 `_get_row_meta`/`_filter_by_session`（纯函数）；`list --session <cid>` 默认只显示本会话素材（out/历史产物不出现）；`--scope-all` 显式全量（带警示）。
- ✅ **工具层**：`list_references` 新增 `session` 参数（默认=CURRENT_SESSION；all=全部），描述明确"默认仅当前会话、复用历史需授权"；无会话上下文（CLI）回退 `--scope-all`。
- ✅ **模型侧边界**：SYSTEM_MESSAGE 新增「素材边界（book-05）」。
- ✅ **测试**：`tests/test_session_filter_unit.py` 7/7 UNIT_OK；spark 实机受控验证 **ISOLATION_OK**（会话 testS 只见其 2 项、otherS 暂无、事后恢复 log.jsonl）。
- 📌 说明：旧上传（本特性前）无 cid → 默认不可见，需 `--scope-all`（不迁移/删除任何现有产物）；`turn_state._active_batch` 仍未被消费（下一批接 cid 或清理）；`agent-reading/01` 本无 list_references 章节，工具描述已更新。

