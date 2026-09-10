#!/usr/bin/env python3
"""H3 视频生成工坊 — 魔搭创空间应用（v2.4：Agent = 工具集 + 外置大脑）。

结构（2026-09-10 重构：v1.x 的展示页 → 专业创作台）：
  Tab1 创作台：任务类型 / 提示词 / 参考图上传 / 参数（分辨率·时长·音色·字幕）→ 提交 → 任务区（状态·预览·下载·历史）
  Tab2 样片墙：本机生成样片（可播放）
  Tab3 能力与部署：能力点、制作流程、部署与"真实生成"说明
后端（studio/backend.py）三实现：demo（默认，免费 CPU）/ remote（引擎网关）/ local（空间内 GPU 模型）。
环境变量：STUDIO_BACKEND=demo|remote|local（默认 auto）；REMOTE_API + STUDIO_TOKEN 走远程。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"
sys.path.insert(0, str(HERE))

from backend import pick_backend  # noqa: E402

DEFAULT_SHOW = {
    "title": "H3 视频生成工坊",
    "tagline": "一句创意 / 一张参考图 / 一句台词 → 本地大模型生成 → 台词·字幕·口型成品链 → ASR 验收交付",
    "hero_points": [
        "文生视频 / 图生视频 / 多参考图连贯 / 首末帧转场",
        "说话镜头：一句台词→H3 自适应音色亲口说出（音画同时长）+ ASR 验收",
        "故事片主控：剧本→分镜→台词→成片 单命令出片（9 段连贯·可断点续跑）",
        "台词先行+发音回环；字幕可选；ComfyUI 全链一体化；1280×736/4x 超分档",
    ],
    "flow_steps": [
        "① 灵感：一句话剧情；也可上传参考图锁定场景/角色/道具",
        "② 提示词：英文提示词+参考图契约（<Picture N> 全片锁定）+故事背景/角色形象卡自动注入",
        "③ 生成：ComfyUI + MiniMax H3 本地推理（本机 GPU，日间≤768p，夜间 1080p 档）",
        "④ 成品链：台词先行（剧本台词表）→ CosyVoice2 真台词 → 口型同步 → 字幕=台词原文烧录 → 旁白垫轨 → 整脸无框修复",
        "⑤ 验收：SenseVoice ASR 双轨验真（台词窗/旁白窗；发音回环不达标自动用发音写法重试）→ 交付命名归档",
    ],
    "samples": [
        {"file": "01_direct_720p.mp4", "cover": "01_direct_720p_cover.jpg",
         "title": "720p 直出 · 病房戏", "desc": "1280×736/24fps/5.17s；剧情直出+成品链", "style": "电影感"},
        {"file": "02_ref2v_720p.mp4", "cover": "02_ref2v_720p_cover.jpg",
         "title": "多参考图连贯（r2v）", "desc": "3 张参考图（角色/场景）全片锁定；720p", "style": "电影感"},
        {"file": "03_talk_nobox.mp4", "cover": "03_talk_nobox_cover.jpg",
         "title": "真台词 · 无框终版", "desc": "角色真的说出设定台词；整脸重渲染无贴皮框", "style": "真实"},
        {"file": "04_keep_orig.mp4", "cover": "04_keep_orig_cover.jpg",
         "title": "角色原声保留 · 旁白错开", "desc": "台词=角色原声+字幕；旁白独立垫轨（不干扰话语）", "style": "纪录片"},
        {"file": "05_comfy_chain.mp4", "cover": "05_comfy_chain_cover.jpg",
         "title": "ComfyUI 全链一体化", "desc": "生成→48fps 插帧→整脸修复→配音字幕→ASR 全链", "style": "真实"},
        {"file": "06_rife_48fps.mp4", "cover": "06_rife_48fps_cover.jpg",
         "title": "RIFE 48fps 插帧", "desc": "24fps→48fps 高帧率（插帧后画面顺滑）", "style": "纪录片"},
        {"file": "07_story_script.mp4", "cover": "07_story_script_cover.jpg",
         "title": "剧本→故事片（主控）", "desc": "希区柯克《油价涨了》短篇：剧本 JSON→9 段连贯+4 句真台词字幕；断点续跑", "style": "电影感"},
        {"file": "08_talk_one.mp4", "cover": "08_talk_one_cover.jpg",
         "title": "说话镜头（H3 自适应音色）", "desc": "一句台词→按语音时长生成→H3 自己选音色说话（音画同时长）+ ASR 验收 1.000", "style": "真实"},
    ],
    "voices": [("H3 自适应（按人物形象）", "h3"), ("中文·男声 yunxi", "yunxi"),
               ("中文·女声 xiaoxiao", "xiaoxiao"), ("英文·男声 daler", "daler"),
               ("英文·女声 aria", "aria")],
    "styles": ["电影感", "真实", "纪录片"],
    "footer": "免费 CPU 档=演示模式（不产生任务）；真实生成需 GPU 硬件档或配置引擎网关（见「能力与部署」）。",
}


def load_show() -> dict:
    try:
        import yaml
        cfg = HERE / "config.yaml"
        if cfg.is_file():
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            show = {k: v for k, v in data.items() if k not in ("sdk", "app_file", "sdk_version")}
            show.update(data.get("showcase") or {})
            for k, v in DEFAULT_SHOW.items():
                show.setdefault(k, v)
            return show
    except Exception:  # noqa: BLE001
        pass
    return dict(DEFAULT_SHOW)


def agent_step(user_text: str, history, image_path=None, client=None) -> dict:
    """Agent 一步（模块级，便于单测）：返回 {'history','trace','video','job','payload'}。

    行为：调用 agent_client.AgentClient().answer()（= 外置大脑决策 + 工具集执行），
    把「工具选择 + 参数 + 将要发出的请求体 + 调用轨迹」写进对话与轨迹区；
    异常兜底成人话，绝不抛给用户。参考图（image_path）会自动转 data URL 注入工具参数。
    """
    history = list(history or [])
    if not (user_text or '').strip():
        return {'history': history, 'trace': None, 'video': None, 'job': None}
    try:
        from agent_client import AgentClient
        out = (client or AgentClient()).answer(user_text, history, image_path=image_path or '')
    except Exception as e:  # noqa: BLE001
        out = {'say': '（agent 层异常：%s）' % str(e)[:150], 'kind': 'error'}
    kind = out.get('kind')
    reply = out.get('say') or ''
    if kind == 'answer':
        reply += "\n\n" + (out.get('text') or '')
    elif kind == 'demo':
        reply += ("\n\n**工具** `%s` → 即将发给视频生成接口的请求体（预览）：\n\n```json\n%s\n```\n\n"
                  "> 演示模式：尚未接入外部生成接口。到「设置 → 变量 / 密钥」填 "
                  "`ENGINE_BASE_URL`（可选 `LLM_*`）后，这里会真实出片。"
                  % (out.get('tool'), json.dumps(out.get('payload') or {}, ensure_ascii=False, indent=2)))
    elif kind == 'remote':
        reply += "\n\n已提交外部生成服务（任务 `%s`）。" % out.get('task')
        if out.get('video'):
            reply += "\n\n成片：%s" % out['video']
    else:
        reply += "\n\n" + (out.get('text') or '')
    history = history + [{"role": "user", "content": user_text},
                         {"role": "assistant", "content": reply}]
    tr = out.get('trace') or {}
    trace_md = ("**模式**：%s　**工具**：%s\n\n```json\n%s\n```"
                % (out.get('mode', '-'), tr.get('tool') or '-',
                   json.dumps(tr, ensure_ascii=False, indent=2)[:1500]))
    job = None
    if kind == 'remote' and out.get('task'):
        job = {"id": str(out['task']), "tool": tr.get('tool') or '-', "status": "running",
               "ts": time.strftime("%H:%M:%S"), "video": out.get('video') or None}
    # 预览优先用空间本地文件(外部 CDN 域名可能被前端校验拦掉)；没有则退回原链接
    preview = out.get('video_local') or out.get('video') or None
    return {'history': history, 'trace': trace_md, 'video': preview,
            'job': job, 'payload': out.get('payload')}


def jobs_table(jobs, client=None, refresh: bool = False) -> str:
    """任务面板渲染（会话内任务 + 可选向外部接口刷新状态）。"""
    jobs = list(jobs or [])
    if not jobs:
        return "_（本会话还没有任务：在下面说一句需求即可）_"
    if refresh and client is not None:
        for j in jobs:
            if j.get('status') in ('running', 'queued', 'unknown'):
                st = client.poll_job(j['id'])
                j['status'] = st.get('status') or j['status']
                if st.get('video_url'):
                    j['video'] = st['video_url']
    rows = ["| 时间 | 任务号 | 工具 | 状态 | 成片 |", "|---|---|---|---|---|"]
    for j in jobs[-12:]:
        v = j.get('video')
        rows.append("| %s | `%s` | %s | %s | %s |"
                    % (j.get('ts', '-'), j.get('id', '-'), j.get('tool', '-'),
                       j.get('status', '-'), ("[打开](%s)" % v) if v else '-'))
    return "\n".join(rows)


def build_app(show: dict):
    import gradio as gr

    backend = pick_backend()
    job_history: list = []

    def _asset(name):
        p = ASSETS / name
        return str(p) if name and p.is_file() else None

    def _sample_for(kind):
        key = {"talk": "08_", "story": "07_", "t2v": "01_", "i2v": "02_"}.get(kind, "01_")
        return next((s for s in show["samples"] if s["file"].startswith(key)), show["samples"][0])

    # ---------------- 创作台 ----------------
    def submit_job(kind, prompt, images, resolution, seconds, voice_src, voice, subtitle, negative):
        sel = {"文生视频": "t2v", "图生视频": "i2v", "说话镜头": "talk", "剧本故事片": "story"}
        k = sel.get(kind, "t2v")
        if not (prompt or "").strip() and k != "i2v":
            return ("⚠️ 请先填写创意/提示词。", None, None,
                    _hist_md(), gr.update())
        imgs = [Path(f).name for f in (images or [])]
        # 语音来源：默认=模型原生语音（自适应音色，不做 TTS 替换）；仅显式选择时才用本地 TTS 音色
        native = str(voice_src or '').startswith('模型原生')
        voice_key = 'h3（模型原生·自适应音色）' if native else dict(show["voices"]).get(voice, voice)
        task = {"kind": k, "prompt": prompt, "images": ", ".join(imgs) or None,
                "resolution": resolution, "seconds": seconds, "voice": voice_key,
                "subtitle": bool(subtitle), "negative": negative}
        t0 = time.time()
        try:
            res = backend.submit(task)
        except Exception as e:  # noqa: BLE001
            return ("❌ 提交失败：%s" % str(e)[:300], None, None, _hist_md(), gr.update())
        dt = time.time() - t0
        rec = _sample_for(k)
        job_history.append({"id": res.get("job_id"), "kind": sel.get(kind, k),
                            "state": res.get("state"), "ts": time.strftime("%H:%M:%S")})
        echo = res.get("echo") or {}
        rows = "\n".join("| %s | %s |" % (kk, vv) for kk, vv in echo.items())
        md = (f"### {'🧪 演示结果' if backend.name == 'demo' else '🚀 已提交'}\n\n"
              f"**任务类型**：{res.get('title')}　**任务号**：`{res.get('job_id')}`\n\n"
              f"| 参数 | 值 |\n|---|---|\n{rows}\n\n"
              f"**规格**：{res.get('spec')}\n\n"
              f"> {backend.note if backend.name == 'demo' else '任务已交给引擎；下方可查看状态与成片。'}\n\n"
              f"_耗时 {dt:.2f}s_")
        video = _asset(rec["file"]) if backend.name != 'remote' else None
        files = None
        if backend.name != 'demo':
            try:
                st = backend.poll(res['job_id'])
                video = st.get('video') or video
            except Exception:  # noqa: BLE001
                pass
        return md, video, files, _hist_md(), gr.update(value="")

    def _hist_md():
        if not job_history:
            return "_（暂无任务记录）_"
        return "\n".join("| %s | %s | %s |" % (h["ts"], h["kind"], h["state"]) for h in job_history[-10:])

    # Gradio 6.x：theme 从 Blocks 移到 launch()
    with gr.Blocks(title=show["title"]) as demo:
        gr.Markdown(f"## 🎬 {show['title']}\n\n{show['tagline']}")

        with gr.Tabs():
            with gr.Tab("🤖 Agent 对话"):
                gr.Markdown("### 直接说需求：agent 自己选工具、定参数、调外部生成接口")
                try:
                    from agent_client import AgentClient as _AC
                    _st = _AC().status()
                except Exception:  # noqa: BLE001
                    _st = {"mode": "demo-planner", "tools": [], "brain": False, "engine": False,
                           "model": "-", "system_prompt": "default"}
                # 三态要说清楚：能不能出片只看视频接口，别拿"大脑已接"糊弄用户
                if _st.get('engine'):
                    _mode_txt = "✅ 已接入视频生成接口 —— 可以真实出片"
                elif _st.get('brain'):
                    _mode_txt = ("🧠 外置大脑已接入（决策由真实模型完成）；**视频生成接口未接** → "
                                 "当前是演示预览，不做假动作")
                else:
                    _mode_txt = "🧪 规划演示模式（未配置外部接口：仍完整展示工具决策 + 请求体预览）"
                gr.Markdown("**当前模式**：%s　|　**外置大脑**：%s　|　**视频生成接口**：%s"
                            % (_mode_txt,
                               ("已配置（%s）" % _st.get('model')) if _st.get('brain')
                               else "未配置（自动用内置规则规划器）",
                               "已配置" if _st.get('engine') else "未配置"))
                gr.Markdown("**工具集**（agent 的手脚，全部走接口）：%s\n\n"
                            "_本空间不部署模型：大脑由 `LLM_*` 接口控制，出片由 `ENGINE_*` 接口控制；"
                            "接口清单见「能力与部署」页与仓库 studio/接口说明.md。_"
                            % "、".join("`%s`" % t for t in (_st.get('tools') or [])))
                with gr.Row():
                    with gr.Column(scale=3):
                        chatbot = gr.Chatbot(label="对话", height=330)  # Gradio 6.x 默认 messages 格式
                        with gr.Row():
                            msg = gr.Textbox(label="说点什么", scale=4,
                                             placeholder="例：让参考图里的老人说一句“天冷了，快进屋坐坐吧。”"
                                                         "／做一段雨夜老屋门口有猫的 5 秒镜头")
                            send = gr.Button("发送", variant="primary", scale=1)
                        with gr.Row():
                            ex1 = gr.Button("示例·说话镜头", size="sm")
                            ex2 = gr.Button("示例·5 秒镜头", size="sm")
                            ex3 = gr.Button("示例·故事片", size="sm")
                            clr = gr.Button("清空对话", size="sm")
                    with gr.Column(scale=2):
                        ref_img = gr.Image(label="参考图（说话镜头建议上传：人物形象）", type="filepath",
                                           height=200)
                        jobs_state = gr.State([])
                        agent_video = gr.Video(label="本轮产物（若有）", interactive=False)
                        jobs_md = gr.Markdown("_（本会话还没有任务：在下面说一句需求即可）_")
                        refresh = gr.Button("🔄 刷新任务状态", size="sm")
                        trace_md = gr.Markdown("_（这里会显示 agent 的工具调用轨迹）_")

                TRACE_IDLE = "_（这里会显示 agent 的工具调用轨迹）_"
                JOBS_IDLE = "_（本会话还没有任务：在下面说一句需求即可）_"
                STEP_OUT = [chatbot, trace_md, agent_video, msg, jobs_state, jobs_md]

                def _step(user_text, history, ref, jobs):
                    """UI 包装：调用模块级 agent_step（可单测）；输出 6 项，组件不重复。"""
                    r = agent_step(user_text, history, image_path=ref)
                    jobs = list(jobs or [])
                    if r.get('job'):
                        jobs.append(r['job'])
                    return (r['history'], r.get('trace') or TRACE_IDLE, r.get('video') or None,
                            gr.update(value=""), jobs, jobs_table(jobs))

                def _refresh(jobs):
                    try:
                        from agent_client import AgentClient as _AC2
                        return jobs_table(jobs, _AC2(), refresh=True), jobs
                    except Exception:  # noqa: BLE001
                        return jobs_table(jobs), jobs

                send.click(_step, [msg, chatbot, ref_img, jobs_state], STEP_OUT)
                msg.submit(_step, [msg, chatbot, ref_img, jobs_state], STEP_OUT)
                ex1.click(lambda h, r, j: _step('让参考图里的老人说一句“天冷了，快进屋坐坐吧，外面风大。”', h, r, j),
                          [chatbot, ref_img, jobs_state], STEP_OUT)
                ex2.click(lambda h, r, j: _step('做一段雨夜老屋门口有猫望着门内暖光的 5 秒镜头', h, r, j),
                          [chatbot, ref_img, jobs_state], STEP_OUT)
                ex3.click(lambda h, r, j: _step('把“父子在病房道别”做成一段连贯的 3 段故事片', h, r, j),
                          [chatbot, ref_img, jobs_state], STEP_OUT)
                refresh.click(_refresh, [jobs_state], [jobs_md, jobs_state])
                clr.click(lambda: ([], TRACE_IDLE, None, JOBS_IDLE, []), None,
                          [chatbot, trace_md, agent_video, jobs_md, jobs_state])

            with gr.Tab("🎛 创作台"):
                with gr.Row():
                    with gr.Column(scale=3):
                        kind = gr.Radio(choices=["文生视频", "图生视频", "说话镜头", "剧本故事片"],
                                        value="文生视频", label="任务类型")
                        prompt = gr.Textbox(label="创意 / 提示词 / 台词", lines=4,
                                            placeholder="例：雨夜老屋门口，一只猫望着门内的暖光；"
                                                        "或（说话镜头）天冷了，快进屋坐坐吧，外面风大。")
                        images = gr.Files(label="参考图（可选，多张；图生视频必填）",
                                          file_types=["image"])
                        with gr.Row():
                            resolution = gr.Dropdown(choices=["360p", "480p", "720p", "768p"],
                                                     value="480p", label="分辨率")
                            seconds = gr.Slider(2, 15, value=5, step=1, label="时长（秒）")
                        with gr.Row():
                            voice_src = gr.Radio(choices=["模型原生语音（推荐·自适应音色）", "指定本地 TTS 音色"],
                                                 value="模型原生语音（推荐·自适应音色）", label="语音来源")
                            subtitle = gr.Checkbox(value=False, label="额外烧录后期字幕（模型自带画面字幕，一般不用勾）")
                        with gr.Accordion("高级：本地 TTS 音色（仅当上面选择「指定本地 TTS 音色」时生效）", open=False):
                            voice = gr.Dropdown(choices=[v[0] for v in show["voices"][1:]],
                                                value=show["voices"][1][0], label="TTS 音色")
                        negative = gr.Textbox(label="负面词（可选）", lines=2,
                                              placeholder="no text, no watermark, no distortion …")
                        with gr.Row():
                            submit = gr.Button("🚀 生成", variant="primary", scale=3)
                            clear = gr.Button("清空", scale=1)
                    with gr.Column(scale=2):
                        status = gr.Markdown("_等待提交…_")
                        out_video = gr.Video(label="成片预览", interactive=False)
                        out_files = gr.File(label="下载", file_count="multiple")
                        hist = gr.Markdown("_（暂无任务记录）_", label="最近任务")
                submit.click(submit_job,
                             [kind, prompt, images, resolution, seconds, voice_src, voice, subtitle, negative],
                             [status, out_video, out_files, hist, prompt])
                clear.click(lambda: ("", None, "480p", 5, "模型原生语音（推荐·自适应音色）",
                                     show["voices"][1][0], True, ""),
                            None, [prompt, images, resolution, seconds, voice_src, voice, subtitle, negative])

            with gr.Tab("🎞 样片墙"):
                gr.Markdown("### 本机生成样片（点击播放）")
                rows = [show["samples"][i:i + 3] for i in range(0, len(show["samples"]), 3)]
                for row in rows:
                    with gr.Row():
                        for s in row:
                            with gr.Column():
                                gr.Image(value=_asset(s["cover"]), label=s["title"],
                                         show_label=True, interactive=False)
                                gr.Markdown(f"**{s['title']}** — {s['desc']}")
                                gr.Video(value=_asset(s["file"]), label=s["title"], interactive=False)

            with gr.Tab("🧭 能力与部署"):
                gr.Markdown("### 能力")
                for pt in show["hero_points"]:
                    gr.Markdown(f"- {pt}")
                gr.Markdown("### 制作流程")
                for t in show["flow_steps"]:
                    gr.Markdown(f"- {t}")
                gr.Markdown(f"""### 部署与「真实生成」
