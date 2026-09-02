# ComfyUI 启动与访问指南

本文档说明如何在 DGX Spark 上启动 ComfyUI 服务，并从本地 Windows 机器通过 SSH 隧道访问其 Web UI。

> 实测环境：DGX Spark（aarch64 / NVIDIA GB10 / 128 GB 统一内存），ComfyUI 安装路径 `~/ai/ComfyUI`，虚拟环境 `~/ai/venv`，SSH 别名 `spark`。

---

## 1. 当前运行方式概览

ComfyUI 在 Spark 上以**手动后台进程**方式运行（**不是** systemd 服务）。启动命令：

```bash
cd ~/ai/ComfyUI && \
nohup ~/ai/venv/bin/python main.py \
  --listen 127.0.0.1 \
  --port 8188 \
  --disable-auto-launch \
  --reserve-vram 12 \
  > ~/ai/ComfyUI/nohup.out 2>&1 &
```

关键参数含义：

| 参数 | 作用 |
|---|---|
| `--listen 127.0.0.1` | 只监听本地回环，外部无法直连，必须走 SSH 隧道（安全） |
| `--port 8188` | Web UI 与 API 端口 |
| `--disable-auto-launch` | 不自动弹浏览器（服务器无桌面） |
| `--reserve-vram 12` | 预留 12 GB 显存，避免与 H3 推理冲突（可按需调整） |

---

## 2. 在 Spark 上启动 ComfyUI

### 2.1 检查是否已在运行

```bash
ssh spark "pgrep -af 'main.py' && ss -tlnp | grep 8188"
```

如果看到类似输出，说明已经在跑，跳到第 3 节：

```
3469 /home/<用户名>/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 ...
LISTEN 0 128  127.0.0.1:8188  0.0.0.0:*  users:(("python",pid=3469,fd=44))
```

### 2.2 如未运行，启动它

推荐使用 **tmux**（比 nohup 更易调试，可随时 `attach` 查看日志）：

```bash
ssh spark
tmux new-session -d -s comfyui \
  "cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py \
   --listen 127.0.0.1 --port 8188 \
   --disable-auto-launch --reserve-vram 12"
```

退出 SSH 后进程仍会持续运行。如需查看实时日志：

```bash
ssh spark
tmux attach -t comfyui
# Ctrl+B D 退出 tmux 但不杀进程
```

### 2.3 验证服务就绪

```bash
ssh spark "curl -s http://127.0.0.1:8188/system_stats | head -c 200"
```

返回 JSON（含 `devices`、`python_version` 等字段）即表示正常。

---

## 3. 在本地 Windows 建立 SSH 隧道

因为 ComfyUI 监听 `127.0.0.1`，本机无法直接访问，必须在本地建立端口转发。

### 3.1 前台模式（推荐，关闭即断开隧道）

```bash
ssh -L 8188:localhost:8188 spark
```

保持此终端打开，浏览器访问 **http://localhost:8188**。

### 3.2 后台模式（适合自动化或脚本）

```bash
ssh -o ExitOnForwardFailure=yes -N -f -L 8188:localhost:8188 spark
```

- `-N`：不执行远端命令，只做转发
- `-f`：认证成功后转入后台
- `ExitOnForwardFailure=yes`：端口绑定失败时直接退出，避免"假连接"

验证隧道：

```bash
netstat -ano | findstr ":8188"
```

应能看到 `127.0.0.1:8188  LISTENING`。

### 3.3 自动重连隧道（推荐，应对 NAT 空闲断开）

到 spark 的路径经过 NAT/防火墙，会主动切断空闲 TCP 连接，普通 `ssh -N -L ...` 跑几分钟就会无声断开。仓库里提供了一个自动重连包装脚本：

```
runs/tunnel/spark-comfyui-tunnel.sh
```

启动（后台、可脱离终端）：
```bash
bash runs/tunnel/spark-comfyui-tunnel.sh &
disown
```

脚本行为：
- 每 10 秒 SSH keepalive，30 秒内无回应视为断连
- 断连后 2 秒自动重连，循环直到手动停止
- 日志写到 `runs/tunnel/tunnel.log`（已被 `runs/**/*.log` 排除在 git 外）

