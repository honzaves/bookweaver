# Handoff: BookWeaver — Guided Wizard UI

## Overview
BookWeaver is a **local-first desktop app** that transforms an English EPUB into a
graded-Spanish (or condensed-English) version using a local AI model (Ollama),
with optional MP3 audiobook output (Kokoro TTS). Nothing leaves the user's
machine.

This handoff covers the chosen **"Guided Wizard"** direction: BookWeaver's long,
dense, adaptive configuration form reframed as a **4-step stepper**
(Book → Transform → Output → Run) with a **persistent run drawer** pinned to the
bottom that expands and takes over once a job starts.

Two documents define the work:
- **`ui-design-brief.md`** (in this folder) — the authoritative description of
  *what the product does*: every control, range/default, conditional reveal, and
  all seven app states. **Read it first; it is the source of truth for behavior.**
- **This README** — how the wizard *arranges and styles* that behavior, with
  exact measurements.

---

## About the Design Files
`BookWeaver Wizard.dc.html` is a **design reference created in HTML** — an
interactive hi-fi prototype showing the intended look and behavior. It is **not
production code to copy directly**, and it uses a custom HTML component format you
do **not** need to run or import.

The task is to **recreate this design in BookWeaver's real codebase** using its
established environment and patterns. The brief states the current app is built in
**Qt** (desktop). If you're reimplementing in the existing Qt app, use its native
widgets/layouts and translate the measurements below into the equivalent Qt
styling. If a new stack is being chosen (Electron + React, Tauri, SwiftUI, etc.),
pick what fits the project and implement the design there. Either way: **match the
layout, spacing, behavior, and visual identity specified here.**

The `screenshots/` folder shows every screen and state (see index at the bottom).

## Fidelity
**High-fidelity (hi-fi).** Final colors, typography, spacing, radii, and
interactions are specified below and should be matched closely. Recreate the UI
**pixel-accurately** in the target stack's idioms. The base canvas was designed at
an **860 × 724 px** window (the brief's window is min ~700×820 / default ~760×900;
the app window is resizable — treat 860×724 as the reference, not a hard cap, and
let the content area scroll).

---

## Design tokens (exact)

### Color
| Role | Hex |
|---|---|
| App background (behind window) | `#0a0a08` |
| Window background | `#111210` |
| Surface (group cards, title bar) | `#1a1b18` |
| Inset / input / list background | `#0f0f0c` |
| Console background (deepest) | `#0c0c09` |
| Footer background | `#16160f` |
| Border (default) | `#2e2f2a` |
| Border (input) | `#36372f` |
| Border (strong / control outline) | `#3a3b34` / `#4a4b42` |
| **Amber accent (primary)** | `#d4a853` |
| Amber hover | `#deb469` |
| Amber dim / dotted underline | `#8a6a2e` |
| Text (primary) | `#e8e4d9` |
| Text (secondary) | `#cfc9ba` |
| Muted | `#7a7870` |
| Muted-2 (labels) | `#8a8678` |
| Faint (placeholder, scale ends) | `#6c6a62` / `#55564d` |
| Success / sweet green | `#7aab6e` |
| Warning amber | `#c98d3a` |
| Error red | `#c0604a` |
| Selected-tile fill | `#211c12` |

### Type
- **UI font:** `-apple-system, "Helvetica Neue", Helvetica, system-ui, sans-serif`.
- **Monospace** (paths, field values, readouts, log, numbers):
  `ui-monospace, Menlo, monospace`.
- **Decorative accent (optional):** "Caveat" (Google Fonts) for the per-step
  hand-lettered prompts ("how should we transform it?"). Purely cosmetic — drop it
  if it doesn't fit; replace with a normal muted heading.
- Scale:
  - App title `19px / 700`, letter-spacing `-0.5px`, color amber.
  - Subtitle `12px`, muted.
  - Group-card titles `9.5px / 600`, **uppercase**, letter-spacing `0.14em`, muted-2.
  - Body / labels `11–13px`.
  - Field & log text `12–12.5px` monospace, line-height `1.7` in the log.
  - Section-prompt (Caveat) `16px`.

### Shape, spacing, elevation
- Radii: window `12px`; group cards / mode tiles `9px`; inputs, buttons, notes
  `7–8px`; checkboxes `5px`; progress bar, ticks-pill, sweet-spot tag fully round
  (`99px`).
- Window shadow: `0 30px 70px -20px rgba(0,0,0,.7)`, plus a `1px` amber-tinted
  hairline ring at `rgba(212,168,83,.04)`.
