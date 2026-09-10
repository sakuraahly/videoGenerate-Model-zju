# 工作流注册表（自动生成，勿手改）

> 来源: config/capabilities.json；重新生成: python runs/h3/capabilities.py --registry-doc

## video_t2v (stage=t2v)

- 用途: text-to-video：**引擎默认用内置生成器 h3_t2v**（代码现场拼 API 工作流，不读模板文件）；同名的 video_minimax_h3_t2v.json 仍在镜像目录里但**未注册为 stage**，需要时用 --template 显式指定。运行日志会写 source=内置生成器/模板文件。
- 生成器: **内置 h3_t2v**（代码现场构建 API 工作流，不读模板文件）
- 备用模板: `（无；镜像目录里的同名文件未注册为 stage）`
- 槽位: images=none; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: negative_support

## video_i2v (stage=i2v)

- 用途: image-to-video: animate from one first frame
- 模板: `workflows/remote_workflows/video_minimax_h3_i2v.json`（format=ui）
- 槽位: images=first_framex1; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: negative_support

## video_r2v (stage=r2v)

- 用途: reference-to-video: multiple reference images (character/scene/props; local template has 8 slots, grow-able via refimage grow)
- 模板: `workflows/remote_workflows/video_minimax_h3_r2v.json`（format=ui）
- 槽位: images=referencex8; videos=1; audios=1
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: reference_videos, audio, negative_support, ref_tag_required

## video_flf2v (stage=flf2v)

- 用途: first-frame + last-frame video (local extension of i2v)
- 模板: `workflows/remote_workflows/video_minimax_h3_flf2v.json`（format=ui）
- 槽位: images=first_framex1, last_framex1; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: negative_support

## video_r2v_finalize (stage=finalize)

- 用途: r2v + 成品链一体（生成→结尾 H3Finalize→H3AsrCheck）：一次提交直接拿到配音/字幕/验收后的成品（31 节点）
- 模板: `workflows/remote_workflows/video_minimax_h3_r2v_finalize.json`（format=ui）
- 槽位: images=referencex8; videos=1; audios=1
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: reference_videos, audio, negative_support, ref_tag_required

## video_r2v_rife (stage=rife)

- 用途: r2v + RIFE 48fps 插帧 + 成品链：画面顺滑的高帧率成品（35 节点）
- 模板: `workflows/remote_workflows/video_minimax_h3_r2v_rife_finalize.json`（format=ui）
- 槽位: images=referencex8; videos=1; audios=1
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: reference_videos, audio, negative_support, ref_tag_required

## video_r2v_restore (stage=restore)

- 用途: r2v + 整脸修复 + RIFE + 成品链：完整后期链，画质/人脸最佳（36 节点）
- 模板: `workflows/remote_workflows/video_minimax_h3_r2v_restore_finalize.json`（format=ui）
- 槽位: images=referencex8; videos=1; audios=1
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: reference_videos, audio, negative_support, ref_tag_required

## video_t2v_ui (stage=t2v_ui)

- 用途: text-to-video 的 UI 模板版：读 video_h3_t2v_builtin.json（由内置生成器导出、widget 顺序对齐节点定义），便于在 ComfyUI 里查看/修改内置 T2V 的默认参数；不可用时回退内置生成器 h3_t2v。
- 生成器: **内置 h3_t2v**（代码现场构建 API 工作流，不读模板文件）
- 备用模板: `workflows/remote_workflows/video_h3_t2v_builtin.json`
- 槽位: images=none; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: negative_support

## 当前全部可用（digest）

- video_t2v (stage=t2v): images=none resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
- video_i2v (stage=i2v): images=first_framex1 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
- video_r2v (stage=r2v): images=referencex8 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=reference_videos,audio,negative_support,ref_tag_required
- video_flf2v (stage=flf2v): images=first_framex1, last_framex1 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
- video_r2v_finalize (stage=finalize): images=referencex8 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=reference_videos,audio,negative_support,ref_tag_required
- video_r2v_rife (stage=rife): images=referencex8 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=reference_videos,audio,negative_support,ref_tag_required
- video_r2v_restore (stage=restore): images=referencex8 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=reference_videos,audio,negative_support,ref_tag_required
- video_t2v_ui (stage=t2v_ui): images=none resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support

## 未注册模板（引擎不会自动用）

> 同目录下但没有任何 stage/注册表条目引用的工作流：只有 GUI 手动打开或 `--template <路径>` 显式指定才会跑。

- （无）

## 权威与自检

- 引擎实际读取的模板目录由 `config/pipeline.json` 的 `templates_dir` 决定（当前 `workflows/remote_workflows/`）；
  `config/templates/` 为历史副本树，**引擎不读**。
- 一条命令自检当前在用哪份：`python runs/h3/workflow_audit.py`（只读；模板缺失时退出码 1）。
- 详见 `docs/guides/workflow-single-source.md`。
