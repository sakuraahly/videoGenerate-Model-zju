# send() 函数集成指南

## 概述

本文档详细说明如何将 `new_send_function.py` 中的重构版 `send()` 函数集成到 `ui_app.py` 中。

**目标**：实现 auto-continue 循环 + 任务监控 + 会话状态管理

---

## 前置条件

### 已完成的模块
- ✅ `runs/agent/session_state.py` - 会话状态管理
- ✅ `runs/agent/task_watch.py` - ComfyUI任务监控
- ✅ `runs/agent/ui_app.py` - 已添加 `extract_prompt_ids()` 函数
- ✅ `runs/agent/new_send_function.py` - 新版send()实现

### 需要修改的文件
- `runs/agent/ui_app.py` - 替换 send() 函数（行463-563）

---

## 集成步骤

### Step 1: 备份当前 send() 函数

```bash
# 在 ui_app.py 中定位 send() 函数
# 起始行：463 (def send(chat_hist, cid, user_text):)
# 结束行：563 (_active_turn.release())

# 建议先创建备份
cp runs/agent/ui_app.py runs/agent/ui_app.py.backup
```

### Step 2: 提取新 send() 函数

```bash
# new_send_function.py 包含完整的新 send() 实现
# 约200行代码，包含：
# - Auto-continue 循环（MAX_AUTO_CONTINUE = 2）
# - 任务 ID 提取（extract_prompt_ids）
# - 后台监控线程启动
# - Turn ID 令牌验证
# - 会话级停止事件
```

### Step 3: 替换 send() 函数

**方法A：手动替换（推荐用于首次集成）**

1. 打开 `ui_app.py`
2. 找到行463：`def send(chat_hist, cid, user_text):`
3. 删除从行463到行563（包含 `_active_turn.release()`）
4. 插入 `new_send_function.py` 的完整内容
5. 确保缩进正确（在 `run_app()` 函数内部，需要保持4空格缩进）

**方法B：使用脚本自动替换**

```python
# replace_send.py
import re

# 读取原文件
with open('runs/agent/ui_app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 读取新send函数
with open('runs/agent/new_send_function.py', 'r', encoding='utf-8') as f:
    new_send = f.read()

# 使用正则表达式匹配并替换 send() 函数
# 注意：需要精确匹配函数边界
pattern = r'(    def send\(chat_hist, cid, user_text\):.*?)(    finally:\s+_active_turn\.release\(\))'
replacement = new_send.strip()

# 执行替换
new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# 写入新文件
with open('runs/agent/ui_app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("send() function replaced successfully")
```

### Step 4: 调整按钮文案（Change 2）

在 `ui_app.py` 中找到按钮定义部分（约行572-573）：

```python
# 修改前
load_btn = gr.Button('加载所选')
del_btn = gr.Button('删除所选')

# 修改后
load_btn = gr.Button('加载所选历史')
del_btn = gr.Button('删除所选历史')
```

### Step 5: 可选 - 添加上传即时反馈（Change 1）

**5.1 添加 elem_id 到上传按钮**

在 `ui_app.py` 中找到上传按钮定义（约行582）：

```python
# 修改前
up_btn = gr.UploadButton('📤 上传素材（图片/视频，自动进入素材池）',
                         file_types=['image', 'video'],
                         file_count='multiple', scale=3)

# 修改后
up_btn = gr.UploadButton('📤 上传素材（图片/视频，自动进入素材池）',
                         file_types=['image', 'video'],
                         file_count='multiple', scale=3,
                         elem_id='up_btn')
```

**5.2 添加 elem_id 到状态 HTML**

```python
# 修改前
up_status = gr.HTML(UP_IDLE)

# 修改后
up_status = gr.HTML(UP_IDLE, elem_id='up_status_html')
```

**5.3 添加 JS 监听器**

在 `gr.Blocks()` 调用中添加 `js` 参数：

```python
UPLOAD_FEEDBACK_JS = '''
() => {
  const setupUploadFeedback = () => {
    const upBtn = document.getElementById('up_btn');
    if (!upBtn) return;
    const fileInput = upBtn.querySelector('input[type=file]') ||
                      upBtn.closest('.gradio-container').querySelector('input[type=file]');
    if (!fileInput) return;
    fileInput.addEventListener('change', () => {
      const statusEl = document.getElementById('up_status_html');
      if (statusEl) statusEl.innerHTML = '<span style="color:#8a6d1a">⏳ 文件传输中…</span>';
    });
  };
  setTimeout(setupUploadFeedback, 500);
}
'''

# 在 Blocks 创建时
with gr.Blocks(title='H3 视频生成助手', theme=gr.themes.Soft(), js=UPLOAD_FEEDBACK_JS) as demo:
```

