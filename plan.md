# MarkdownInlinePreview — 开发计划

一个 Sublime Text 插件：在编辑器内部（同窗口分栏）实时预览 Markdown，
渲染引擎可配置，独立发布到 Package Control，不依赖任何其他 Sublime 包
（尤其不依赖 MarkdownPreview）。

## 背景与定位

- 目标不是 1:1 复刻 VS Code 的 Markdown 预览，而是实现其"日用核心"：
  分栏预览、实时刷新、GFM 渲染、单向同步滚动。
- Sublime 的 minihtml 是 HTML 子集（无 `<script>`、无外部 CSS/资源），
  这决定了架构天花板，见文末"明确不做的"。
- 参考 math2001/MarkdownLivePreview（2019 年停更）的骨架：
  markdown → html → base64 内嵌图片 → phantom 显示；
  其表格缺失、有序列表 bug、未保存文件 NameError 等问题全部重写规避。

## 架构

```
MarkdownInlinePreview/
├── .python-version            # 内容 "3.8"：opt 进 ST4 的 Python 3.8 插件宿主（默认回落 3.3 宿主，会导致 markdown-it-py(3.6+) import 失败、依赖频道装到 3.3 变体）
├── dependencies.json          # 声明 python-markdown、pygments（PC 依赖频道现成有）
├── MarkdownInlinePreview.py   # 根模块：import 全部子模块，plugin_loaded/unloaded
├── mip/
│   ├── engines/
│   │   ├── __init__.py        # 引擎注册表：按 settings["engine"] 分发；缺库降级 + 状态栏提示
│   │   ├── engine.py          # 统一接口 render(text, settings) -> html
│   │   ├── py_md.py           # python-markdown 引擎（默认）
│   │   └── mdit.py            # markdown-it-py 引擎（v0.2，可选）
│   ├── normalize.py           # 引擎输出 → 规范 HTML：隔离各引擎 HTML 方言，转换层只针对规范 HTML 写一次
│   ├── render.py              # 规范 HTML → minihtml 适配：标签转换层(table→div网格/input→[x]/del→line-through)、图片 base64、<style> 内嵌配色、白名单清理、逐块分片
│   ├── preview.py             # 命令(toggle) + 视图管理：分栏、空白预览视图(scratch/只读)、逐块多 phantom、关闭还原布局
│   ├── listener.py            # ViewEventListener：on_modified_async 防抖刷新、
│   │                          # on_selection_modified_async 同步滚动、on_close 还原布局、plugin_loaded 清理孤儿视图
│   ├── settings.py            # 设置读取 + on_settings_change 热更新
│   └── completions.py         # 路径补全 + 粘贴 URL 自动链接命令（v0.3）
├── tests/
│   ├── conftest.py            # sublime/sublime_plugin shim（仿 SyncSettings/tests 做法）
│   ├── test_engines.py        # 引擎纯 Python 直测，无需 Sublime
│   └── test_render.py
├── messages.json + messages/  # Package Control 版本说明，每个 release 一条
├── README.md
├── LICENSE                    # MIT
└── CHANGELOG.md
```

> 宿主版本：`.python-version` 内容为 `3.8` 时，包运行在 ST4 的 Python 3.8 插件宿主；不写则回落旧版
> 3.3 宿主（markdown-it-py 要求 3.6+、新版 python-markdown 均可能失败，且 PC 依赖频道按 3.3 变体安装）。
> 最低支持 ST4 build 4000+（首个带 3.8 宿主的 ST4），建议 4107+。
> 注意：ST build 4200+ 已将现代宿主升到 Python 3.14、3.3 默认禁用，目标版本若更新需相应调整 `.python-version` 取值。

### 渲染引擎配置项（核心设计）

`MarkdownInlinePreview.sublime-settings`：

```jsonc
{
    // 渲染引擎："python-markdown"（默认）| "markdown-it-py"
    "engine": "python-markdown",

    // 传给引擎的扩展开关（python-markdown 的 extensions 名）
    // 注意：tables 覆盖了 GFM 表格；但任务列表(- [ ])与删除线(~~x~~)默认扩展不支持，
    // 需额外扩展：手写极小扩展，或 vendor pymdown-extensions 子集（见依赖策略）
    "extensions": ["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"],

    // 刷新防抖毫秒数
    "refresh_delay_ms": 300,

    // 光标移动时同步滚动预览
    "sync_scroll": true
}
```