- Selected mode tile: `1px` amber border + `inset 0 0 0 1px rgba(212,168,83,.25)`.
- Spacing rhythm: `26px` horizontal page padding; `13px` gap between stacked
  cards; `11px` inside-card grid gaps; `8–14px` control padding.

### Iconography
Sparing emoji as accents only: ▶ Start · ⏩ Resume · 🟢 / ✦ sweet spot · ℹ️ note ·
🎉 done · 💾 saved · ✓ checks. Chevrons `▾` (dropdown) and `▴▾` (steppers).

---

## Global frame (every step)

Vertical stack inside the window, top → bottom:

1. **Title bar** — `38px` tall, `#1a1b18`, bottom border `#2e2f2a`. Three `11px`
   traffic-light dots (`#34352e`) + monospace "BookWeaver" label at `#6c6a62`.
2. **Header** — padding `17px 26px 0`. Title **"BookWeaver"** (`19px/700`, amber,
   `-0.5px`) over subtitle **"EPUB → Spanish rewriter via Ollama"** (`12px`,
   muted). A **`2px` amber rule** (linear-gradient `#d4a853` → transparent at 70%)
   sits `13px` below, full content width.
3. **Step rail** — padding `16px 26px 4px`, horizontal, `9px` gaps. Four steps,
   each = a `23px` circular number badge + label, joined by `1px` connector lines
   (`#2e2f2a`, `flex:1`). The whole step is clickable.
   - *Active:* badge **amber-filled** (`#d4a853`, dark `#191610` number), label
     amber `600`.
   - *Completed:* badge `#26271f` fill with a `✓`, label `#cfc9ba`.
   - *Upcoming:* badge outlined `#3a3b34`, number + label muted.
4. **Recap line** *(shown from step 2 on)* — padding `3px 26px 0`, `11.5px`
   faint. Recaps step-1 choices, e.g. `Step 1 · middlemarch.epub · 11 chapters ·
   Gemma 4 31B · B2`, with an amber dotted-underline **"edit"** that jumps to
   step 1.
5. **Content area** — `flex:1`, vertically scrollable, padding `18px 26px 22px`,
   children stacked with `13px` gap. (Custom `10px` amber-tinted scrollbar.)
6. **Footer (pinned run drawer)** — `flex:none`, top border `#2e2f2a`, bg
   `#16160f`, padding `13px 26px`, items `14px` gap. Contents are contextual
   (see each step + Run).

**Group card** (`.gc`) — the repeated container: bg `#1a1b18`, `1px #2e2f2a`
border, radius `9px`, padding `13px 14px`. Its title row is the uppercase muted-2
label, optionally with a right-aligned monospace meta (e.g. `11 / 11 selected`,
`at least one`).

**Field / input** — bg `#0f0f0c`, `1px #36372f` border, radius `7px`, padding
`9px 11px`, `12.5px` monospace text. Dropdowns add a right `▾` and a hover
border-brighten to `#55564d`. Numeric steppers show value + suffix + `▴▾`.

**Buttons** — radius `7px`, padding `8px 13px`. *Primary:* amber fill `#d4a853`,
dark text, `600` (hover `#deb469`; disabled `#3a3528` bg / `#6c6453` text).
*Danger:* `#23130f` bg, `#5a3127` border, `#c0604a` text (Abort; disabled =
40% opacity). *Ghost:* transparent, muted text → brightens on hover (Back, Clear).

**Checkbox** — `17px` square, radius `5px`, `1.5px #4a4b42` border; checked =
amber fill + dark `✓`; **partial (tri-state)** = `#3a3528` fill, `#8a6a2e` border,
amber `–` glyph; disabled = dim.

---

## Target language (derived) — gates several controls
Several controls only make sense when the **output is Spanish**. There is no
explicit "target language" picker; it is **derived from the mode** (and the
key-ideas toggle):

```
targetIsSpanish = mode === 'summariseRewrite'
              ||  mode === 'fullTranslation'
              || (mode === 'keyIdeas' && keyIdeasLanguage === 'es')
// 'summariseOnly' (English) → false
```

When `targetIsSpanish` is **false**, hide the **Spanish level** dropdown (step 2)
and drop the level from the recap line. When it flips back to true, restore it. The
default mode is Spanish, so it's visible on a fresh start. (The Cross-chunk
continuity dropdown is **not** gated — it's always shown.)

---

## Screens / Views

