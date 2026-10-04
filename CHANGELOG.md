# Changelog

## Unreleased
- **表格渲染重写**：minihtml 无 width/flex/滚动，原 inline-block 网格列无法对齐且超宽被裁。
  现为：窄表 → 等宽字体 nbsp 补齐网格（精确对齐）；宽表 → 逐行卡片布局（永不裁切）。
- **浏览器实时预览**（`ctrl+alt+shift+m`）：内置 127.0.0.1 HTTP 服务器 + SSE 推送，
  浏览器原生渲染（真实 `<table>`/复选框/删除线），GitHub 风格 CSS 亮暗跟随系统，离线零外部请求。
- **浏览器模式 KaTeX 数学公式与 mermaid 图**（JS/CSS/字体 vendor 进包，`browser_extras` 设置可关）。
- **锚点跳转**：预览内点 `#heading` 链接滚动到对应块（默认引擎新增 `toc` 扩展，mdit 引擎新增 anchors 插件）。
- **增量 phantom 更新**：块数不变时只重插内容变化的块，未变块原地保留（消除整版闪烁）。
- **默认引擎补齐 GFM**：vendored pymdownx 子集（tasklist/tilde），python-markdown 引擎也能渲染任务列表与删除线。
- **zip 安装兼容**：Package Control 发布形态（.sublime-package）下 vendored 库自动解压到缓存目录，
  修复 mdit 引擎与公式/图资产在 zip 安装下不可用的问题。
- **修复 markdown-it-py 引擎不可用**：vendored 副本从 4.2.0 降到 2.2.0（4.x 用了 3.9+ 运行时语法，
  ST 3.8 宿主 import 失败被静默吞掉）；表格/删除线改由 `default` preset 提供。
- `.python-version = 3.8` 兼容全部 ST4：旧构建跑 3.8 宿主，Build 4205+ 官方别名自动选 3.14 宿主。

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
