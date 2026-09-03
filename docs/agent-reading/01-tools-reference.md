# Agent 工具参考

## 1. call_comfyui — 提交视频生成任务（提交/等待分离）

```
call_comfyui(stage, prompt, resolution, seconds, seed,
             dry_run, wait_until_done, force_new)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| stage | str | t2v / i2v / r2v / flf2v |
| prompt | str | 正向提示词（需遵循提示词工程规则） |
| resolution | str | 360p-768p，默认 720p |
| seconds | float | 时长，默认 5 |
| dry_run | bool | true=只验证不提交 |
| force_new | bool | true=忽略遗留断点 |
| wait_until_done | bool | 默认 **false**：提交即返回 prompt_id（后台运行）；true=阻塞等待完成（数分钟） |

**重要（提交/等待分离）**：默认调用只负责“提交”，立即返回
`TASK_SUBMITTED: <prompt_id>`，**不会**长时间阻塞，也不会出现“任务其实在跑却被
超时误报”的情况。生成在 ComfyUI 后台进行：
- 需要完成结果时，用 **run_script** 运行 `runs/h3_submit.py`（**不带任何参数**）——
  会自动续传等待原任务直到完成，输出 `REMOTE_VIDEO_PATH:` 与（spark-local 下）
  `LOCAL_OUTPUT:`（视频已保存到项目 outputs/）。
- 若任务仍在生成，续传会一直等到出片为止（长任务可分多次询问进度）。

**返回值**：成功返回任务信息（含 prompt_id），失败返回错误消息。

## 2. run_script — 运行白名单脚本

```
run_script(script, args)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| script | str | 脚本路径（相对于 runs/） |
| args | str | 命令行参数 |

**可用脚本**：
- `h3_submit.py` — 视频生成（同 call_comfyui 的底层实现）
- `h3_text2img.py` — 文生图：`--prompt "描述" --output 名称 [--resolution 720p]`
- `h3/idea2prompts.py` — 提示词生成：`--idea "创意" [--workflow 类型] [--force]`
- `h3/refimage.py` — 参考素材：
  - `list [--pool in|up|out] [--name 关键字] [--limit N]`（默认仅图片、按池限量，
    不会像以前那样被 out 池刷屏截断）
  - `use --name <id|文件名> --stage r2v --slot N`（**r2v 支持多张参考图**：本地模板
    默认 8 个槽位 slot0..7，人物/场景/道具各占一个；未用槽位为禁用占位，
    use 自动启用并接线。用 `use --info --stage r2v` 查看槽位与状态；还要更多槽用
    `grow --stage r2v --total N` 扩。i2v/flf2v 为单槽，默认 slot 0）
  - `promote --name <id|文件名>`；`use --undo`（git 还原模板）

**安全限制**：
- 只允许 .py 文件
- 路径必须在 runs/ 目录内
- 输出截断 ≤5000 字符
- 超时 120 秒

## 3. modify_workflow — 修改工作流 JSON

```
modify_workflow(workflow_file, changes)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| workflow_file | str | 工作流JSON路径（相对于 workflows/remote_workflows/） |
| changes | dict | {节点ID(str): {要修改的字段}} |

**注意**：节点ID是字符串形式的整数（如 "5", "12"）。
ComfyUI 工作流格式是 `{"nodes": [{"id": 5, "type": "...", ...}]}`，不是扁平字典。

**格式对照（容易混淆）**：本地镜像模板是 **UI 格式**——LoadImage 的图名存在
`widgets_values[0]`；引擎在线转换后（dry_run/提交时打印的 API 图）同一字段显示为
`inputs.image`。两者是同一个东西：**改模板一律用 widgets_values**。

**示例**：修改 LoadImage 节点的图片路径
```python
modify_workflow(
    workflow_file="video_minimax_h3_i2v.json",
    changes={"5": {"widgets_values": ["new_image.png"]}}
)
```
> 日常换参考图更推荐 `run_script("h3/refimage.py", "use --name <id> --stage r2v --slot 1")`——
> 它会自动 promote 到 ComfyUI input 并精确改对应 LoadImage 槽位。
