# 《油价涨了》台词表(配合 config/story_oil_price_prompts.json; film_series 9 段生成后,用单段 lipsync_chain 逐段配音替换)

- seg_02 (L=莱可近景; voice=yunxi 男): "我叫莱可。我的汽车在八里外没油了,太太还在车里——我只要两加仑汽油就够了。"
- seg_04 (达克近景; voice=yunxi 男): "五十元一加仑。您想想,这样的风雪天,人在外面很快就会冻死的。"
- seg_07 (海伦近景; voice=xiaoxiao 女): "我先生说了汽油的事,我们还想买一加仑。这些钱足够了。"
- seg_08 (达克近景惊恐; voice=yunxi 男): "香柏银行……你们,是抢劫了香柏银行?"

技术要点(给 agent):
1) film_series.py --prompts-file config/story_oil_price_prompts.json --resolution 480p --seconds 4 --lora fl2v_4step --seed 20260909 --work-dir /tmp/oil_story --stitch --strip-audio --out /tmp/oil_story_visual.mp4
   (注意: --stitch 只是先出预览; 最终台词段替换后用 film_stitch 重拼)
2) 逐段台词: 对 segment_02.mp4/segment_04.mp4/segment_07.mp4/segment_08.mp4 分别跑
   lipsync_chain.py --video <该段> --line "<台词>" --voice <音色> --asr-check --face-restore --out <同段主目录>/seg_02_voice.mp4 等
   (更新过的段再写回同名 segment_XX.mp4, 保持命名)
3) 最终拼接: film_stitch.py --segments <9 段按序> --out outputs/story_oil_price.mp4 --strip-audio --keep-audio-segs "2,4,7,8"
   (其余段=画面无声; 台词段保留音轨+字幕)
4) 完成后报告: 成片路径(相对说法)+ 每段 probe(宽高/帧率/时长)+ 台词 ASR 分数行。
