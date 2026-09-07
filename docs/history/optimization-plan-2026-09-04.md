# Agent 体验/性能/隔离 优化计划（终版）

> **日期**：2026-09-04
> **状态**：待实施
> **涉及问题**：上传状态多态、素材池隔离、页面预热、多图转场延迟、无效图片拦截、状态栏显示、失败后卡死

## Context

用户在使用 7860 Agent UI 时发现多个问题：
1. 上传状态反馈不够清晰（无多态：未上传/上传中/成功）
2. 素材池全局共享导致模型看到所有历史素材，无法区分当前任务的图片
3. 页面加载后模型未预热，首次对话需等待唤醒
4. 多图转场任务（5张图→4段flf2v）耗时 400s+，因 12 次工具调用×LLM 推理
5. 无效图片（11-70B 的 ui_verify.png）进入素材池导致 ComfyUI 任务失败
6. 状态栏在回合结束后显示不清（bare 'idle' 丢失绿色圆点 HTML）
7. ComfyUI 失败后模型卡死/循环重试

## 实施顺序

**Phase 1 → P1+P6 → Phase 2 → P5 → Phase 3 → P7 → Phase 4 → P4 → Phase 5 → P2 → Phase 6 → P3**

---

## Phase 1: P1+P6 — 上传多态状态 + 状态栏优化（`ui_app.py`）

### 状态 HTML 常量
```python
def _pill(text, fg, bg, border):
    return (f'<div style="padding:4px 8px;background:{bg};'
            f'border:1px solid {border};border-radius:4px;'
            f'color:{fg};font-weight:600;font-size:13px">{text}</div>')

IDLE_HTML  = '<span style="color:green">● 等待输入</span>'
BUSY_HTML  = lambda t: f'<span style="color:#b45309">● {t}</span>'
ERROR_HTML = '<span style="color:red">● 出错</span>'
UP_IDLE    = '<span style="color:#888">尚未上传素材</span>'
UP_LOADING = lambda n: _pill(f'⏳ 正在上传中… {n} 个文件', '#8a6d1a', '#fff8e1', '#e7d492')
```

### `_upload()` 三态 + 上传/发送竞争防护
- 模块级 `_upload_in_progress = False`
- 上传开始时 `_upload_in_progress = True`，完成/异常时 `= False`（**try/finally 保证复位**）
- `send()` 开头检查：若 `_upload_in_progress` → yield `'⏳ 上传尚未完成，请稍候再发送'`
- 三态：
  1. yield `UP_LOADING(n)`, `noop`（**不清空 gallery**，保留旧预览）
  2. 执行 `ingest_upload`
  3. yield 成功 pill + previews / 失败 pill
- Phase 1 先用简单计数实现无效文件反馈，Phase 2 完成后补充具体文件名

### 所有 `'idle'` → `IDLE_HTML`
- `send()` 最终 yield、`_auto_new`、`_load`、`_new`
- 心跳：`BUSY_HTML(f'处理中 {secs}s · ...')`
- 完成：`IDLE_HTML` + `note_md = '✅ 本轮完成'`
- 出错：`ERROR_HTML`
- 中止：`'<span style="color:#b45309">● 已中止</span>'`

---

## Phase 2: P5 — 无效图片拦截

### 新建 `runs/h3/mediacheck.py`
```python
MIN_IMAGE_BYTES = 1024
MIN_IMAGE_DIM = 32

def check_image_bytes(data: bytes) -> tuple[bool, str]:
    """全异常捕获，永不向外抛异常。"""
    try:
        if len(data) < MIN_IMAGE_BYTES:
            return False, f'过小({len(data)}B)'
        buf = BytesIO(data)
        im = Image.open(buf)
        im.verify()
        im2 = Image.open(BytesIO(data))
        im2.load()  # 强制解码像素
        if min(im2.size) < MIN_IMAGE_DIM:
            return False, f'尺寸过小({im2.size})'
        return True, ''
    except Exception as e:
        return False, f'无法解码: {type(e).__name__}'

def check_image_file(path) -> tuple[bool, str]:
    try:
        return check_image_bytes(Path(path).read_bytes())
    except Exception as e:
        return False, f'读取失败: {e}'
```

