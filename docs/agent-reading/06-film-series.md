# 长片/多段连贯短片（agent 用：run_script film_series.py / film_stitch.py）

> 2026-09-09 用户定案：多段短片**必须连贯**——场景/人物/运镜跨段延续，禁止"逐段独立生成"（各自为战=用户批评'连贯性一塌糊涂'的根因）。

## 何时用
用户要求：长片 / 电影 / 多集 / 分镜短片 / 多段连贯 / "几个镜头连起来"。

## 正确做法（一条命令）
```
run_script(script="runs/h3/film_series.py", params="--prompts-file config/<项目>_prompts.json --resolution 480p --seconds 4 --seed <种子> --stitch --out /tmp/film.mp4")
```
- **--prompts-file**：段提示词 JSON（{"0":"…","1":"…"}，索引=段序，长度=段数）——由你按剧情写出（英文、写实电影感、段与段同人物/同场景/同光照）；
- **连贯机制**：段0=t2v（或 --start-image 首帧图），**每段 i2v 且首帧=上一段末帧**（程序自动逐段提取末帧）+ 每段自动追加"延续句"（same characters/location/lighting, continuous, no cuts）；
- **--stitch**：完成后自动 film_stitch 拼接成片（STITCH_OUT + PROBE 行）。

## 独立拼接（已有各段时）
```
run_script(script="runs/h3/film_stitch.py", params="--segments f1.mp4,f2.mp4,... --out /tmp/film.mp4")
```
自动逐段归一化（统一分辨率/24fps/aac/双声道）后 concat。

## 台词段（人物说话的口型段）
在 film_series 之外对**某单人近景段**补真台词链（与片长无关时）：
```
run_script(script="runs/h3/lipsync_chain.py", params="--video <段文件> --line "台词" --voice yunxi --asr-check")
```
旁白配音机械味=cosy speed 已调 0.95（tts_cosy_check --speed；链默认生效）。

## 纪律
- 480p/5s 验证档（白天≤768p）；长片各段用同 seed；
- 输出字段：SEGMENTS（段列表）/ STITCH_OUT / PROBE；报告给用户=成品文件名（相对说法，不露绝对路径）。
