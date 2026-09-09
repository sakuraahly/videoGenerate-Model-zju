# 故事片主控 story_film(agent 使用规范,2026-09-09)

## 一句话
用户给剧本→我们用 `runs/h3/story_film.py` 一条命令完成「分镜→逐段生成→台词配音→成片」。

## 剧本文件(config/story_<名字>.json)
- `title` 标题 / `style` 统一风格句(自动注入每段)
- `characters` 角色卡(名字→描述;程序自动注入每段=人物一致性)
- `segments` 段数组(顺序=播放顺序;每段 `prompt` 描述镜头+剧情动作时序)
- `lines` 台词表(段索引→{`text` 台词, `voice` 音色, `spoken`(可选)发音写法})
- **台词先行**:生成语音之前台词已在剧本里设置好;TTS 输入永远=台词表文本,不允许现场编词。

## 命令
- `run_script(h3/story_film.py, --story config/story_xxx.json --stitch --out outputs/xxx.mp4)`
- 进度查询: `run_script(h3/story_film.py, --story config/story_xxx.json --status)`

## 铁律
1. 脚本名必须带子目录(**h3/story_film.py**),路错误会"脚本不存在"。
2. **断点续跑**:程序把进度写到 work-dir/state.json(默认 /tmp/story_film);任何失败/超时/重启后:
   先 `--status` 查进度,再**重跑同一条命令续跑**(自动跳过已完成段,从断点继续);
   **绝对禁止从头重跑**(--fresh 只有用户明确要求才用)。
3. **动态计时**:RunScript 已按脚本名给足超时(story_film=7200s);不要因为"好像很慢"就中断。
4. 台词段发音:程序先 TTS(台词表文本)→ASR 回环(>=0.70),不达标自动用 spoken 重试;
   若台词段仍失败,程序会保留画面段并报告**分数/原因**(不做假)。
5. 完成后报告:成片 PROBE(宽高/帧率/时长)+ 各台词 ASR 分数。