### 修改 `ui_app.py` — `ingest_upload()`
- kind=='image' → `mediacheck.check_image_bytes(data)`
- 无效图片跳过归档和镜像
- 返回 `(msg, previews, batch_id, invalid_details)` — invalid_details 为 `[(filename, reason), ...]`
- 反馈消息列出具体文件名：`🚫 2 个无效：a.png（过小），b.png（无法解码）`

### 修改 `upload_watch.py` — `scan_once()`
- 归档前验证，无效图片记录 `{"sha": ..., "rejected": reason}`
- **排除 `_quarantine/` 路径**，避免重复处理

### 修改 `refimage.py`
- `_rows()` 跳过 <1KB 图片；排除 `_quarantine/` 目录
- `prune` 子命令：
  - 扫描三池中 <64KB 的文件，**始终调用 `mediacheck.check_image_file` 完整校验**
  - 无效文件移至 `uploads/_quarantine/<date>/<sha8>_<name>`（唯一命名，不覆盖）
  - 恢复：手动从 `_quarantine/` 移回即可

---

## Phase 3: P7 — 失败处理 + 熔断器

### 新建 `runs/agent/turn_state.py`
```python
import threading, hashlib

_lock = threading.Lock()
_retry_counts: dict[str, int] = {}       # 不可恢复失败计数
_recoverable_counts: dict[str, int] = {}  # 可恢复失败计数（独立上限）
_active_batch: str | None = None
MAX_DETERMINISTIC_RETRIES = 3
MAX_RECOVERABLE_RETRIES = 5

def begin_turn(batch_id: str | None = None):
    global _active_batch
    with _lock:
        _active_batch = batch_id
        # 不清空计数 — 跨轮保留

def bump_retry(key: str, recoverable: bool = False) -> int:
    with _lock:
        if recoverable:
            _recoverable_counts[key] = _recoverable_counts.get(key, 0) + 1
            return _recoverable_counts[key]
        else:
            _retry_counts[key] = _retry_counts.get(key, 0) + 1
            return _retry_counts[key]

def reset_retry(key: str):
    """成功时重置该 key 的所有计数"""
    with _lock:
        _retry_counts.pop(key, None)
        _recoverable_counts.pop(key, None)

def reset_deterministic_only(key: str):
    """可恢复失败时仅重置不可恢复计数"""
    with _lock:
        _retry_counts.pop(key, None)

def get_active_batch() -> str | None:
    with _lock:
        return _active_batch

def reset_all_on_upload():
    """新素材上传后重置所有计数"""
    with _lock:
        _retry_counts.clear()
        _recoverable_counts.clear()
```

### 修改 `tools.py` — `_wrap_call`
```python
key = f"{name}:{hashlib.sha1(p.encode()).hexdigest()[:12]}"

if _is_deterministic_failure(out):
    n = turn_state.bump_retry(key, recoverable=False)
    if n >= MAX_DETERMINISTIC_RETRIES:
        return '⛔ 熔断：同一操作已连续失败 3 次...'
elif _is_recoverable_failure(out):
    n = turn_state.bump_retry(key, recoverable=True)
    if n >= MAX_RECOVERABLE_RETRIES:
        return f'⛔ 连续可恢复失败（{n}次），建议检查服务状态或更换方案'
    # 可恢复失败不重置不可恢复计数
else:
    # 成功 → 重置该 key 的所有计数
    turn_state.reset_retry(key)
```

### 失败消息统一格式
```
⛔ [{错误类型}] {具体信息} | 建议: {操作}
```
- exit 3: `⛔ [ComfyUI执行失败] {stderr首行} | 建议: 检查图片有效性或更换素材`
- 无效图片: 追加 `疑似无效图片，建议运行 refimage.py prune`
- exit 2: `⚠️ [可恢复] {信息} | 建议: 无参重跑续传`（不触发熔断，除非超上限）
- 熔断消息提示"如已更换素材，请重新上传或稍后再试"

### `ui_app.py` — `run_turn()` 开头调用 `turn_state.begin_turn()`
### `ui_app.py` — `_upload()` 成功后调用 `turn_state.reset_all_on_upload()`

### SYSTEM_MESSAGE 增加
```
- 工具返回 ⛔ 时表示不可恢复：不要重试同一调用，改换方案或向用户汇报
```

---

## Phase 4: P4 — 批量提交工具

### 新建 `runs/h3_batch.py`
```
submit --stage flf2v --images a.png,b.png,... [--seconds 5] [--resolution 360p] [--dry-run]
status [--wait] [--timeout 600] [--batch <dir>] [--json]
retry --batch <batch_id> --segments 1,3
```