### Step 6: 验证语法

```bash
python -m py_compile runs/agent/ui_app.py
echo $?  # 应该输出 0
```

### Step 7: 本地测试

```bash
# 在 Windows 上启动 agent
cd D:\MY_CODING_PROGRAM\videoGenerate-Model-zju
source ~/qwen-agent-venv/Scripts/activate  # 或相应路径
python runs/agent/scheduler.py

# 访问 http://localhost:7860
# 测试以下场景：
# 1. 上传大文件 → 观察"文件传输中"是否立即出现
# 2. 发送消息 → 观察 auto-continue 是否工作
# 3. 提交任务 → 观察后台监控是否显示进度
```

### Step 8: 部署到 spark

```bash
# 1. Commit
git add runs/agent/ui_app.py
git commit -m "feat(agent): 集成 send() 重构（auto-continue + 监控）"

# 2. Push
git push origin master

# 3. Sync
python runs/sync_to_spark.py

# 4. Restart agent on spark
ssh spark "tmux kill-session -t qwen-agent"
ssh spark "tmux new-session -d -s qwen-agent 'cd ~/videoGenerate-Model-zju && source ~/qwen-agent-venv/bin/activate && python ~/Qwen3.8-27B/start_qwen_agent.py'"

# 5. Verify
sleep 3
curl http://127.0.0.1:7860 | head -5
```

---

## 关键代码说明

### Auto-continue 循环逻辑

```python
for attempt in range(MAX_AUTO_CONTINUE + 1):  # 最多3次（0,1,2）
    # 1. 执行一轮对话
    # 2. 提取任务ID
    # 3. 判断是否需要续接
    if not needs_continuation or attempt >= MAX_AUTO_CONTINUE:
        break
    # 4. 自动续接：添加system消息
    msgs.append({"role": "system", "content": '[系统自动续接]...'})
```

### 任务提取

```python
prompt_ids = extract_prompt_ids(final_text)
if prompt_ids:
    tasks = [{'prompt_id': pid, 'type': 'single'} for pid in prompt_ids]
    all_pending_tasks.extend(tasks)
```

### 监控线程启动

```python
if all_pending_tasks and check_turn_valid(cid, current_turn_id):
    monitor_thread = threading.Thread(
        target=_monitor_worker,
        args=(cid, current_turn_id, monitor_queue, stop_event),
        daemon=True
    )
    monitor_thread.start()
```

---

## 常见问题

### Q1: 替换后出现缩进错误
**A**: 确保新 send() 函数的缩进与原函数一致（4空格）。检查所有嵌套函数和yield语句。

### Q2: ImportError: cannot import session_state
**A**: 确认 session_state.py 已在 runs/agent/ 目录下，且 __init__.py 存在。

### Q3: 监控线程不工作
**A**: 检查：
1. task_watch.py 是否正确导入
2. ComfyUI 是否在运行（端口8188）
3. 是否有任务被提取（查看日志）

### Q4: Auto-continue 不触发
**A**: 检查：
1. ABORT_MARKERS 是否包含空字符串（会导致永远不续接）
2. final_text 是否为空
3. 是否有 prompt_ids（有任务ID则不续接）

---

## 回滚方案

如果集成后出现问题，可以快速回滚：

```bash
# 恢复备份
cp runs/agent/ui_app.py.backup runs/agent/ui_app.py

# 重启 agent
# ...（同上）
```

---

## 验收标准

集成完成后，应满足以下条件：

- [ ] 语法检查通过（py_compile）
- [ ] Agent 正常启动（端口7860响应）
- [ ] 上传大文件时"文件传输中"立即显示（如实现Change 1）
- [ ] 按钮文案为"加载所选历史"/"删除所选历史"
- [ ] Auto-continue 在模型中途停止时自动续接（最多2次）
- [ ] 任务提交后后台监控显示进度
- [ ] 多会话隔离正常（新turn不影响其他会话）
- [ ] 中止按钮只影响当前会话

---

## 下一步优化

集成成功后，可以考虑：

1. **性能优化**：调整监控频率（MONITOR_SEC）
2. **错误处理**：完善监控异常恢复
3. **用户体验**：添加任务取消功能
4. **日志记录**：记录 auto-continue 触发次数和原因

---

**文档版本**: v1.0  
**最后更新**: 2026-09-04  
**维护者**: Qoder Agent
