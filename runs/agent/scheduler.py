"""
受限调度器 — 主入口（适配 scheduler-agent-design.md）

Qwen3.8-27B 作为受限调度器：理解意图 → 选工具 + 生成参数 → 工具层执行。
模型不直接执行命令，所有动作经白名单工具。

Usage:
    python3 runs/agent/scheduler.py              # Gradio Web UI (port 7860)
    python3 runs/agent/scheduler.py --cli         # 终端交互
    python3 runs/agent/scheduler.py --port 7861   # 自定义端口
"""
from __future__ import annotations

import argparse
import os
import sys

_PROJECT_ROOT = os.environ.get(
    'VIDEOGEN_PROJECT_ROOT',
    os.path.expanduser('~/videoGenerate-Model-zju'),
)
os.environ['VIDEOGEN_PROJECT_ROOT'] = _PROJECT_ROOT

if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from runs.agent.tools import (RunScript, ModifyWorkflow, CallComfyUI, ReadDoc,  # noqa: E402, F401
                              ListReferences)

LLM_CFG = {
    'model': 'Qwen3.8-27B',
    'model_server': 'http://127.0.0.1:8000/v1',
    'api_key': 'sk-dummy',
    'generate_cfg': {
        'temperature': 0.2,
        'top_p': 0.8,
        # 服务端 ctx=8192：max_tokens 必须 < ctx（曾用 8192 → 任何请求都 400）；
        # 输入侧预算由各入口经 ctx_budget.request_budgets 显式设置
        # （max_input_tokens），详见 runs/agent/ctx_budget.py。
        'max_tokens': 2048,
        'fncall_prompt_type': 'nous',
    },
}

SYSTEM_MESSAGE = """\
你是 Qwen3.8-27B 视频生成调度器，运行在 DGX Spark 本地服务器。
你的职责是理解用户创意，自主完成视频/图片生成任务。

═══ 核心行为准则 ═══
1. **自主行动优先**：用户给出创意后，你应自主选择工作流、生成详细英文提示词、选择参数、直接提交。不要反复确认技术细节。
2. **只问必要问题**：仅在以下情况询问用户——①视频内容/主题完全不明确 ②需要用户从素材中选择参考图 ③分辨率/时长偏好不确定且无法合理推断。其他一切技术细节由你决定。
3. **工作到完成**：提交任务后不要停下来等用户指示。如果还有后续步骤（生成下一段、检查进度、获取结果），继续执行。
4. **"继续"= 承接上次工作**：当用户说"继续"，查看对话历史，了解之前在做什么，然后继续未完成的工作。绝对不要回复"当前没有进行中的任务"或问用户想做什么——你之前的对话记录里就有上下文。
5. **创意→成片**：用户只给一句创意时，直接：选工作流→生成英文提示词→选默认参数(720p/5s)→提交。

═══ 工作流（只用本地，不提 api_*） ═══
- t2v：文生视频（文字→视频）
- i2v：首帧图生视频（一张图→延续动画）
- r2v：多参考图生视频（多张参考图保证连贯）
- flf2v：首末帧转场（首帧+末帧→平滑过渡）

═══ 工具 ═══
- batch_submit(stage, images, ...) — 批量提交多图转场（推荐用于多图任务）
- call_comfyui(stage, prompt, resolution, seconds, ...) — 提交视频生成
- run_script(script, args) — 运行白名单脚本：
  · h3_text2img.py — 文生图：--prompt "描述" --output 名称
  · h3/idea2prompts.py — 从创意生成提示词
  · h3/refimage.py — 素材管理：list/promote/use/prune
  · h3_batch.py — 批量状态查询/重试：status --wait / retry --batch <dir>
- modify_workflow(path, changes) — 修改工作流节点
- read_doc(filename) — 读取参考文档（按需）
- list_references() — 列出可用素材

═══ 创意→成片流程 ═══
1. 判断工作流：默认 t2v；用户提供/提到图片→i2v/r2v；需要首末帧→flf2v
2. 生成英文提示词（具体描述：主体+环境+光影+镜头运动+音频分层+负面约束收尾）
3. 选参数：默认 720p/5s（用户指定则用用户值）
4. 直接 call_comfyui 提交
5. 汇报 TASK_SUBMITTED + prompt_id
6. 如有后续（多段视频等），继续执行

═══ 提示词规则 ═══
- 英文撰写，具体物理动作描述（不写抽象概念）
- 中文文字渲染逐字枚举：first '你', then '好'...
- 始终包含音频描述（即使"no dialogue, only ambient tone"）
- 负面约束收尾：No text, no watermark, no cuts, no dialogue.

═══ 分辨率/时长 ═══
360p(608×352) / 480p / 540p / 720p(1280×736,推荐) / 768p(1344×768)
时长 0.1-600秒，推荐 5-15秒。

═══ 多图转场 ═══
N 张图 → 一次 batch_submit(stage=flf2v, images=逗号分隔) 提交全部 N-1 段；
然后 run_script("h3_batch.py", "status --wait") 等待并取回全部产物。
部分段失败时：run_script("h3_batch.py", "retry --batch <dir> --segments <idx>")。
禁止逐段手动提交。

═══ 硬性限制 ═══
✗ 不能执行 shell 命令、管理服务（ComfyUI/SGLang/tmux）
✗ 不能读写白名单目录以外的文件
✗ 工具返回 ⛔ 时表示不可恢复：不要重试同一调用，改换方案或向用户汇报
→ 用户要求上述操作时，拒绝并告知需人工操作

═══ 输出纪律 ═══
- 中文回复，精炼（≤600字）
- 结论带依据（TASK_SUBMITTED/REMOTE_VIDEO_PATH/LOCAL_OUTPUT）
- 提交后简要汇报并继续下一步，不要反复解释或等待指示

═══ 语言铁律（强制，优先级最高）═══
- 一切面向用户的话**必须用简体中文**：解释、汇报、提问、总结、进度说明。
- **仅有以下四类允许英文**：①代码/命令片段 ②生成任务的英文提示词本体 ③工具标记行/TASK_SUBMITTED/REMOTE_VIDEO_PATH/LOCAL_OUTPUT/退出码/prompt_id ④技术名词（ComfyUI、SGLang、分辨率、stage 名、token 等）及其已有英文缩写。
- 反例：不要回复 submitted successfully，应回复 已提交成功；不要回复 I will use r2v，应回复 我将使用参考图生视频（r2v）。
- 不要为展示英文而插入整段英文解释；用户看到的是中文对话，英文只出现在上述四类豁免中。


请用中文回答。
"""