**`submit`**：
1. 解析图片 → `refimage._resolve_sel`
2. `mediacheck` 验证所有图片 → 任一失败则整体拒绝
3. 生成 manifest `workflows/batch_<ts>/manifest.json`：
   ```json
   {"batch_id": "...", "stage": "flf2v",
    "segments": [{"idx": 0, "images": [...], "prompt_id": "",
                  "state": "pending", "error": "", "output": "",
                  "submit_time": 0, "complete_time": 0}],
    "created": "...", "total_submit_time": 0}
   ```
4. 逐段 `subprocess.run([sys.executable, str(PROJECT_ROOT / "runs/h3_submit.py"), ...])`
   - 使用 `sys.executable` 确保 venv 一致
   - 使用**绝对路径**定位 `h3_submit.py`
   - `timeout=60` 每段（submit-only 应 <10s）
   - TimeoutExpired → manifest 记录 `state: "timeout"` + 保留 pid
   - 每段完成后立即更新 manifest + 记录耗时
5. `--dry-run` 只生成 manifest 不提交
6. 输出：`SEG 0/3 TASK_SUBMITTED: <pid>` + `BATCH_MANIFEST: ...`

**`status`**：
1. 加载 manifest（**无锁**，只读；manifest 原子写入保证一致性）
2. 逐段轮询（`h3_submit.py --resume <pid>`）
3. `--json` 输出机器可读 JSON
4. 幂等：已完成段跳过
5. 输出性能统计：`总耗时 82s，平均每段 20s`

**`retry`**：
1. 加载 manifest，仅重新提交指定段（state=failed/timeout）
2. 使用 `--force-new` 绕过 breakpoint
3. retry 前检查旧输出，备份后删除
4. 更新 manifest

**文件锁**：`workflows/.batch_lock`
- submit/retry 获取**独占锁**
- status **无锁**（只读 manifest）

### 新建 `tools.py` — `BatchSubmit` 工具
- 参数：stage, images, resolution, seconds, prompt, dry_run
- `subprocess.run([sys.executable, "runs/h3_batch.py", "submit", ...])`
- timeout 300s
- 注册到 TOOL_NAMES

### SYSTEM_MESSAGE 替换多图转场段
```
═══ 多图转场 ═══
N 张图 → 一次 batch_submit(stage=flf2v, images=逗号分隔) 提交全部 N-1 段；
然后 run_script("h3_batch.py", "status --wait") 等待并取回全部产物。
部分段失败时：run_script("h3_batch.py", "retry --batch <dir> --segments <idx>")。
禁止逐段手动提交。
```

---

## Phase 5: P2 — 任务级素材隔离

### `ui_app.py`
- 模块级 `_pending_batch_id: str | None = None`
- `_upload()` 成功后 `_pending_batch_id = batch_id`
- `send()` 开头：`turn_state.begin_turn(batch_id=_pending_batch_id)`，然后清空
- `ingest_upload()` 返回 `(msg, previews, batch_id, invalid_details)`
- `batch_id` 使用 `secrets.token_hex(4)` 避免同秒冲突

### `refimage.py` — `cmd_list`
- `--batch <id>|latest` 和 `--recent <minutes>` 过滤
- 无 active batch 时默认 `--batch latest`（最近完整批次，非时间窗口）
- 打印头部：`批次过滤: batch=<id>（N 项）`
- 0 结果提示：`无匹配，去掉 --batch 查看全部`
- **缓存**：`(mtime, size)` 联合校验 log.jsonl 映射
- `legacy` 批次在 `batch=all` 时明确标记

### `tools.py` — `ListReferences`
- 参数 `batch`（默认 'latest'）
- 返回上下文行：
  ```
  （当前批次 b_xxx：3 张；可用批次：b_xxx(3张,刚刚), b_yyy(5张,10分钟前)；batch=all 查全部）
  ```

---

## Phase 6: P3 — 文档状态追踪 + 预热