- 统一接口：`render(text: str, settings: dict) -> str (html)`。
- 注册表模式：新增引擎 = `engines/` 下加一个文件 + 注册一行，核心不动。
- 引擎库缺失时**不报错**：降级到可用引擎，状态栏提示一次。
- 渲染管线：`引擎 HTML` → `normalize.py` 归一到**规范 HTML** → `render.py` 转换层（只认规范 HTML）。
  新增引擎只需在其适配器里产出规范 HTML（或加一段 normalize 适配），转换层代码不动，避免为每个引擎
  重写 table→div / input→`[x]` 等逻辑（否则 3 个引擎 = 3 套方言适配）。
- 引擎按需添加（YAGNI）：架构已支持 N 引擎零边际成本，但每加一个就多一份上游维护 + 转换层方言适配。
  v0.1 只 python-markdown；v0.2 加 markdown-it-py（CommonMark 精准度这一真实卖点）；
  mistune / markdown2 等仅在有明确用户需求时再加，不为"多选"而加。

### 依赖策略

| 依赖 | 方式 | 说明 |
|------|------|------|
| python-markdown | `dependencies.json` 声明 | PC 依赖频道现成有（OmniMarkupPreviewer 同路线） |
| pygments | `dependencies.json` 声明 | 用于 codehilite 代码高亮 |
| markdown-it-py | v0.2 再定：vendor 进包（MIT，纯 Python）或向 PC 依赖频道提 PR | 不作为 v0.1 依赖 |
| pymdown-extensions（子集） | ✅ 已 vendor（10.15 取 5 个文件：tasklist/tilde/util 等） | 默认引擎的任务列表与删除线；经 vendor_loader.activate() 激活，zip 安装同样解压可用 |
| ~~MarkdownPreview~~ | 不依赖 | 用户明确要求；如将来需要"与浏览器预览一致"，允许用户配置 engine 指向已安装的 MarkdownPreview 作为可选引擎，但不是包的依赖 |

> vendor 说明：把第三方库的**纯 Python 源码**直接复制进包内（如 `mip/vendor/markdown_it/`）随插件分发，
> 不依赖 Package Control 依赖频道。仅适用于纯 Python 库；需编译 C 的库（cmark/Misaka 等）虽可针对 ST 内置
> Python 逐平台编译分发，但 ABI 精确匹配 + 多平台构建矩阵 + 分发/签名成本远超纯 Python 引擎收益，故不采用。

> vendor 维护成本：vendoring 等于冻结一份源码，上游 bug/CVE 需手动重新 vendor（无 pip upgrade）。
> 故引擎按需添加（YAGNI）——默认 python-markdown 走 PC 频道零维护；markdown-it-py 仅 v0.2 启用；
> mistune/markdown2 等有明确需求再加。新增引擎边际架构成本≈0，但持续维护成本随引擎数线性增长。

### minihtml 适配要点（render.py）

- **minihtml 标签转换层（核心，与引擎无关）**：minihtml 明确不支持 `<table>`/`<input>`/`<button>`/`<del>`
  等标签（官方文档："Other HTML tags … are not implemented, e.g. `<input>`, `<button>`, `<table>`"）。
  引擎产出的这些必须在此转换——`<table>`→嵌套 `<div>`(display:inline-block + border)网格；
  `<input type=checkbox>`→`[x]`/`[ ]` 文本或带样式的 span；`<del>`/`<s>`→`<span style="text-decoration:line-through">`
  （`text-decoration` minihtml 支持）。这是 GFM 表格/任务列表/删除线能显示的唯一途径，**与选哪个引擎无关**。
- 图片（本地/远程）→ base64 data URL 内嵌；远程图片线程池异步，加载完成后**合并(coalesce)再重渲染**，
  已内嵌图片走缓存不重复请求，避免多图互相触发整篇重渲染抖动。HTTP 客户端用标准库 `urllib`
  （零新增依赖，不引入 requests，否则 dependencies.json 还要加）。
- 长文档分块：预览视图为**空白专用视图**，按 Markdown 顶层块逐段插入多个 phantom（每段一个，
  host 缓冲每行挂一个），整篇随视图自然滚动；规避单个 phantom 的尺寸上限（单 LAYOUT_BLOCK 放不下长文）。