TOOL_NAMES = ['run_script', 'modify_workflow', 'call_comfyui', 'read_doc',
               'list_references', 'batch_submit']


def _detect_project_root() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidate = os.path.dirname(os.path.dirname(script_dir))
    if os.path.isfile(os.path.join(candidate, 'config', 'pipeline.json')):
        return candidate
    return _PROJECT_ROOT


def _print_version(root: str):
    """启动版本指纹：防"跑的不是这个代码"类假绿（book-01 / book-09 进程级判据）。"""
    try:
        from runs.agent import version
        version.AGENT_VERSION  # 触发计算
        print(f"[agent] {version.describe()}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[agent] AGENT_VERSION=unknown root={root} err={e}", flush=True)


def run_gui(port: int = 7860, share: bool = False):
    # 自研轻量界面：历史会话/新对话/进行中指示/上下文预算（见 ui_app.py）
    from runs.agent import ui_app

    root = _detect_project_root()
    os.environ.setdefault('VIDEOGEN_PROJECT_ROOT', root)
    _print_version(root)
    ui_app.run_app(port=port, share=share)


def run_cli():
    from qwen_agent.agents import Assistant
    from runs.agent import ctx_budget

    llm = dict(LLM_CFG)
    # 输入硬预算：qwen_agent 截断层按 max_input_tokens − tokens(system) 限制
    # 对话往返，与回复预算 2048 合计不越 ctx=8192（实测依据见 ctx_budget.py）
    max_input, _ = ctx_budget.request_budgets(SYSTEM_MESSAGE)
    llm['generate_cfg'] = {**(llm.get('generate_cfg') or {}),
                           'max_input_tokens': max_input}

    bot = Assistant(
        llm=llm,
        system_message=SYSTEM_MESSAGE,
        function_list=TOOL_NAMES,
    )

    messages = []
    print('Qwen-Agent 受限调度器 CLI')
    print(f'项目根目录: {_detect_project_root()}')
    print('输入 quit 退出')
    print('=' * 50)

    while True:
        try:
            user_input = input('\n你: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\n再见!')
            break

        if not user_input:
            continue
        if user_input.lower() == 'quit':
            print('再见!')
            break

        # 内存协同：回合前保证模型可用（nap 后自动 wake）
        from runs.agent import llm_mem as lmem
        if not lmem.ensure_llm_up(timeout_s=900):
            print('\n[调度器] 本地模型唤醒失败，请人工查 ~/sglang.log')
            continue

        messages.append({'role': 'user', 'content': user_input})
        # 与界面同口径的历史裁剪（token 预算；保留最新轮次+尽量保留首轮）
        messages, dropped = ctx_budget.trim_messages(messages)
        if dropped:
            print('\n[调度器] 较早的轮次已按 token 预算自动压缩，继续对话。')

        response = []
        for chunk in bot.run(messages=messages):
            response = chunk

        if response:
            last = response[-1]
            content = last.get('content', '')
            print(f'\n调度器: {content}')
            messages = messages + response


def main():
    parser = argparse.ArgumentParser(description='Qwen-Agent 受限调度器')
    parser.add_argument('--cli', action='store_true', help='终端交互模式')
    parser.add_argument('--port', type=int, default=7860, help='Web UI 端口')
    parser.add_argument('--share', action='store_true', help='Gradio 公网分享')
    args = parser.parse_args()

    if args.cli:
        run_cli()
    else:
        run_gui(port=args.port, share=args.share)


if __name__ == '__main__':
    main()
