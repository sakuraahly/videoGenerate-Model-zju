# 清理 cleanup(agent 用法,2026-09-10)

## 什么时候用
- 用户说"清理/磁盘满了/日志太多/清一下临时文件" → `run_script(agent/cleanup.py, --status)` 先看报告,
  确认后 `run_script(agent/cleanup.py, --apply)` 执行。
- **默认 dry-run**:不加 --apply 只报告,不删任何文件。

## 清理范围(默认)
| 类别 | 规则 |
|---|---|
| 运行日志 logs/run_*.log | 保留最近 200 个且 3 天内 |
| workflows/h3_* 工作流目录 | 保留最近 100 个 |
| /tmp 项目临时(lipsync_chain、gfp_frames、pip-*、story_film* 等) | 保留 1 天内 |
| __pycache__/*.pyc | 全清 |
| ComfyUI output/video 旧产物 | **默认不动**；加 --include-comfy 才清（保留最近 150） |
| 卡死进程（>2h 的 ffmpeg/cosy） | 只报告；加 --kill-stuck 才杀 |

## 红线(永不触碰)
uploads/ 素材、outputs/ 交付产物、assets/、models/、.git、config/、源码(.py 本身)。
路径经过白名单根 + 保护规则双重校验（Windows 反斜杠也已规范化处理）。

## 参数
- `--status`(默认) / `--apply`
- `--keep-logs N` `--keep-log-days N` `--keep-workflows N` `--keep-tmp-days N`
- `--include-comfy`(清 ComfyUI 旧产物) `--keep-comfy N`
- `--kill-stuck`(清卡死进程, 需与 --apply 同用) `--json`

## 定时
`config/agent-tasks.json` 的 `sched-cleanup`(每周, UTC 周六 20:30 = 北京周日 04:30)自动 `--apply`。