- 外部 CSS / `<script>` 全部剥离；样式收敛为内联 style，预置一份接近 GitHub 观感的紧凑样式。
- 版式设计有据可查：浏览器模式的完整版式逐值对齐 GitHub——实测 github.com blob 页正文列
  （1006px/行高 1.5/段距 16px/h 系列 margin 24-16），并对照 github-markdown-css 5.8.1 权威值；
  关键版式规则注释标注出处（[实测]/[gmc]/[增补]），禁止凭感觉设值。
- 代码块：codehilite 输出 `<span class=...>`，在 phantom `<body>` 内嵌一段 `<style>` 把 pygments
  类名（`.c1`/`.k`/`.s` …）映射到固定色；结合 `<html>` 自动加的 `dark`/`light` 类适配明暗主题。
  不跟随编辑器主题（TextMate 高亮无法复用，架构限制）。无需逐 token 转 inline。
- **链接交互**：phantom 的 `<a>` + `on_navigate` 是 minihtml 唯一交互通道。v0.1：点击外链用系统浏览器打开
  （几行）；v0.2：文内锚点 `#heading` → 定位并 `view.show()` 对应块。
- 未保存文件（无 `file_name`）：按缓冲区内容正常渲染，不触发 MarkdownLivePreview 的 erase/edit 崩溃路径。

### 预览视图与监听规范（v0.1 即定）

- 预览视图属性：`set_scratch(True)`（关 tab 不弹保存）+ 只读（防在预览里打字）+ 关行号 + 专用隐藏 syntax；
  并打内部 tag（如 `settings.set("mip_preview", True)`）作为"关闭还原布局"时识别预览视图的标记，避免误伤普通视图。
- 命令 `preview` 为 **toggle**（按源视图）：对同一文件再次触发即关闭它的预览；
  不同文件分别触发 → 右栏各开一个预览标签页（注册表 `window_id → {source_view_id: manager}`，
  与浏览器模式一致）。布局状态机上移到窗口级：首个预览切两栏、**末个**预览关闭才还原布局。
  （v0.1 曾为"一窗口一预览、切文件复用同一视图"，多标签需求下改为按源视图隔离。）
- `listener.py` 监听：`on_modified_async`（防抖刷新，避免大文档卡 UI）、`on_selection_modified_async`
  （同步滚动）、`on_activated_async`（左栏切源文件标签时右栏跟随切预览标签，可由
  `preview_tab_follows_source` 关闭；右栏前台已是对应预览时不切换，还焦点给源视图的
  那次激活也因此不会被拉回）、
  `on_close`（关源视图→关其预览；手动关预览 tab→摘除；末个→还原布局）；
  `plugin_loaded` 扫描并清理上次 reload 遗留的孤儿视图（开发期频繁 reload 必然产生）。

## 分期与验收

### v0.1 — MVP 闭环
- [x] 仓库骨架 + sublime shim 测试基座跑通
- [x] `preview` 命令：同窗口分栏打开**空白预览视图**，按顶层块插入多个 phantom（逐块，非单 LAYOUT_BLOCK）
- [x] python-markdown 引擎（tables/fenced_code/sane_lists/attr_list/md_in_html）+ pygments 高亮
      （任务列表/删除线：v0.2 起 mdit 引擎原生支持；默认引擎经 vendored pymdownx 子集同样支持）
- [x] on_modified 防抖实时刷新
- [x] 图片 base64 内嵌（本地 + 远程异步）
- [x] 关闭预览还原原布局
- [x] 快捷键（默认 `ctrl+alt+m`；macOS 映射 `super+ctrl+m`，keymap 分 Default / OSX 两个文件写）+ 设置文件带注释
- [x] 锚点跳转（预览内 `#heading` 链接 → 定位并滚动到对应块；两引擎均有标题 id）
- [x] zip 安装兼容（vendor/assets 按需解压到 sublime.cache_path()，按 zip mtime+size 缓存键清理旧目录）
- 验收：本机 Sublime 打开任意 README，边写边看，表格(经 div 转换)/代码块高亮/任务列表(经转换)正常显示。

