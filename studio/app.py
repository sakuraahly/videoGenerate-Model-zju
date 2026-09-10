#!/usr/bin/env python3
"""H3 视频生成工坊 — 魔搭创空间静态展示版（M1）。

设计（docs/guides/studio-porting.md §3 M1）：
  - 片墙：本机生成样片（assets/*.mp4 + 封面），可播放；
  - 流程：灵感→提示词→生成→成品链→验收 五步说明；
  - 演示表单：剧情/台词/音色/风格 → 演示模式结果卡（M2 远程调度上线前不产生真实任务）；
  - 配置驱动：同目录 config.yaml（创空间 sdk 配置 + 展示元数据；缺失时用内建默认）。

运行：python app.py [--port 7860]（Gradio；本地/创空间一致）。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

DEFAULT_SHOW = {
    "title": "H3 视频生成工坊",
    "tagline": "一句创意 → 参考图/提示词 → 本地大模型生成 → 真台词/字幕/旁白/口型成品链 → ASR 验收交付",
    "hero_points": [
        "文生视频 / 图生视频 / 多参考图连贯 / 首末帧转场",
        "说话镜头：一句台词→H3 自适应音色亲口说出（音画同时长）+ ASR 验收",
        "故事片主控：剧本→分镜→台词→成片 单命令出片（9 段连贯·可断点续跑）",
        "台词先行+发音回环；字幕可选；ComfyUI 全链一体化；1280×736/4x 超分档",
    ],
    "flow_steps": [
        "① 灵感：一句话剧情；也可上传参考图锁定场景/角色/道具",
        "② 提示词：英文提示词+参考图契约（<Picture N> 全片锁定）",
        "③ 生成：ComfyUI + MiniMax H3 本地推理（本机 GPU，日间≤768p，夜间 1080p 档）",
        "④ 成品链：角色真台词（CosyVoice2）→ 口型同步 → 字幕烧录 → 旁白垫轨（错开不叠）→ 整脸无框修复",
        "⑤ 验收：SenseVoice ASR 双轨验真（台词窗/旁白窗）→ 交付命名归档",
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
    "voices": [("yunxi（中文·男声）", "yunxi"), ("xiaoxiao（中文·女声）", "xiaoxiao"),
               ("aria（英文·女声）", "aria"), ("daler（英文·男声）", "daler")],
    "styles": ["电影感", "真实", "纪录片", "动漫"],
    "footer": "演示模式说明：本页为静态展示（M1）。M2 远程调度上线后，「演示表单」将真实提交至引擎并回传成片；当前提交不产生任务。样片均为本机生成。",
}


def load_show() -> dict:
    """读 config.yaml（创空间 sdk 配置 + 展示元数据）；失败回退内建默认。"""
    try:
        import yaml  # noqa: F401
        cfg_file = HERE / "config.yaml"
        if cfg_file.is_file():
            data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
            show = {k: v for k, v in data.items() if k not in ("sdk", "app_file", "sdk_version")}
            show.update(data.get("showcase") or {})
            for k, v in DEFAULT_SHOW.items():
                show.setdefault(k, v)
            return show
    except Exception:  # noqa: BLE001
        pass
    return dict(DEFAULT_SHOW)


REMOTE_API = (os.environ.get('REMOTE_API') or '').strip()
STUDIO_TOKEN = (os.environ.get('STUDIO_TOKEN') or '').strip()
# 定位（2026-09-09 用户定案）：本空间=**创空间自包含**展示+交互（免费 CPU 档零依赖）；
# REMOTE_API/STUDIO_TOKEN 仅实验机联调开关（非交付形态，配置缺失即自动演示模式）。


def remote_submit(plot: str, line: str, voice_txt: str, style: str, res_val: str,
                  remote_api: str, token: str) -> tuple:
    """M2 远程提交：调 studio_gateway POST /v1/jobs；返回 (markdown, err)。"""
    if not remote_api or not token:
        return '', '未配置远程（REMOTE_API/STUDIO_TOKEN）'
    try:
        import requests
    except Exception:  # noqa: BLE001
        return '', '环境缺 requests'
    try:
        payload = {'prompt': ('A cinematic video scene: ' + (plot or '')).strip()[:1200],
                   'resolution': '720p' if '720p' in str(res_val) else '360p',
                   'seconds': 5}
        r = requests.post(remote_api.rstrip('/') + '/v1/jobs', json=payload,
                          headers={'Authorization': 'Bearer ' + token}, timeout=25)
        d = r.json() if r.headers.get('content-type', '').startswith('application/json') else {}
        if r.status_code == 200 and d.get('job_id'):
            return ('### 🎬 已提交远程生成（M2 上线模式）\n\n'
                    f'| 项 | 值 |\n|---|---|\n'
                    f'| 剧情 | {plot or "（未填写）"} |\n'
                    f'| 台词 | {line or "（未填写）"} |\n'
                    f'| 音色 | {voice_txt} |\n'
                    f'| 分辨率 | {res_val} |\n'
                    f'| 任务 id | `{d["job_id"]}` |\n\n'
                    '> M2 网关已接单；页面刷新后可下载成片（网关提供 /v1/jobs/<id>/download）。'), ''
        return '', f'远程返回 {r.status_code}: {d.get("error", "")[:80]}'
    except Exception as e:  # noqa: BLE001
        return '', f'远程不可达: {type(e).__name__}'


def build_demo(show: dict):
    import gradio as gr

    def _asset(name: str) -> str | None:
        p = ASSETS / name
        return str(p) if p.is_file() else None

    def demo_submit(plot, line, voice, style, res):
        voice_txt = dict(show["voices"]).get(voice, voice)
        rec = next((s for s in show["samples"] if s.get("style") == style), show["samples"][0])
        if REMOTE_API and STUDIO_TOKEN:
            rmd, err = remote_submit(plot, line, voice_txt, style, res, REMOTE_API, STUDIO_TOKEN)
            if not err:
                return rmd, _asset(rec["file"]) or None
            note = f'> ⚠️ 远程提交失败（{err}），已降级为演示模式。'
        else:
            note = '> M2 远程调度未配置，演示模式。'
        md = (
            f"### 🎬 演示结果卡（M1 演示模式）\n\n"
            f"| 项 | 值 |\n|---|---|\n"
            f"| 剧情 | {plot or '（未填写）'} |\n"
            f"| 台词 | {line or '（未填写；留空=按剧情设计）'} |\n"
            f"| 音色 | {voice_txt} |\n"
            f"| 风格 | {style} |\n"
            f"| 分辨率 | {res} |\n\n"
            f"> 正式版将提交至本机引擎（MiniMax H3，本页为静态展示）。该风格推荐样片：**{rec['title']}**。\n\n{note}"
        )
        return md, _asset(rec["file"]) or None

    with gr.Blocks(title=show["title"], theme=gr.themes.Soft()) as demo:
        gr.Markdown(f"## 🎬 {show['title']}\n\n{show['tagline']}")
        with gr.Row():
            for pt in show["hero_points"]:
                gr.Markdown(f"**▸ {pt}**")
        gr.Markdown("---\n### 🎞 成品片墙（样片均为本机生成）")
        rows = [show["samples"][i:i + 3] for i in range(0, len(show["samples"]), 3)]
        for row in rows:
            with gr.Row():
                for s in row:
                    with gr.Column():
                        gr.Image(value=_asset(s["cover"]), label=s["title"], show_label=True,
                                 interactive=False)
                        gr.Markdown(f"**{s['title']}** — {s['desc']}")
                        gr.Video(value=_asset(s["file"]), label=s["title"], interactive=False)
        gr.Markdown("\n### 🧭 制作流程")
        for t in show["flow_steps"]:
            gr.Markdown(f"**{t.split('：')[0]}**：{t.split('：', 1)[-1]}")
        gr.Markdown("\n### 🗣 说话镜头（一句台词→人物亲口说出）\n"
                    "_输入一句台词、选音色与字幕开关→演示卡展示对应样片与生成规格。_")
        with gr.Row():
            talk_text = gr.Textbox(label="台词", lines=2, scale=2,
                                   placeholder="例如：天冷了,快进屋坐坐吧,外面风大。")
            talk_voice = gr.Dropdown(choices=["H3 自适应（按人物形象）", "中文·男声 yunxi",
                                              "中文·女声 xiaoxiao", "英文·男声 daler",
                                              "英文·女声 aria"],
                                     value="H3 自适应（按人物形象）", label="音色", scale=1)
            talk_sub = gr.Checkbox(value=False, label="烧录字幕")
        talk_btn = gr.Button("生成说话镜头（演示）", variant="primary")

        def talk_demo(text, voice, sub):
            rec = next((s for s in show["samples"] if s.get("file", "").startswith("08_")),
                       show["samples"][0])
            secs = max(2.0, round(len(text or "") * 0.36 + 0.4, 2)) if text else 3.0
            return (f"### 🗣 说话镜头演示\n\n"
                    f"| 项 | 值 |\n|---|---|\n"
                    f"| 台词 | {text or '（未填写）'} |\n"
                    f"| 音色 | {voice} |\n"
                    f"| 字幕 | {'烧录' if sub else '不烧录'} |\n"
                    f"| 预计时长 | ≈{secs}s（按语音时长匹配，不虚长） |\n"
                    f"| 语音来源 | H3 自适应音色（模型按人物形象自选）｜备选本地 TTS |\n\n"
                    f"> 真实生成规格：本地 TTS 先定台词时长 → H3 帧档匹配生成 → 队列内成品（配音/字幕可选）+ ASR 验收；"
                    f"本页为自包含演示，展示同规格样片。")

        talk_out = gr.Markdown()
        talk_btn.click(talk_demo, [talk_text, talk_voice, talk_sub], [talk_out])

        gr.Markdown("\n### ✍️ 演示表单\n_本空间为**自包含演示**：选择参数→提交→展示匹配样片与格式说明；不产生真实生成任务（完整生成能力见项目文档）。_")
        with gr.Row():
            plot = gr.Textbox(label="剧情描述", lines=3, max_lines=6,
                              placeholder="例如：雨夜便利店前，一只猫望着暖光；或你的一句话创意…", scale=2)
            line = gr.Textbox(label="角色台词（可选）", lines=2, placeholder="例如：路上小心。", scale=1)
        with gr.Row():
            voice = gr.Dropdown(choices=[v[0] for v in show["voices"]], value=show["voices"][0][0], label="音色")
            style = gr.Radio(choices=show["styles"], value=show["styles"][0], label="风格")
            res = gr.Radio(choices=["360p 验证档", "720p 交付档"], value="720p 交付档", label="分辨率")
        with gr.Row():
            demo_btn = gr.Button("填入示例", size="sm")
            clear_btn = gr.Button("清空", size="sm")
            submit = gr.Button("提交演示（不产生真实任务）", variant="primary", scale=2)

        def _fill_example():
            return ("雨夜，老站台的昏黄站灯下，绿衣老人拖着行李箱望向驶来的绿皮火车，雾气弥漫。",
                    "路上小心。")
        demo_btn.click(_fill_example, None, [plot, line])
        clear_btn.click(lambda: ("", ""), None, [plot, line])
        result_md = gr.Markdown()
        rec_video = gr.Video(label="风格匹配样片", interactive=False)
        submit.click(demo_submit, [plot, line, voice, style, res], [result_md, rec_video])
        gr.Markdown(f"\n---\n_{show['footer']}_\n\n_空间版本 v1.3（2026-09-09 · 故事片主控样片+台词先行/回环；样片与代码为本项目自有，参考素材自备。）_")
    return demo


def main() -> int:
    ap = argparse.ArgumentParser("H3 视频生成工坊（M1 静态展示版）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "7860")))
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--share", action="store_true")
    args = ap.parse_args()
    show = load_show()
    demo = build_demo(show)
    demo.queue()
    demo.launch(server_name=args.host, server_port=args.port, share=args.share,
                show_error=True, quiet=True,
                allowed_paths=[str(ASSETS)])
    return 0


if __name__ == "__main__":
    sys.exit(main())
