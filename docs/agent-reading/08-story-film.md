# 故事片主控 story_film(agent 使用规范,2026-09-09)

## 一句话
用户给剧本→我们用 `runs/h3/story_film.py` 一条命令完成「分镜→逐段生成→台词→成片」。

## 配音与字幕(2026-09-10 用户三次纠错后的最终定案)
- **配音=native(默认)**:台词原文写进该段提示词 → **H3 自己说出台词**(实测 ASR_SCORE 1.000;口型本来就同步)。
  旧行为(tts=CosyVoice2 配音替换原轨)降级为备选 `--voice-mode tts`。
- **字幕=我们后期烧**(默认烧、位置**贴底** `SUBTITLE_MARGIN_V=0.03`;不想烧用 `--no-subtitle`)。
  ⚠️ **关键坑**:台词若用**引号**包起来,H3 会**自动把它画成画面字幕**,即使另写 no subtitles 也不听,
  后期再烧就变成**两条叠字**(用户当场指出并定性为错误)。
  实测解法:台词**不加引号** + 明确 audio only / this sentence must never appear as written text,
  subtitle or caption anywhere on screen(见 `spoken_line_clause()`)→ 画面干净无字,且台词照样说对。
  用拼音代替汉字会无字但发音变糊(ASR 掉乱码)→ **必须保留汉字原文**。
- **画面内文字(招牌/标语等)另有一套**:明确要文字时才注入四维描述法条款——
  前缀 `超高清摄影，8K文字渲染，矢量级笔画锐度，无抗锯齿失真` +
  (1)字体风格 现代无衬线/等宽笔画 (2)字号层级 主行最大、次级≤60%、同基线
  (3)颜色对比 纯白字+细黑描边+微压暗底 (4)动态行为 静态稳定/不抖/不重绘,
  并禁掉艺术化/手写感/书法类干扰词(negative:text-artistic)。
  触发条件=提示词出现 `sign reads` / 招牌上写着 / 字样是 这类明确要字的短语(反向句 no signage text 不误触发)。
- 分辨率仍是文字清晰度最大杠杆:720p 文字锐度约为 480p 的 4.5 倍。

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
