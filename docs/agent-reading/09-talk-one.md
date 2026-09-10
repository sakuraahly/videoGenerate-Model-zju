# 说话镜头 talk_one(agent 用法,2026-09-10)

## 一句话
用户要"人物说话/台词/对白/口型/配音" → `run_script(h3/talk_one.py, ...)` **一条命令出成品**。

## 为什么用它(而不是 lipsync_chain)
- **H3 音频能力**:默认让 **H3 自己选音色说话**(台词写进提示词)→ 口型/表情/音色都由模型生成,**音画同时长**;
- **时长严格匹配**:先本地 TTS 得台词真实时长 → 按 H3 帧档(5+17k 帧@24fps)取最小足够档(例:2.76s→3.04s),
  不会出现"说完了还在动嘴";
- **队列内成品**:生成后由 ComfyUI 节点 H3Finalize 出成品(字幕**可选**)+ H3AsrCheck 验真——**本地零后处理**。

## 用法
```
run_script(h3/talk_one.py, --text "台词" --ref-image <人物图路径> [选项])
run_script(h3/talk_one.py, --text "台词" --from-video <已有视频路径> [选项])   # 从视频抽首帧当人物图
```
选项:
- `--no-subtitle`     不烧字幕(默认烧)
- `--audio-source h3` 默认:H3 自适应音色(推荐;音画同时长)
- `--audio-source tts --voice xiaoxiao|yunxi|aria|daler` 备选:本地 TTS 准确音轨(H3 只做口型)
- `--resolution 480p|720p`、`--speed 0.95`(TTS 语速)、`--margin`
输出:成品 = 生成产物同名 `_final.mp4`(在项目 outputs/,并复制到 ComfyUI 输出区),打印时长与 ASR 分数。

## 铁律
1. 脚本名带子目录:**h3/talk_one.py**。
2. 必须有 `--ref-image` 或 `--from-video`(H3 音频/口型能力只在 r2v 档可用)。
3. 台词=用户给的原文(没有则按剧情拟一句口语台词);**不要**自己改字数或加旁白。
4. 任务耗时 3-8 分钟(含本地 TTS 30-60s);**不要中断**,报错时先看输出再重跑;**不要从头重复提交**(脚本自带产物与队列校验)。
5. 面向用户不要提路径/脚本名:说"说话镜头已生成,成片在结果区(文件名 xxx)"。