### Step 1 — Book  (`screenshots/01-step1-book.png`)
**Purpose:** identify the book and choose what to process.
- **EPUB file** card: read-only path field (`flex:1`) + **"Browse…"** button
  (filters `.epub`). Helper line: "Selecting a file reads title, author & chapters,
  and pre-fills the output folder." Selecting triggers metadata + chapter
  extraction and pre-fills the output folder to the book's folder.
- **Chapters** card: title meta shows live `N / total selected`. A **tri-state
  "Select all"** checkbox row, then a scrollable list (`max-height 188px`, inset
  `#0f0f0c`, radius `8px`). Each row: checkbox + zero-padded monospace number
  (`01.`) + title; row hover `#181812`. All checked by default; ≥1 required to
  start.
- **Ollama model** card (full width): dropdown "Gemma 4 31B (recommended)" ▾.
  *(The Spanish level dropdown used to sit here — it now lives in step 2, since it
  depends on the mode chosen there; see Step 2.)*

### Step 2 — Transform  (`02-step2-transform.png`, `03-…full-translation.png`, `04-…key-ideas.png`)
**Purpose:** the heart of the app — choose the mode and tune the two sliders.
- **Mode selector** — a **2×2 grid** of tiles (`10px` gap). Each tile: a `16px`
  radio + bold `13px` title + a `11px` muted description (indented `25px`).
  Selected tile = amber border + `#211c12` fill + inset amber ring; the radio
  fills with an `8px` amber dot.
  1. **Summarise → rewrite** *(default)* — "condense, then retell in Spanish at
     your level"
  2. **Full translation** — "whole text, nothing cut — slower"
  3. **Summarise only (EN)** — "condensed English, no translation"
  4. **Summary + key ideas** — "+ a book-wide synthesis at the end"