### v0.2 — 体验
- [x] 编辑器→预览同步滚动（编辑器行 → 对应块的 host 行 `view.show()`，**块级近似对齐**，非像素级；不做反向）
- [x] YAML front matter 渲染为表格
- [x] markdown-it-py 引擎 + mdit-py-plugins（tables/tasklists/strikethrough，已 vendor 进 mip/vendor）。
      v0.4 起 vendor 升级为 **markdown-it-py 4.2.0 + mdit-py-plugins 0.6.1 + mdurl 0.1.2**
      （此前钉死 2.2.0/0.3.5 的原因是 3.8 宿主）。4.x/0.6.x 要求 Python 3.10+：3.8 宿主
      实测抛 TypeError（`'ABCMeta' object is not subscriptable`，不是预想的 SyntaxError），
      注册层懒加载/构造阶段统一捕获 ImportError/SyntaxError/TypeError，优雅回落
      python-markdown 并在状态栏说明（消息与"未知引擎"区分）。表格/删除线经实测由 4.x
      `"default"` preset 默认提供（preset 的 components 为空但规则构造期 enable），
      不用 0.6 聚合 gfm 插件（捆绑脚注/alerts/裸链接 autolink，会改变输出）；
      anchors 插件 0.6.1 仍在（默认只覆盖 h1/h2，与旧版逐字节一致）。
- [x] 引擎降级与状态栏提示（缺库降级 + `sublime.status_message`）
- [x] **浏览器实时预览**（`ctrl+alt+shift+m` / macOS `super+ctrl+shift+m`）：内置 127.0.0.1 HTTP
      服务器（`mip/browser_server.py`，纯 Python 可单测）+ SSE 推送 + EventSource 自动重连。
      复用同一引擎但**跳过 minihtml 标签转换层**——浏览器原生渲染 `<table>`/`<input>`/`<del>`，
      GitHub 风格 CSS 全内嵌（亮暗跟随系统）、pygments 高亮、离线零外部请求。
      这是"跳出 minihtml 限制"的正式通道：KaTeX/mermaid 已 vendor 进 mip/assets（`browser_extras`
      设置可关，npmmirror 下载，woff2 字体齐全，客户端 auto-render + mermaid.run 随 SSE 更新重跑）。
- [x] 增量 phantom 更新：块数不变时只重插内容变化的块（差分对比，未变块原地保留消除闪烁）
- [x] 渲染后台线程化（async_render.py）：取源文本/应用 phantom 留主线程，引擎转换 + 图片 IO
      在单一 daemon 工作线程串行执行（引擎实例是进程级单例、vendor_loader 临时改 sys.path，
      均不可并发；单线程既移出 UI 线程又天然消除竞态）。同预览排队任务 coalesce 只留最新，
      回调经 set_timeout 回主线程并做代际/视图有效性校验丢弃过期结果；浏览器首帧渲染完成
      后才打开浏览器，避免打开瞬间 404

### v0.3 — 发布件
- [x] 路径补全（`on_query_completions`：`![](` / `[](` 触发文件路径补全）
- [x] 粘贴 URL 覆盖选中文字 → 自动链接（小命令 `mip_paste_url_as_link`）
- [x] README（含与 VS Code 预览的能力对照表，管理预期）
- [x] messages.json / CHANGELOG / LICENSE / tag `v0.3.0`
- [ ] 提 PR 到 wbond/package_control_channel（注册 git 仓库，release 走 tag）——**需在本机/仓库侧执行，非代码层**

## 明确不做的（架构死路，防止范围蔓延）

- minihtml 模式下的 KaTeX / mermaid —— 依赖 JS，minihtml 禁止 `<script>`；已通过浏览器实时
  预览模式实现（vendor JS 进包），minihtml 内仍不做。
- 预览内 Ctrl+F —— phantom 内容不进缓冲区。
- 预览→编辑器反向同步滚动 —— phantom 不接收滚动事件。
- 拖拽图片插入 —— Sublime 未向插件暴露文件拖放事件。
- webview/JS 扩展生态 —— minihtml 非 webview。
- 原生 GFM 表格 / 复选框 —— minihtml 不支持 `<table>`/`<input>`，**但可经 render.py 转换层近似呈现**
  （table→div 网格、input→`[x]`），属"能做"，不在此死路清单内，只是非原生渲染。

## 开发约定

- 测试：引擎与 render 层纯 Python，脱离 Sublime 用 shim 直测（沿用 SyncSettings 仓库
  `tests/mocks/sublime_mock.py` 的做法）；`.venv` + pytest，提交前全绿。
- dev 依赖：`.venv` 需安装 `Markdown` / `pygments` 才能跑引擎测试；render 层测试用标准库 `html.parser`
  解析 HTML 即可，不引入 bs4。
- 规范：flake8 max-line-length 120；提交信息 `feat:/fix:/refactor:` 前缀，一提交一逻辑。
- 调试：开发版软链到本机 Sublime Packages 目录，改动后靠 `1_reloader` 式重载或重启验证。
