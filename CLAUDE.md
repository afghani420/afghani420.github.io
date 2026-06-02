# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`afghani420.github.io` is a GitHub Pages **user site**. Whatever is on the `main` branch at the repo root is served live at `https://afghani420.github.io/`. There is no build system, package manager, framework, or Jekyll config — the static files committed here are exactly what ships.

## Architecture

The site is a hub of small, self-contained browser utilities, each in its own directory:

- `index.html` — the landing page (titled 物置, "storage shed"). It is a hand-maintained directory of tools, each a `<a class="tool">` card. Some cards link to **other repositories' Pages sites** (e.g. `keiba-ai-blog`), others to local subdirectories. Adding a tool means adding its card here by hand.
- `ali-search/index.html` — "Ali Multi-Search": type a phrase in Japanese, it translates to English and Chinese and generates three AliExpress search links.

### Single-file tool convention

Every page is **one self-contained HTML file** with its CSS in an inline `<style>` and its logic in an inline `<script>` — no shared stylesheet, no JS modules, no external dependencies beyond Google Fonts and runtime API calls. When adding or editing a tool, keep it within its single `index.html`; do not introduce a bundler or split files unless the user asks.

### Shared design language (copy it, there's no shared file)

All pages reuse the same visual system, redefined per-file via CSS custom properties on `:root`:

- Palette: cream background `--bg: #faf8f5`, near-black ink `--ink: #1a1a1a`, red-orange accent `--accent: #e62e04`, hairline borders `--line: #e8e4dd`.
- Type: `Fraunces` (serif, for headings/display — italic + accent color for emphasis via `<em>`) and `JetBrains Mono` (body), loaded from Google Fonts.
- Cards use a `border-left` accent stripe that shifts color on hover/state. `ali-search` color-codes by language (`--jp`/`--en`/`--zh`, keyed off a `data-lang` attribute).
- UI text is Japanese; keep that convention.

### How `ali-search` works

- Translation: `https://api.mymemory.translated.net/get?q=…&langpair=ja|<target>` (a free, key-less API), called once per target language via `Promise.all`. Targets are `en` and `zh-CN`.
- Search links: built against `https://www.aliexpress.com/wholesale?SearchText=…`, with a `sortBy` param driven by the sort toggle (`price_asc` / `total_tranpro_desc` / `default`).
- Search history is persisted in `localStorage` under the key `ali_hist` (max 12 entries); all `localStorage` access is wrapped in try/catch.

## Working in this repo

- **No build/lint/test.** To verify a change, open the HTML file directly in a browser (or run any static server, e.g. `python3 -m http.server`, and visit the path). Note that `ali-search` makes live external API/network calls.
- **Deploy = push to `main`.** GitHub Pages serves the branch directly; there is no CI build step for the site.
- Test on mobile widths — the pages are mobile-first (viewport is locked to `maximum-scale=1.0`, with iOS web-app meta tags).

## Not in this repo (intentionally)

`.gitignore` excludes a local-only **sake-lottery** project (`sake-lottery/`, `scripts/fetch_lottery.py`, `requirements-lottery.txt`, `.github/workflows/fetch_lottery.yml`, `.api-keys.env`). Per the git history it was deliberately removed from GitHub but kept on the local machine. Do **not** re-add these to version control, and never commit `.api-keys.env` or any secrets.
