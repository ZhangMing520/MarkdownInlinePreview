# MarkdownInlinePreview

在 **Sublime Text 编辑器内部（同窗口分栏）** 实时预览 Markdown，不依赖浏览器、不依赖其他 Sublime 包。

渲染引擎可配置（默认 python-markdown，可选 markdown-it-py），独立发布到 Package Control。

## 功能

**两种预览模式**（互补）：

- **内嵌预览**（`ctrl+alt+m`）：同窗口分栏，编辑器内 phantom 渲染，边写边看，不切窗口
- **浏览器实时预览**（`ctrl+alt+shift+m`）：内置本地服务器 + SSE 推送，浏览器原生渲染，
  完整 GitHub 样式、原生表格/复选框；**KaTeX 数学公式与 mermaid 图**已 vendor 进包（离线可用，
  `browser_extras` 设置可关）
- 刷新防抖（默认 300ms），大文档不卡
- GFM 渲染：表格（窄表对齐网格/宽表卡片）、代码高亮(pygments)、任务列表、删除线、front matter
- 文内锚点跳转（`#heading` 链接定位到对应块）
- 单向同步滚动（编辑器 → 预览，块级近似）
- 图片 base64 内嵌（本地即时、远程异步）
- 点击预览里的外链用系统浏览器打开
- 路径补全（`](` / `![` 后触发）、粘贴 URL 自动链接
- 预览视图为只读 scratch，关闭还原原布局

## 安装

通过 Package Control 安装 `MarkdownInlinePreview`（发布后）。

或开发版：把本目录软链到 `Packages/MarkdownInlinePreview`。

## 使用

- 打开任意 `.md` 文件，按 `ctrl+alt+m`（macOS：`super+ctrl+m`）开启/关闭内嵌预览。
- 预览视图为分栏右侧的只读视图；再次按快捷键或关掉预览 tab 即还原布局。
- 按 `ctrl+alt+shift+m`（macOS：`super+ctrl+shift+m`）开启/关闭浏览器实时预览：
  自动打开系统浏览器，编辑时自动刷新（SSE 推送），服务器只绑定 127.0.0.1、样式全内嵌、离线可用。

## 设置（`MarkdownInlinePreview.sublime-settings`）

| 项 | 默认 | 说明 |
|----|------|------|
| `engine` | `python-markdown` | `markdown-it-py` 为备选（CommonMark 更精准） |
| `extensions` | tables/fenced_code/sane_lists/attr_list/md_in_html/codehilite | python-markdown 扩展开关 |
| `refresh_delay_ms` | 300 | 防抖毫秒 |
| `sync_scroll` | true | 编辑器→预览同步滚动 |

## 引擎

引擎统一接口 `render(text, settings) -> html`，新增引擎 = `mip/engines/` 下加一个文件 + 注册一行。

- **python-markdown**（默认）：PC 依赖频道现成，零安装摩擦。
- **markdown-it-py**（v0.2，已 vendor 进包）：CommonMark 精准度最高，GFM 表格/任务列表/删除线开箱。

## 与 VS Code 预览的能力对照

| 能力 | VS Code | MarkdownInlinePreview |
|------|---------|----------------------|
| 分栏实时预览 | ✅ | ✅ |
| GFM 表格 | ✅ | ✅（div 网格近似，非原生 `<table>`） |
| 任务列表 | ✅ | ✅（`[x]`/`[ ]` 近似） |
| 删除线 | ✅ | ✅（line-through） |
| 代码高亮 | ✅ | ✅（pygments） |
| 同步滚动 | ✅ 双向 | ⚠️ 单向、块级近似 |
| 数学公式 KaTeX | ✅ | ❌（minihtml 禁 `<script>`） |
| 图表 mermaid | ✅ | ❌（同上） |
| 预览内 Ctrl+F | ✅ | ❌（phantom 内容不进缓冲区） |
| 反向同步滚动 | ✅ | ❌（phantom 不接收滚动事件） |
| 浏览器预览 | ✅ | ✅（内置服务器实时模式，样式无限制） |

## 已知架构限制（minihtml 天花板）

Sublime 的 minihtml 是 HTML 子集：不支持 `<table>`/`<input>`/`<script>`/外部 CSS。
因此 GFM 表格用 div 网格近似、任务列表用 `[x]` 近似；数学公式/图表因禁 JS 无法做。
这些是架构死路，不是 bug——详见 plan.md「明确不做的」。
