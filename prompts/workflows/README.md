# prompts/workflows —— 每个工作流的提示词文件

命名规则：<槽>.positive.txt / <槽>.negative.txt（槽名见 ../../prompts/manifest.json）。

- 为空 = 未设置：运行时自动回退到 prompts/positive_prompts.txt（默认）。
- 用 bats\prompts\prompts.bat（图形/记事本）或 bats\prompts\bats\prompts\ai_prompts.bat（AI 根据一段创意自动生成全部）来填写。
- 修改后即时生效：引擎提交对应工作流时会自动用本文件替换工作流内嵌提示词。