- **Two slider cards** in a `2-col` grid below.
- **Conditional reveals** (animate height/opacity ~150–200ms; don't pop):
  - **Summarisation depth** card shows for every mode **except Full translation**,
    where it collapses and the creativity card spans the row.
  - **Full translation** → info note "⚠️ Full text is translated directly — expect
    longer model calls. Consider raising the timeout in step 3."
  - **Summarise only** → info note about English-only output.
  - **Summary + key ideas** → a **"Key-ideas output language"** card with two
    tiles: *Spanish (at B2)* / *English*. Note: "Changing this re-populates the
    MP3 voice list in step 3." (And it must actually re-populate it.) Because this
    toggle can flip `targetIsSpanish`, it also drives the Spanish-only cards below.
- **Spanish level** dropdown card — **shown only when `targetIsSpanish`**, placed
  directly **above** the Cross-chunk continuity card. Dropdown (`max-width 280px`)
  "B2 — Vantage" ▾; levels `B1 — Threshold`, `B2 — Vantage` (default),
  `C1 — Advanced`, `C2 — Mastery`. Helper: "Target CEFR level for the rewritten
  Spanish." *(Lives here rather than step 1 because it only applies when the mode
  produces Spanish output — a step-1 control can't depend on a step-2 choice.)*
- **Cross-chunk continuity** card (`screenshots/04b-step2-cross-chunk-continuity.png`)
  — **always visible** (applies whenever a chapter is split into chunks,
  regardless of mode/language). A styled **`<select>` dropdown** (`max-width 340px`,
  the `.selraw` control — inset field with a right chevron), **default Off**, plus
  a live info note below that updates with the selection. Four options (brief §5):
  1. **Off — no continuity aid** *(default)* — "No continuity aid — each chunk is
     processed independently."
  2. **Names only — protect proper nouns** — character/place names found in each
     chunk's source are passed to the model so spellings stay consistent across
     chunks. No extra model calls.
  3. **Prose tail — scene-gated carry-over** — the last ~120 words of the previous
     chunk's output are carried into the next prompt for smoother transitions; the
     carry resets at scene breaks & chapter starts. **Also hard-splits chapters at
     scene breaks (`* * *`, `---`, `<hr>`), which can add model calls / progress
     steps**; a `* * *` separator is restored in the output so nothing is lost.
  4. **Both — names + prose tail** — both mechanisms together; highest continuity,
     may add model calls at scene breaks.
  State: `crossChunkContinuity` = `off | names | tail | both`. The descriptive
  note beneath the dropdown communicates each option's cost/benefit.

**The two sliders — preserve exactly (brief §5):**
- *Track* `6px`, radius `99px`, `#2a2b24`, with faint tick marks; *knob* `17px`
  amber with `2px #15150f` ring + soft shadow. Implement as a custom track + knob
  with an invisible native range overlay for interaction.
- **Summarisation depth (keep %):** range **10–90**, default **40**, ticks every
  **10%**. Readout `Keep 40% of original (↓ 60% reduction)`. **Sweet spot
  30–50%** → readout + knob + fill turn **green** and a **"✦ sweet spot"** pill
  appears; legend "🟢 30–50% keeps the core story without noise". Outside sweet
  spot the readout/fill are muted (`#9a978c`), knob amber.
- **Creativity:** range **1–10**, default **5**, ticks every **1**. Readout
  `<Name> — level N/10  (temp ≈ 0.xx)` where temp = `((N-1)/9)`. **Named notches:**
  1 Verbatim, 2 Faithful, 3 Faithful+, 4 Enriched, 5 Enriched+, 6 Vivid,
  7 Expressive, 8 Inventive, 9 Free, 10 Unbound. **Color ramp** (readout, knob,
  fill end): 1–2 muted `#7a7870` → 3–4 neutral `#cfc9ba` → **5–6 green `#7aab6e`
  (sweet spot, shows ✦ pill)** → 7–8 amber `#c98d3a` → 9–10 red `#c0604a`. Fill is
  a gradient from `#5b594f` to the current color. Legend "🟢 5–6 adds vivid prose
  without inventing plot".

### Step 3 — Output  (`05-step3-output.png`, `06-step3-output-advanced.png`)
**Purpose:** formats, audio, destination, metadata, advanced.
- **Output formats** card (meta "at least one"): three checkboxes in a row —
  **Plain text (.txt)** (default on), **EPUB (.epub)**, **HTML (.html)**. ≥1
  required.
  - **Generate MP3 audiobook (Kokoro TTS)** checkbox below. **Disabled** (dim, with
    explanatory text) if Kokoro isn't installed **or** if .txt isn't selected
    ("Requires Plain text (.txt) to be selected."). When enabled + checked, reveals
    an **indented Voice dropdown** (`26px` left margin + `1px` left rule). The voice
    list is per-language and re-populates when the target/key-ideas language
    changes, preserving the selection when possible.
- **Output folder** card: editable path field + "Browse…". Defaults to the source
  book's folder.
- **EPUB metadata** card — **shown only when .epub is checked**. A `2×2` grid of
  labeled fields: **Title**, **Author** (both auto-filled from source), **Language**
  (default `es`), **Contributor** (translator/editor).
- **Timeout per call** + **Chunk size** cards in a `2-col` row, each a value field
  with `▴▾` stepper + a helper legend:
  - Timeout: **30–3600 s**, step 30, default **1200**, suffix " s" —
    "raise for Full translation".
  - Chunk size: **200–10000 words**, step 100, default **2000**, suffix " words" —
    "long chapters split & rejoin".
- Persistent **info note**: "ℹ️ Character names and place names are never translated
  — passed through to the model exactly as written."

### Step 4 — Run  (`07-run-idle.png`, `08-run-running.png`, `09-run-success.png`, `10-run-failed.png`)
**Purpose:** the run console — the emotional core during a multi-minute job. The
content area becomes the expanded console (this is the "run drawer takes over"
behavior).
- Header row: "RUN CONSOLE" label + a **state segmented control** (Idle · Running ·
  Success · Failed). *(That segmented control is a prototype affordance for
  reviewing states — in production the state is driven by the actual job, not a
  toggle.)*
- **Progress** row: a thin `8px` pill bar with rounded caps, fill = gradient
  `#8a6a2e → #d4a853`, `width` animates (`.4s`); a monospace `%` readout on the
  right.
- **Log**: `flex:1`, bg `#0c0c09`, `1px #2e2f2a`, radius `9px`, padding `13px 15px`,
  `12px/1.7` monospace, auto-scrolling. **Color-coded severities:** info neutral
  `#9a978c`, muted `#5b594f`, success `#7aab6e`, warning `#c98d3a`, error
  `#c0604a`, head `#cfc9ba`. Sample lines: `Chapter 3.1/4  rewriting…`,
  `✓ saved chapter 19`, `🎉 All done! Output: <path>`, `✗ Chapter 14/20 failed —
  model call timed out`, `💾 13 chapter(s) saved. Raise the timeout, then press
  Resume.`

---

## Footer / run-drawer behavior by step
The footer is always pinned. Contents change with step + run state:
- **Steps 1–3 (idle):** `[← Back]` (hidden on step 1) · a muted **"▸ run drawer ·
  idle — expands & takes over on Start"** pill in the middle · `[Next →]` (label
  names the next step) · **`[▶ Start]`** (primary, always present).
