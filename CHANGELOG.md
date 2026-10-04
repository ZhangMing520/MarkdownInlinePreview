# Changelog

## v0.3.0
- 路径补全：`](` / `![` 后列出同目录文件/子目录
- 粘贴 URL 自动链接命令：`mip_paste_url_as_link`
- README（含与 VS Code 预览能力对照表）、LICENSE、messages.json
- 发布件就绪

## v0.2.0
- 备选引擎 markdown-it-py（已 vendor 进包，含 mdit-py-plugins）
  - 补齐 GFM 表格 / 任务列表 / 删除线（python-markdown 默认扩展缺失的能力）
- YAML front matter 渲染为表格
- 引擎库缺失时降级并状态栏提示
- 单向同步滚动（块级近似）

## v0.1.0
- 同窗口分栏 + 空白预览视图 + 逐块多 phantom
- python-markdown 引擎 + pygments 代码高亮
- on_modified 防抖实时刷新
- 图片 base64 内嵌（本地 + 远程异步）
- 关闭预览还原布局
- 快捷键 ctrl+alt+m（macOS super+ctrl+m）
- minihtml 标签转换层：table→div 网格、input→[x]、del→line-through