| 档位 | 能做什么 |
|---|---|
| **免费 CPU（2vCPU/16G，本页默认）** | 展示与参数化演示（本页表单）；不产生真实生成任务 |
| **GPU 硬件档（如 A10 24G）** | 空间内跑**轻量视频模型**（Wan2.1-1.3B / CogVideoX-2B 等）→ 页面上真实出片 |
| **引擎网关（REMOTE_API）** | 表单直连你的本地大模型引擎（H3 全链：生成→台词→字幕→口型→ASR） |

当前后端：**{backend.name}**。**形态①（已定案）：创空间只放 Agent，模型走外部 API**——
在空间「设置 → 变量 / 密钥」里填这几项即可真实出片（不填=规划演示）：
| 变量 | 说明 |
|---|---|
| `ENGINE_BASE_URL` / `ENGINE_API_KEY` | **视频生成模型接口**（预留口；旧名 `VIDEO_API_URL`/`VIDEO_API_KEY` 仍兼容） |
| `ENGINE_STATUS_URL` | 可选，异步作业查询地址（旧名 `VIDEO_API_STATUS_URL`） |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | **外置大脑**：OpenAI 兼容决策模型（不填=内置规则规划器） |
| `TOOLSET` | 可选，暴露给大脑的工具子集（默认 all） |
| `AGENT_SYSTEM_PROMPT`（或 `AGENT_SYSTEM_PROMPT_FILE`） | 可选，外置 system 提示：注入行业规则/铁律 |

