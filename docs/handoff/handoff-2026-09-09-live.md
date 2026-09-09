# 交接 · 2026-09-09(当日实况)

> 时间轴(UTC=机器时区;北京时间=UTC+8)。上一日: handoff-2026-09-08-live.md。

## 一、本轮闭环(2026-09-09 凌晨~下午)

### 1. 定时 agent 任务:注入+审计 验证通过 ✅
- sched-agent-test(*/3): 连 3 轮注入→agent 收到(SYSTEM 服从条款)→run_script 执行→110s 审计「有工具调用」全 ok(05:52/05:55/05:57,event 05 4c/47 0b/1e d8)。
- **测试任务已下线**: sched-demo-minutely(48 轮 ok)/ sched-agent-test(3 轮 ok)从 config/agent-tasks.json 移除;保留 sched-watchdog / sched-night-check / sched-daily-report。
- **待办**: sched-daily-report 今晚北京 20:00(UTC 12:00)首次真机(agent 对话任务→简报)。

### 2. 调度器时区 bug 修复 ⚠️(重要)
- 机器=UTC;task_scheduler 用 time.localtime() → schedule 字段= **UTC 语义**。
- 修复: night-check 巡检窗口 hour 22-23,0-6 → **14-23**(对应北京 22:00-08:00);daily-report hour 20 → **12**(北京 20:00);_comment 标注时区。config 已同步 spark(无需重启,每 tick 重载)。

### 3. EchoMimic 无框路线:冒烟全链 PASS ✅(nt-echomimic-smoke)
- 人像模式: --ref-image 父亲.png(1600×2848)+line.wav(1.5s)→MTCNN 原图判据(5 脸/最大脸)→infer_audio2vid_acc.py(fp16/6步/512²/24fps)→_withaudio.mp4→/tmp/echomimic_smoke.mp4(265KB)→DONE_ECHO_TALK;抽帧=白发老者正面像/口型合成/无贴框。
- **四连修**(本地+spark;commit e345d6a): ①人像入口(视频/参考图至少其一,各自校验;dry-run 兼容) ②facenet_pytorch **2.6.0→2.5.0**(2.6.0 在 numpy1.26 下 detect 返回 object dtype→np.round 崩;requirements 本就 pin 2.5.0)+select_face np.asarray(float) 防御 ③moviepy **2.2.1→1.0.3**(2.x 无 moviepy.editor) ④em_out 相对路径按 EM_ROOT 解析。
- tts-venv 健康复验: torch 2.14+cu130/CUDA True/f5_tts OK/cv2 5.0/librosa 0.10.2.1/numpy 1.26.4/scipy 1.13.1 ✅。
- **下一步**: 接 lipsync 链 --talking-backend echomimic(替 W2L+GFPGAN 贴皮段)→真机交付 video_N;视频构图(带背景回贴)模式另测。

### 4. S7 r2v 参考视频测试:PASS ✅(nt-ref-video-test)
- 修复版(config 已含 <Picture 2>+2 图;昨夜失败=旧版 config 缺 tag/图 + 图片上传瞬时失败)。
- 真机: 720p/5s/ref2v_8step;父亲.png+父母卧室.png+参考视频 00188(手部特写)→prompt 5815452b→success:**outputs/video_504.mp4**(1280×736/24fps/124f/5.167s)。
- 抽帧目检: 手部装信封(参考视频驱动)+背景卧室台灯/花瓶锁定(参考图)+母亲虚化在后;无文字。**已取回: Windows outputs/video_87_医院夜_父亲装信封_r2v参考视频.mp4**(1.28MB)。

### 5. 夜窗重活(昨夜自动,本日上午核定)
- nt-hd-4x-ultimate EXIT=0 ✅(video_461 1920×1088,4x 收尾)
- nt-hd-4x-r2v-refs EXIT=0 ✅
- nt-upscale4x PASS_chunked_4864×2688_12.458s ✅
- nt-upscale-backfill(video_462/463 4x 超分)**昨夜未跑**(config 昨夜后新增)→ 今夜窗口自动执行(pending)。
- nt-rife=blocked_channels_verified_deferred(渠道阻塞,保持登记)。

### 6. 猫 demo v2(压缩前会话成果,核验)
- /tmp/demo_cat_v2.mp4: 3 段(老屋木门 463/502/503)拼接 864×480/13.46s;提示词=config/demo_cat_night_prompts.json(已有提交)。
- 待: 交付/展示(与 video_86_雨夜老屋前的猫.mp4 同场景)。

## 二、提交(Windows 主库;已 push GitHub)
- e345d6a echomimic 修复+调度测试任务下线+猫提示词
- 30e6530 docs 闭环登记+§15e⑦
- 09671bf 调度器时区语义修复
- spark 工作树=上述最新(scp 同步;git HEAD 落后 53b832c 无碍,以工作树为准)。

### 7. 故事短片《油价涨了》(用户剧本→agent 生成;2026-09-09 下午)
- 玩法: 模拟用户对话(7860 send 注入 3 轮)[剧本+9 段分镜+台词表]→agent 自主完成 9 段连贯电影系列(film_series 480p/4s/i2v 首帧继承)+ 段2/4/7 台词链(lipsync_chain+ASR+face-restore)。
- agent 卡点: ①run_script 600s 超时容不下 9 段(→1800s,已提交)②长任务后模型轮两次停摆(>10 分钟无活动,重启恢复)③段文件映射两次错位。
- 兜底: 段8 原素材(手枪顶额)W2L 全帧无脸→重生成正面脸版(video_518)后台词链;最终拼接由 shell 完成。
- 产物: outputs/story_oil_price.mp4(864×480/48.0s/9 段;4 句台词字幕;段8 ASR 0.786 ok)→已取回 Windows outputs/video_88_油价涨了_希区柯克短篇.mp4(6.6MB)。
- config: story_oil_price_prompts.json(9 段)+story_oil_price_lines.md(台词表)已入库;教训=长链路 agent 欠稳,路径映射须幂等。

## 三、当前待办(下一步)
1. sched-daily-report 今晚北京 20:00 首测(agent 对话任务;UTC 12:00 tick)。
2. nt-upscale-backfill 今夜自动(UTC 14:00 窗口开始,V >14:00 后 ComfyUI 空闲即跑)。
3. EchoMimic 接 lipsync 链(替 W2L+GFPGAN)→真机交付 video_N。
4. **Studio v1.2 需重新发布到魔搭创空间**(需要 token 或用户 push;上一版 419 验收)。
5. demo_cat_v2 展示(用户可看)。
6. video_87 交付说明(参考视频驱动测试件,可放样片墙候选)。

## 四、风险提示
- 队列: 当前空闲;今夜 14:00 UTC 起自动窗口任务(backfill 4x 超分≈5-8 分钟/个)。
- agent 心跳/防假完成: 已由 110s 审计覆盖;任务注入历史保留(不冲会话)。
- 时区: 一切机器 cron=UTC;北京=UTC+8(已踩坑修复,勿再按北京时区写 schedule)。
