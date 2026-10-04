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
- **浏览器模式版式逐值对齐 GitHub**：实测 github.com 文件页（blob）正文列 1006px/行高 1.5/
  段距 16px/h 系列 margin 24-16 等，并对照 github-markdown-css 5.8.1（列宽 1012px、内联代码
  底 #818b981f、表格 6px 13px、引用 0 1em、hr .25em、暗色板 #f0f6fc/#3d444d/#151b23 等）；
  关键版式规则在源码注释标注出处（[实测]/[gmc]/[增补]）。
- **修复无语言标注代码块被染红**：codehilite 关闭 guess_lang——pygments 的语言猜测会把
  目录树等纯文本的制表线字符（├── │）判成 error token，在浏览器模式的完整 pygments 样式下
  显示为红色方块。无语言标注的围栏块现在按纯文本渲染（与 GitHub 行为一致）。
- **修复浏览器模式 SSE 通道失效（含实时刷新与同步滚动）**：页面模板里 EventSource 用相对
  路径 "events"，在无尾斜杠的 /{doc} 页面 URL 下被解析成根级 /events 而 404——真浏览器里
  实时刷新和同步滚动从未生效过（pytest 直连绝对路径未暴露）。改为 location.pathname 拼接。
- **围栏语言别名归一**：只映射捆绑 pygments 解析不到的语言名——jsonc→json、json5→json、
  yml→yaml（此前这些名字直接素色）。sh/zsh/golang/rs/c++/cs/docker/objc 等 pygments 原生
  别名不进表、不改写（原生已能高亮，强行映射反而会把 console/asm 的正确词法改坏）；
  所有围栏开行（含无语言的）都纳入跟踪，嵌套围栏里展示的代码字样不受影响。
  注意：markdown-it-py 引擎目前无高亮（pygments 只接在默认引擎上）。
- **修复多文件预览互相覆盖**：浏览器预览文档原按窗口编号，同窗口打开第二个文件的预览会
  覆盖第一个（两个标签页同 URL 同内容）。改为按源视图隔离——每个文件独立文档/URL/标签页，
  可同时开任意多个；toggle 按当前文件生效（关 A 的预览需聚焦 A 再按快捷键）。
  新增 on_window_close 兜底：关窗时逐个视图的 on_close 不可依赖，按视图注册的
  manager 与服务器文档须按窗口整体注销，否则成批泄漏。
- **页面标签按文件命名**：VS Code 惯例 "Preview <文件名>"（如 "Preview README.md"），
  多个预览标签可区分；未保存文件取缓冲区显示名（View.name()，可被用户改）避免标签同名；
  标题变化经新增的 "t" 帧推送，无需重发整页。
- **修复同步滚动从未生效**：cursor_ratio 调用了不存在的 View.line_count()（官方 API 无此
  方法，任何宿主都会 AttributeError 且被静默吞掉），改用 rowcol(view.size()) 计算行数。
- **修复 Python 3.14 宿主崩溃**：ST 4205+ 的 3.14 宿主向 ViewEventListener.is_applicable
  传 view.settings()（Settings 对象）而非 View，is_preview_view 改为双形态兼容
  （Build 4215 真机验证的崩溃点）。
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