- **Step 4:** `[Clear log]` (ghost) · `[Abort]` (red, **enabled only while
  Running**) · `[⏩ Resume]` (**only when Failed**) · **`[▶ Start]`** → label
  becomes **"▶ Start over"** after success/failure, **"● Running…"** (disabled)
  while running.
- **Pressing Start** from any step jumps to step 4 and enters the Running state
  (drawer expanded).

## Interactions & Behavior
- **Stepper nav:** clicking any step badge/label (or the recap "edit") jumps there;
  Back/Next move sequentially.
- **Mode change** live-reshapes the Transform panels (animated reveal/collapse).
- **Sliders** live-update readout, color, sweet-spot pill, fill width, and knob
  position on every change; snap to ticks (10% / 1).
- **MP3 checkbox** reacts live to .txt selection and Kokoro availability; toggling
  it reveals/hides the Voice dropdown.
- **EPUB metadata** card reveals only while .epub is checked.

## State Management
State variables (see brief §5/§7 for full semantics):
- `step` (1–4), `stepsCompleted`
- `epubPath`, `bookTitle`, `bookAuthor`, `chapters[] {index, title, checked}`,
  `selectAllState` (checked|unchecked|partial)
- `model`, `cefrLevel` (default B2)
- `mode` (sr | full | sum | key; default sr)
- `keyIdeasLanguage` (es|en) — only meaningful in `key` mode; drives voice list
- **`targetIsSpanish`** (derived, see "Target language") — gates the step-2
  Spanish level dropdown and the recap level
- `crossChunkContinuity` (off | names | tail | both; default off) — always shown
- `keepPct` (10–90, default 40), `creativity` (1–10, default 5)
- `formats {txt:true, epub:false, html:false}`, `mp3Enabled`, `mp3Available`,
  `voice`, `voiceList[]` (language-dependent)
- `outputFolder`, `epubMeta {title, author, language:'es', contributor}`
- `timeoutSec` (30–3600, default 1200), `chunkWords` (200–10000, default 2000)
- `runState`: idle | running | success | failed (+ derived: empty, configured,
  validationBlocked, aborted), `progress` (0–1), `log[] {severity, text}`,
  `resumeAvailable`, `failedChapterIndex`

**App states (brief §7) — all must be expressed:** Empty/ready · Configured ·
**Validation blocked** (Start with no file / no format / no chapter → warning line
in the log, no modal; gate visibly *before* Start — disable Start + flag the
offending step) · Running (Start disabled, Abort enabled, log streaming, Resume
hidden) · Success (progress full, green 🎉 line) · **Failure with resumable
progress** (red failure line + amber 💾 "N saved… press Resume" + Resume button;
recovery = raise timeout, then Resume from failed chapter) · Aborted.

## Assets
None required. All visuals are CSS / native widgets + a few unicode/emoji glyphs
(listed under Iconography). The optional "Caveat" font is from Google Fonts and is
non-essential.

## Files
- **`README.md`** — this hi-fi implementation spec (self-sufficient).
- **`ui-design-brief.md`** — authoritative product/behavior brief. Source of truth.
- **`BookWeaver Wizard.dc.html`** — the interactive hi-fi prototype. Open in a
  browser to explore; click the step badges ① ② ③ ④ to navigate, drag the sliders,
  switch modes/formats, and use the Run-state segmented control to preview all
  states.
- **`screenshots/`** — reference renders:
  - `01-step1-book.png` — Step 1 (Book)
  - `02-step2-transform.png` — Step 2, Summarise → rewrite (both sliders)
  - `03-step2-full-translation.png` — Step 2 with depth collapsed + translate note
  - `04-step2-key-ideas.png` — Step 2 with key-ideas language toggle revealed
  - `04b-step2-cross-chunk-continuity.png` — Step 2 Spanish level dropdown + Cross-chunk continuity (always shown)
  - `05-step3-output.png` — Step 3 (Output) default
  - `06-step3-output-advanced.png` — Step 3 with MP3 enabled + Voice revealed
  - `07-step4-run-idle.png` — Run console, idle
  - `08-step4-run-running.png` — Run console, running (progress + streaming log)
  - `09-step4-run-success.png` — Run console, success
  - `10-step4-run-failed.png` — Run console, failure + Resume path
