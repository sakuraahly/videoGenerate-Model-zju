# 工作流注册表（自动生成，勿手改）

> 来源: config/capabilities.json；重新生成: python runs/h3/capabilities.py --registry-doc

## video_t2v (stage=t2v)

- 用途: text-to-video (official standard template)
- 模板: `workflows/remote_workflows/video_minimax_h3_t2v.json`（format=ui）
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
- 槽位: images=referencex8; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: audio, negative_support

## video_flf2v (stage=flf2v)

- 用途: first-frame + last-frame video (local extension of i2v)
- 模板: `workflows/remote_workflows/video_minimax_h3_flf2v.json`（format=ui）
- 槽位: images=first_framex1, last_framex1; videos=0; audios=0
- 参数: resolutions=360p,480p,540p,720p,768p; seconds=5..15; fps=24; steps=20
- 特性: negative_support

## 当前全部可用（digest）

- video_t2v (stage=t2v): images=none resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
- video_i2v (stage=i2v): images=first_framex1 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
- video_r2v (stage=r2v): images=referencex8 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=audio,negative_support
- video_flf2v (stage=flf2v): images=first_framex1, last_framex1 resolutions=[360p,480p,540p,720p,768p] seconds=5..15 features=negative_support