**Agent 的两半**：①**工具集** `generate_video` / `generate_talk` / `make_story_film` / `answer`（全部 HTTP，空间内无本机依赖）；
②**外置大脑** `LLM_*`（决定用哪个工具、什么参数）。两半齐备即为完整 Agent，缺大脑时用内置规则规划器兜底演示。

**空间内等价实现的本地功能**：参考图上传与预览、请求体预览（演示模式）、任务面板与状态刷新、成片预览/下载、
画布内字幕与拼接由引擎接口返回的成片直接承载（空间侧不做重编码，避免占用免费 CPU）。

_{show['footer']}_""")

        gr.Markdown(f"\n---\n_空间版本 v2.4（2026-09-10 · Agent=工具集+外置大脑；接口全外置·无本机依赖）_")
    return demo


def launch_kwargs(app) -> dict:
    """按当前 gradio 版本能力组装 launch 参数（跨版本安全，缺能力就少传一个参数）。"""
    kw = {}
    try:
        kw['theme'] = __import__('gradio').themes.Soft()
    except Exception:  # noqa: BLE001
        pass
    try:  # Gradio 5.30+/6.x 才有 MCP；本空间用不到，关掉它（也避免 gr.State 的 MCP 警告）
        import inspect as _inspect
        if 'mcp_server' in _inspect.signature(app.launch).parameters:
            kw['mcp_server'] = False
    except Exception:  # noqa: BLE001
        pass
    return kw


def main() -> int:
    ap = argparse.ArgumentParser("H3 视频生成工坊（创空间 Agent v2.4）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "7860")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--share", action="store_true")
    args = ap.parse_args()
    show = load_show()
    app = build_app(show)
    app.queue()
    app.launch(server_name=args.host, server_port=args.port, share=args.share,
               show_error=True, quiet=True,
               allowed_paths=[str(ASSETS), str(HERE / "outputs")],
               **launch_kwargs(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
