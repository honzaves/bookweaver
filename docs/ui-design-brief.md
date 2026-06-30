# BookWeaver — UI Design Brief

A complete, design-tool-ready description of the application: what it does, who
uses it, every feature and control, every state, and the current visual
identity. Use this to generate a new UI design. Nothing here is Qt-specific —
it describes behavior and intent, not implementation.

---

## 1. What the product is

**BookWeaver** is a **desktop app** that turns an English EPUB e-book into a
Spanish-language (or condensed English) version using a **local AI model**
(Ollama, running on the user's own machine — nothing is sent to the cloud). It
can also generate an **MP3 audiobook** of the result.

The user picks a book, chooses how it should be transformed (translate,
summarize, rewrite at a chosen Spanish proficiency level, or extract key
ideas), presses Start, and watches a live log as each chapter is processed.
Output is written to disk as text, EPUB, HTML, and/or MP3.

**One-line positioning:** *Weave an English book into the Spanish you can
actually read — privately, on your own machine.*

---

## 2. Who uses it and why

- **Primary user:** a Spanish learner (or a fluent reader who wants graded
  material) who wants to read real books at their level — from B1 (beginner-
  intermediate) up to C2 (mastery).
- **Secondary user:** someone who wants fast English summaries or key-idea
  digests of long books.
- **Context:** runs locally, often offline. The user is privacy-conscious and
  patient — processing a book takes minutes and is compute-heavy. They value
  control over the output (length, difficulty, creativity) and clear feedback
  on long-running jobs.
- **Skill level:** comfortable with a settings-heavy tool, but the defaults
  should make a good first run possible without touching most controls.

---

## 3. Core mental model

The screen is essentially **one configuration form + a run console**. The user
moves top-to-bottom configuring a job, then acts on it via a footer of
buttons, watching a progress bar and a color-coded log. Many controls
**reveal/hide or re-populate** depending on the chosen processing mode and
output formats — the form is adaptive, not static.

---

## 4. Primary flow (happy path)

1. **Select an EPUB.** On selection, the app reads the book's metadata
   (title, author) and its chapter list, and pre-fills the output folder to
   the book's folder.
2. **Pick which chapters** to process (all are checked by default).
3. **Choose a model and a Spanish CEFR level.**
4. **Choose a processing mode** (this reshapes the controls below it).
5. **Tune length and creativity** with two sliders.
6. **Choose output formats** (text / EPUB / HTML), optionally an **MP3
   audiobook** with a chosen voice, and an output folder.
7. **Press Start.** The progress bar fills; the log streams per-chapter
   status. On success, a "🎉 All done" line names the output path.
8. **On failure,** completed chapters are saved and a **Resume** button
   appears — the user can raise the timeout and continue from the failed
   chapter.

---

## 5. Complete feature & control inventory

Organized by the current on-screen sections. Each control lists: type, range/
options, default, and any conditional behavior. **A redesign may regroup or
restyle these, but every capability must remain reachable.**

### Header
- App title "BookWeaver" + subtitle "EPUB → Spanish rewriter via Ollama".

### Source
- **EPUB file picker** — read-only path field + "Browse…" button (filters to
  `.epub`). Selecting a file triggers metadata + chapter extraction.

### Chapters
- **Chapter checklist** — a scrollable list of every chapter, each a checkbox
  labeled `01. <Chapter title>` (zero-padded number + title). All start
  checked.
- **"Select all" master checkbox** — tri-state: checked (all), unchecked
  (none), or partially-checked (some). Clicking it sets all children; child
  changes update its state. At least one chapter must be selected to start.
- Empty until a book is loaded.

### Model & Target Language
- **Ollama model dropdown** — list comes from config (e.g. "Gemma 4 31B
  (recommended)"). Has a configurable default.
- **Spanish CEFR level dropdown** — four options: `B1 — Threshold`,
  `B2 — Vantage`, `C1 — Advanced`, `C2 — Mastery`. Default **B2**. This is the
  difficulty/register the Spanish output is written at (acts as a ceiling: it
  simplifies harder text down to the level; it does not inflate easy text up).

### Processing mode (the key adaptive control)
Four mutually exclusive options:
1. **Summarise → Rewrite in Spanish** (default) — condense each chapter, then
   rewrite it as Spanish narrative at the chosen level.
2. **Full translation (no summarisation)** — translate the complete chapter
   text directly to Spanish; nothing is cut. (Slower, longer model calls.)
3. **Summarise only (English, no translation)** — condense to target length,
   save as English.
4. **Summary with key ideas** — condense each chapter, then append 1–5 "key
   ideas" (bullet + ≤2-sentence explanation); after the book, a book-wide "Key
   ideas of the book" synthesis. Output language is chosen per run.

**Conditional reveals driven by mode:**
- A **"Summarisation depth" panel** (the keep-% slider + explainer) is shown
  for every mode **except Full translation**.
- A **translate-mode note** ("full text translated… expect longer calls")
  shows only in Full translation.
- A **summarise-only note** shows only in Summarise only.
- A **"Key-ideas output language" toggle** (Spanish at CEFR level / English)
  shows only in Summary-with-key-ideas. It also re-populates the MP3 voice
  list to match the language.

### Summarisation depth (conditional — see above)
- **Keep-% slider** — range **10–90%**, default **40%**, ticks every 10%.
- Live readout: `Keep 40% of original (↓ 60% reduction)`.
- **Sweet spot 30–50%** — inside this range the readout turns green and shows a
  "✦ sweet spot" tag; a legend reads "🟢 Sweet spot: 30–50% keeps core story
  without noise".

### Creativity — "how freely may the LLM elaborate?"
- **Creativity slider** — range **1–10**, default **5**, ticks every 1.
- Each notch has a named label and color: 1 Verbatim, 2 Faithful, 3 Faithful+,
  4 Enriched, 5 Enriched+, 6 Vivid, 7 Expressive, 8 Inventive, 9 Free,
  10 Unbound. Labels shift from muted → neutral → green (sweet spot) → amber →
  warning → red as creativity rises.
- Live readout: `Enriched+ — level 5/10 (temperature ≈ 0.x) ✦ sweet spot`.
  It exposes the underlying model **temperature**.
- **Sweet spot 5–6**; legend: "🟢 Sweet spot: 5–6 adds vivid prose without
  inventing plot events".

### Options
- **Output format checkboxes** (select one or more, ≥1 required): **Plain text
  (.txt)** [default on], **EPUB (.epub)**, **HTML (.html)**.
- **Generate MP3 audiobook (Kokoro TTS)** checkbox:
  - **Disabled** with an explanatory tooltip if Kokoro isn't installed, or if
    Plain text isn't selected (MP3 requires the .txt output).
  - When enabled and checked, reveals a **Voice dropdown** (indented). The
    voice list is per-language and re-populates when the target language
    changes (Spanish voices vs. English voices), preserving the selection when
    possible.
- **Output folder** — editable path + "Browse…". Defaults to the source book's
  folder.
- **EPUB metadata sub-panel** — shown only when EPUB output is checked. Four
  labeled fields: **Title**, **Author**, **Language** (default `es`),
  **Contributor** (translator/editor). Title and Author are auto-filled from
  the source book.
- **Timeout per call** — numeric stepper, **30–3600 s**, step 30, default 1200,
  suffix " s". (Full translation may need a higher value.)
- **Chunk size** — numeric stepper, **200–10000 words**, step 100, default
  2000, suffix " words". Chapters longer than this are split at paragraph
  boundaries, processed independently, and rejoined.

### Persistent info note
- A standing note: "ℹ️ Character names and place names are never translated —
  passed through to the model exactly as written."

### Action footer (always visible, below the scrolling form)
- **Progress bar** — thin, fills as chapters complete.
- **Log console** — read-only, color-coded, auto-scrolling; streams status
  lines like `Chapter 3.1/4`, save confirmations, and final result path.
- **Buttons:** **Clear log** (left); right-aligned **Abort** (red, enabled only
  while running), **Resume** (hidden unless a run failed with partial
  results), **Start** (primary).

---

## 6. Speech sanitization (behavioral note, no UI)
When generating MP3, the spoken text is auto-cleaned (footnote markers,
emphasis asterisks, list bullets removed; scene breaks become short silences)
so the audio sounds natural. The written text/EPUB/HTML output keeps its
original markup. **This is invisible to the user** — list it only so the design
doesn't invent a control for it.

---

## 7. Application states the UI must express

1. **Empty / ready** — no book loaded; chapter list empty; log shows "Ready.
   Configure settings above and press Start."
2. **Configured** — book loaded, metadata + chapters populated.
3. **Validation blocked** — Start pressed with no file / no format / no chapter
   selected → a warning line in the log (no modal). Design should make these
   requirements obvious *before* Start.
4. **Running** — Start disabled, Abort enabled, progress filling, log
   streaming; Resume hidden.
5. **Success** — progress full; green "🎉 All done! Output: <path>" line.
6. **Failure with resumable progress** — red failure line, plus a "💾 N
   chapter(s) saved… press Resume" warning; Resume button appears. Raising the
   timeout before resuming is the intended recovery.
7. **Aborted** — user-initiated stop.

Log severity levels and their meaning: **info** (neutral), **success**
(green), **warning** (amber), **error** (red), **muted** (secondary/gray).

---

## 8. Current visual identity (preserve the spirit; modernize freely)

- **Mood:** dark, warm, focused, "crafted." A literary/workshop feel — the
  amber accent over near-black evokes lamplight and old paper.
- **Palette (hex):**
  - Background `#111210`, Surface `#1c1d1b`, Surface-2 `#252620`,
    Border `#2e2f2a`
  - **Amber accent** `#d4a853` (primary brand color), dim amber `#8a6a2e`
  - Text `#e8e4d9`, Muted `#7a7870`
  - Success/sweet green `#7aab6e`, Warning `#c98d3a`, Error `#c0604a`
- **Type:** UI in Helvetica Neue / system sans, ~13px base; the log console in
  a monospace face (SF Mono / Menlo). Title is heavy-weight, tight letter-
  spacing, amber.
- **Shapes:** rounded corners (cards/group boxes ~8px, inputs ~6px). Group
  boxes are titled cards with uppercase, letter-spaced, muted titles. A thin
  amber rule sits under the header. The progress bar is a thin pill with
  rounded caps. Primary button is amber-filled; danger button is red-tinted.
- **Iconography:** sparing emoji as accents (▶ Start, ⏩ Resume, 🟢 sweet spot,
  ℹ️ note, 🎉 done, 💾 saved).

---

## 9. Layout structure (current)

- Fixed window, min ~700×820, default ~760×900 (single column).
- **Header** (title + subtitle) → **amber rule** → **scrollable config area**
  (all the grouped sections) → **fixed footer** (progress bar, log console,
  button row). The footer never scrolls away.

---

## 10. Design goals for the redesign

What a strong new design should achieve (priorities, not prescriptions):

1. **Tame the density.** The form is long and adaptive; help the user see
   "what do I minimally need to set" vs. "advanced tuning." Consider
   progressive disclosure, a stepper/wizard, or a two-pane (configure | run)
   layout. Defaults already allow a one-glance first run — surface that.
2. **Make the adaptive logic legible.** Mode selection reshapes the form;
   make cause-and-effect obvious so controls don't appear/vanish jarringly.
3. **Elevate the run experience.** Long jobs need confident progress: per-
   chapter status, time/▮ remaining feel, clear success/failure, and an
   obvious, reassuring Resume path. The log is the emotional core during a run.
4. **Keep the two sliders delightful.** The keep-% and creativity sliders with
   their live readouts, named notches, and "sweet spot" guidance are a
   signature interaction — preserve that helpfulness.
5. **Respect the local-first, private, crafted identity.** Warm dark theme,
   amber accent, literary tone. Avoid a generic SaaS look.
6. **Validation up front.** Required inputs (file, ≥1 format, ≥1 chapter)
   should be visibly gated rather than failing only after Start.

### Hard constraints (do not drop)
- Every control in §5 must remain reachable.
- The mode-driven conditional reveals (§5) and the MP3 enable/voice-language
  rules must be honored.
- It is a **desktop** app (offline-capable, file-system access, local model) —
  not a web service. Mockups can be presented in a browser, but the design
  language should read as a focused desktop tool.

---

## 11. One-paragraph summary (for a quick design prompt)

> Design the UI for **BookWeaver**, a private, local desktop app that
> transforms English EPUBs into graded Spanish (or condensed English) using a
> local AI model, with optional MP3 audiobook output. The user loads a book,
> selects chapters, picks a model and a Spanish CEFR level (B1–C2), chooses one
> of four processing modes (summarise→rewrite, full translation, summarise-
> only, or summary-with-key-ideas), tunes two expressive sliders (how much to
> keep, 10–90%; and creativity, 1–10, with named notches and "sweet spot"
> guidance), selects output formats (txt/epub/html + optional voiced MP3), then
> runs a multi-minute job watched via a thin progress bar and a color-coded,
> auto-scrolling log. Failed runs save partial progress and offer Resume. The
> aesthetic is warm dark with an amber accent over near-black — literary,
> crafted, focused — not generic SaaS. Reduce density and clarify the mode-
> driven adaptive controls without removing any capability.