### 新建 `runs/agent/doc_state.py`
```python
STATE_FILE = PROJECT_ROOT / 'config' / 'doc_state.json'
_prewarm_lock = threading.Lock()
_prewarm_result_lock = threading.Lock()
_prewarm_result = {}  # {'success': bool, 'error': str, 'diff': dict}

def current_hashes() -> dict:
    """计算 SYSTEM_MESSAGE + docs/agent-reading/*.md 的 sha256"""

def check_and_update() -> dict:
    """原子写入（tmp + os.replace）"""

def prewarm():
    """单飞模式：成功才标记完成；失败允许下次重试"""
    with _prewarm_result_lock:
        if _prewarm_result.get('success'):
            return
    if not _prewarm_lock.acquire(blocking=False):
        return  # 其他线程在预热，不阻塞
    try:
        # 预热前检查 ComfyUI 是否在执行任务
        diff = check_and_update()
        if diff: refresh_read_doc_description()
        llm_mem.ensure_llm_up(timeout_s=900)
        with _prewarm_result_lock:
            _prewarm_result['success'] = True
            _prewarm_result['diff'] = diff
    except Exception as e:
        with _prewarm_result_lock:
            _prewarm_result['success'] = False
            _prewarm_result['error'] = str(e)
    finally:
        _prewarm_lock.release()
```

### 新建 `runs/agent/doc_utils.py`（避免循环依赖）
- 从 `tools.py` 提取 `scan_agent_reading_docs()` 函数
- `tools.py` 和 `doc_state.py` 共同导入

### `ui_app.py` — `_auto_new()`
- `threading.Thread(target=doc_state.prewarm, daemon=True).start()`
- 心跳/send 时检查 `_prewarm_result`，附加提示
- 失败时提示：`模型预热失败（{error}），首次对话可能较慢`
- 文档变化提示"新建会话后生效"

### `config/doc_state.json` 加入 autosync 排除

---

## 关键文件清单

| 文件 | Phase |
|---|---|
| `runs/agent/ui_app.py` | P1+P6, P5, P7, P2, P3 |
| `runs/agent/tools.py` | P7, P4, P2 |
| `runs/agent/scheduler.py` | P7, P4 |
| `runs/h3/refimage.py` | P5, P2 |
| `runs/h3/upload_watch.py` | P5 |
| `runs/h3/mediacheck.py`（新建） | P5 |
| `runs/agent/turn_state.py`（新建） | P7, P2 |
| `runs/h3_batch.py`（新建） | P4 |
| `runs/agent/doc_state.py`（新建） | P3 |
| `runs/agent/doc_utils.py`（新建） | P3 |

## 约束

- **ctx=8192**：每阶段实现后实测 token 数；SYSTEM_MESSAGE 净增 ≤50t
- **子进程隔离**：h3_batch 用 subprocess + sys.executable
- **双端同步**：新 .py 在 runs/ 下；doc_state.json 机器本地
- **向后兼容**：log.jsonl 仅增加可选字段

## 实施注意事项（终审微调）

### Phase 1
- `_upload_in_progress` 必须在 `try/finally` 中复位，防止异常锁死发送
- Phase 1 先用简单计数实现无效文件反馈，Phase 2 完成后补充具体文件名

### Phase 2
- `upload_watch.py` 扫描时排除 `_quarantine/` 路径
- `prune` 始终调用 `mediacheck.check_image_file` 完整校验，不仅凭大小预筛
- UI 上传和 watch 扫描不会同时触发同一路径（UI 走 ingest，watch 走 Open WebUI 目录），无重复风险

### Phase 3
- 重置逻辑精确化：
  - 成功 → 重置该 key 的所有计数
  - 可恢复失败 → 仅重置不可恢复计数，保持可恢复计数
  - 不可恢复失败 → 仅增加不可恢复计数
- 熔断消息提示"如已更换素材，请重新上传或稍后再试"

### Phase 4
- 文件锁粒度：submit/retry 独占锁；status 无锁（只读 manifest，manifest 原子写入）
- 子进程使用绝对路径：`Path(__file__).parent / 'h3_submit.py'`
- retry 前检查旧输出，备份后删除
- 超时后 manifest 记录 `state="timeout"` + 保留 pid

### Phase 5
- `turn_state` 按单用户单会话设计（当前 UI 不支持多用户并发）
- `batch_id` 使用 `secrets.token_hex(4)` 避免同秒冲突
- `legacy` 批次在 `batch=all` 时明确标记

### Phase 6
- `_prewarm_result` 使用 `threading.Lock` 保护读写
- 预热前检查 ComfyUI 是否在执行任务（`curl 8188`），若有则延迟
- 文档变化提示"新建会话后生效"
