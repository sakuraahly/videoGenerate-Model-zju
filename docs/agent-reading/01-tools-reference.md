# Agent 工具参考

## 1. call_comfyui — 提交视频生成任务

```
call_comfyui(stage, prompt, negative_prompt, image, image2,
             resolution, seconds, seed, dry_run, force_new, workflow_file)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| stage | str | t2v / i2v / r2v / flf2v |
| prompt | str | 正向提示词（需遵循提示词工程规则） |
| negative_prompt | str | 负向提示词（可选） |
| image | str | 输入图片路径（i2v/r2v/flf2v 需要） |
| image2 | str | 第二张图片（r2v 可选 / flf2v 末帧） |
| resolution | str | 360p-768p，默认 720p |
| seconds | float | 时长，默认 5 |
| dry_run | bool | true=只验证不提交 |
| force_new | bool | true=忽略断点续传 |

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

**示例**：修改 LoadImage 节点的图片路径
```python
modify_workflow(
    workflow_file="video_minimax_h3_i2v.json",
    changes={"5": {"widgets_values": ["new_image.png"]}}
)
```