停止：
```bash
pkill -f spark-comfyui-tunnel
```

> 如果不想用脚本，至少在每次手动隧道上加 `-o ServerAliveInterval=10 -o ServerAliveCountMax=3`，并把 `~/.ssh/config` 的 spark 段改成同样的值。

### 3.4 关闭后台隧道

```bash
# Windows Git Bash
taskkill /F /IM ssh.exe        # 粗暴但有效（会杀掉所有 ssh）

# 或精准杀：先找到 PID，再 taskkill /PID <pid> /F
```

---

## 4. 常见问题排查

### 4.1 `Connection refused` / 隧道建立后浏览器打不开

1. 确认 Spark 上 ComfyUI 在跑：`ssh spark "ss -tlnp | grep 8188"`
2. 确认本地端口未被占用：`netstat -ano | findstr ":8188"`
3. 若本地 8188 已被别的程序占用，换本地端口：`ssh -L 18188:localhost:8188 spark`，浏览器访问 `http://localhost:18188`

### 4.2 隧道建立后过一段时间就断开 / `Connection closed by <IP> port <N>`

典型表现：隧道开了一会就无声断开，浏览器卡住，重连时 SSH 报 `Connection closed by <NAT跳板机IP> port XXXXX`。
原因：本地与 Spark 之间的 NAT / 防火墙设备会清理空闲 TCP 连接（通常几分钟无流量即断）。

**修复**：启用 SSH keepalive，每 30 秒发一次心跳。

一次性（命令行）：
```bash
ssh -o ServerAliveInterval=30 -o ServerAliveCountMax=6 -N -L 8188:localhost:8188 spark
```
（连续 6 次无回应才断开，约 3 分钟容忍窗口。）

持久化（推荐）：在 `~/.ssh/config` 中为 spark 加 keepalive：
```
Host spark
    ServerAliveInterval 30
    ServerAliveCountMax 6
```
之后所有 `ssh spark` 与 `-L ... spark` 转发都自动受益，无需每次传 `-o`。

附加建议：
- 隧道加 `-o ExitOnForwardFailure=yes`，本地端口被占用时直接报错而不是静默空跑
- 前台模式（不加 `-f`）运行，能在终端看到断连信息，便于排查

### 4.3 ComfyUI 启动失败 / 端口被占用

```bash
ssh spark "ss -tlnp | grep 8188"          # 看谁占着
ssh spark "pkill -f 'python main.py'"    # 杀掉残留进程（慎用，确保只杀 ComfyUI）
```

### 4.4 GPU 显存不足

H3 推理峰值约 36 GB，`--reserve-vram 12` 是给非推理期预留的。若同时跑其他模型导致 OOM，把 `--reserve-vram` 调大，或在提交 H3 任务前重启 ComfyUI 释放显存。

---

## 5. 快速命令速查

| 操作 | 命令 |
|---|---|
| 查 ComfyUI 进程 | `ssh spark "pgrep -af main.py"` |
| 查端口占用 | `ssh spark "ss -tlnp \| grep 8188"` |
| 验证 API 可用 | `ssh spark "curl -s http://127.0.0.1:8188/system_stats"` |
| tmux 启动 ComfyUI | `ssh spark "tmux new-session -d -s comfyui 'cd ~/ai/ComfyUI && ~/ai/venv/bin/python main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch --reserve-vram 12'"` |
| 进入 ComfyUI tmux | `ssh spark "tmux attach -t comfyui"` |
| 停止 ComfyUI | `ssh spark "pkill -f 'python main.py'"` |
| 开本地隧道（前台） | `ssh -L 8188:localhost:8188 spark` |
| 开本地隧道（后台） | `ssh -N -f -L 8188:localhost:8188 spark` |
| 浏览器访问 | **http://localhost:8188** |

---

## 6. 与 H3 视频生成的关系

ComfyUI 是 H3 工作流的调度与 Web UI 入口：
- 模型文件见 `docs/h3-workflow-architecture.md`
- 提交任务、监控、下载视频见 `docs/h3-manual-operations.md`

只要 ComfyUI 在跑且隧道通畅，即可通过浏览器加载工作流并提交 H3 生成任务。
