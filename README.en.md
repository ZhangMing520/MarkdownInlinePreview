# MarkdownInlinePreview

Real-time Markdown preview **inside the Sublime Text editor (split view in the same window)** —
no browser required, no other Sublime packages required.

The rendering engine is configurable (python-markdown by default, markdown-it-py optional).
Published as a standalone Package Control package.

[简体中文](README.md)

## Features

**Two preview modes** (complementary):

- **Inline preview** (`ctrl+alt+m`): rendered via in-editor phantoms in a split view of the
  same window — edit and read side by side, no window switching
- **Live browser preview** (`ctrl+alt+shift+m`): built-in local server + SSE push, rendered
  natively by your browser — full GitHub styling, native tables/checkboxes; **KaTeX math and
  mermaid diagrams** are vendored into the package (works offline, can be disabled via the
  `browser_extras` setting)
- Debounced refresh (300 ms by default) — large documents stay smooth
- GFM rendering: tables (aligned monospace grid for narrow tables, cards for wide ones),
  code highlighting (pygments), task lists, strikethrough, front matter
- In-document anchor links (`#heading` jumps to the matching block)
- One-way scroll sync (editor → preview, block-level approximation)
- Images embedded as base64 (local images instantly, remote ones asynchronously)
- Clicking an external link in the preview opens it in your system browser
- Path completion (triggered after `](` / `![`), paste-URL-as-link
- Preview views are read-only scratch views; closing them restores the original layout

## Installation

Install `MarkdownInlinePreview` via Package Control (once published).

Or for development: symlink this directory into `Packages/MarkdownInlinePreview`.

## Usage

- Open any `.md` file and press `ctrl+alt+m` (macOS: `super+ctrl+m`) to toggle the inline preview.
- The preview is a read-only view in the right pane; press the shortcut again or close the
  preview tab to restore the layout.
- Press `ctrl+alt+shift+m` (macOS: `super+ctrl+shift+m`) to toggle the live browser preview:
  your default browser opens automatically and refreshes as you type (via SSE). The server
  binds to 127.0.0.1 only, all styles are inlined, and it works offline.

## Settings (`MarkdownInlinePreview.sublime-settings`)

| Option | Default | Description |
|--------|---------|-------------|
| `engine` | `python-markdown` | `markdown-it-py` is the alternative (higher CommonMark fidelity) |
| `extensions` | tables/fenced_code/sane_lists/attr_list/md_in_html/codehilite | python-markdown extension switches |
| `refresh_delay_ms` | 300 | Debounce delay in milliseconds |
| `sync_scroll` | true | Editor → preview scroll synchronization |

## Engines

All engines share one interface: `render(text, settings) -> html`. Adding an engine =
one new file in `mip/engines/` + one registration line.

- **python-markdown** (default): already available through Package Control's dependency
  channel — zero installation friction.
- **markdown-it-py** (v0.2, vendored into the package): highest CommonMark fidelity,
  GFM tables/task lists/strikethrough out of the box.

## Feature comparison with VS Code preview

| Capability | VS Code | MarkdownInlinePreview |
|------------|---------|---------------------|
| Split live preview | ✅ | ✅ |
| GFM tables | ✅ | ✅ (approximated with a div grid, not native `<table>`) |
| Task lists | ✅ | ✅ (approximated as `[x]` / `[ ]`) |
| Strikethrough | ✅ | ✅ (line-through) |
| Code highlighting | ✅ | ✅ (pygments) |
| Scroll sync | ✅ bidirectional | ⚠️ one-way, block-level approximation |
| KaTeX math | ✅ | ❌ (minihtml forbids `<script>`) |
| mermaid diagrams | ✅ | ❌ (same reason) |
| Ctrl+F inside preview | ✅ | ❌ (phantom content is not in a buffer) |
| Reverse scroll sync | ✅ | ❌ (phantoms do not receive scroll events) |
| Browser preview | ✅ | ✅ (built-in server with live-mode push, no style limits) |

## Known architectural limits (the minihtml ceiling)

Sublime's minihtml is a subset of HTML: no `<table>` / `<input>` / `<script>` / external CSS.
That is why GFM tables are approximated with a div grid and task lists with `[x]`;
math and diagrams are impossible because JavaScript is not allowed.
These are hard architectural limits, not bugs — see plan.md, "明确不做的" (Explicitly not doing).
