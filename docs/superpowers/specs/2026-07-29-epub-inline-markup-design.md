# Inline markup must not shred sentences — design

**Date:** 2026-07-29
**Status:** approved

## Problem

`epub_io.extract_chapters` builds chapter text with
`soup.get_text(separator="\n")`. That inserts a newline between **every**
adjacent string node, including the ones created by inline markup. A
sentence wrapped in `<i>`, `<span>`, `<b>` or `<a>` therefore reaches the
LLM in pieces:

```
"I speak sign language, but I am not deaf," I said, and signed
I want to throw my shit at you
.
```

and emphasis words end up alone on a line:

```
all
about you. Then they had a talk with
their
```

It also splits **words**: `hyper<i>text</i>` extracts as `hyper` / `text`.

Two measured consequences:

1. **Fabricated text.** Where a sentence is severed mid-clause the model
   invents a bridge. Source *"He said if doing drugs and singing your heart
   out was wrong he didn't want to be right"* came back as
   «Él dijo algo. Dijo que las drogas y cantar eran correctos» — *"He said
   something"* appears nowhere in the source.
2. **Untranslated fragments.** An isolated line reads as a caption or block
   quote, and the model preserves it verbatim. This is the residue left
   after the glossary fix (commit `eb09e41`): 2 of the 9 English sentences
   surviving in a full-book Spanish rerun.

Scale, measured across all 23 books in `books/`: **34,002 fragment lines**.

## Scope

**In:** inline-markup flattening only.

**Out (confirmed with the user):** hard-wrapped source text, where the
*source itself* contains literal newlines mid-sentence — `The Skinner`
(9,983 fragment lines), `Designing Multi-Agent Systems`, `Multi-Agent
Development`. That is a separate cause needing a separate fix and its own
evidence; flattening inline markup does not touch it. It stays recorded in
`docs/todo.txt`.

## Design

### Block set from the HTML standard, flatten the complement

Rather than enumerate inline tags — an open-ended list that would silently
shred any tag we forgot — enumerate the closed set of **block-level**
elements and flatten everything else. Unknown and future tags then default
to inline, which is the safe direction: missing an inline tag re-introduces
the bug, whereas treating a rare tag as inline merely joins text that was
already adjacent.

`_BLOCK_ELEMENTS` = the W3Schools block-level list —
`address article aside blockquote canvas dd div dl dt fieldset figcaption
figure footer form h1-h6 header hr li main nav noscript ol p pre section
table tfoot ul video` — plus two deliberate additions:

- **`<br>`**, which that list calls inline. It is a line break the author
  intended; flattening it would run poetry and addresses together.
- **Document skeleton and table internals** — `html head body title script
  style meta link tr td th thead tbody caption col colgroup`. Unwrapping
  these would merge table cells or leak stylesheet text into prose.

### The helper

```python
def _flatten_inline(soup) -> None:
    """Unwrap inline elements, so a sentence split by markup arrives
    whole. unwrap() (not replace_with(get_text())) so a <br>/<hr>/block
    element nested inside an inline tag survives.

    get_text(separator="\n") puts its separator between adjacent string
    nodes, and unwrap leaves the hoisted strings as separate nodes —
    so smooth() must merge them or the newline survives anyway.
    """
    for tag in [t for t in soup.find_all(True)
                if t.name not in _BLOCK_ELEMENTS]:
        tag.unwrap()
    soup.smooth()
```

`smooth()` consolidates adjacent `NavigableString`s. Without it the
flattening silently does nothing — the single easiest way to get a
green-looking no-op. It is available under the project's existing floor
(`beautifulsoup4>=4.12` in `pyproject.toml` and `requirements.txt`;
4.15.0 installed), so no dependency change is needed.

### Call site

Once in `extract_chapters`, immediately after `BeautifulSoup(...)` and
before any `get_text`.

`extract_chapters` reads the soup three ways — the unmarked text that
drives `MIN_CHAPTER_CHARS` and chapter indices, `_resolve_title`, and the
`<hr>`-marked text for scene breaks. Flattening once at the top keeps all
three consistent. Flattening later, or per-read, would let them disagree
and break the index parity between `app.py`'s and `worker.py`'s extractions
that `selected_chapters` depends on.

## Measured behaviour changes

Across all 23 books:

| | today | after |
|---|---|---|
| Fragment lines | 34,002 | 17,913 |
| Chapters passing `MIN_CHAPTER_CHARS` | 559 | 558 |
| Word count (e.g. A World Without Email) | 91,319 | 89,238 |

- The **word-count drop is the fix, not loss**: words split in half by
  markup are rejoined (`hyper` + `text` → `hypertext`).
- The **one lost chapter** is a `nav.xhtml` whose text falls 209 → 190
  chars, below the 200-char threshold. It was never a real chapter.
  Accepted by the user: indices stay internally consistent because both
  frontends extract through this same function, and no chapter order or
  selection is persisted across runs.
- **Chunk counts shift in 5 of 23 books** (e.g. The Power of Mattering
  50 → 48) because rejoined text packs differently. Slightly fewer LLM
  calls; no other effect.
- **Chapter titles improve.** One book currently titles a chapter
  `"Conscious Leadership in the Workplace` — truncated where the italic
  ended. Title resolution reads the flattened soup, so it gets the whole
  phrase.

## Testing

Unit tests in `tests/test_epub_io.py`:

- a sentence split by `<i>` arrives as one line
- a *word* split by markup rejoins (`hyper<i>text</i>` → `hypertext`)
- `<p>` still separates paragraphs
- `<br>` still breaks a line
- a scene separator inside an inline tag still becomes `SCENE_BREAK`
- a heading split by inline markup yields a complete title
- nested inline tags (`<span><b>x</b></span>`) flatten once, not twice

The six existing test classes must stay green — in particular
`TestSceneBreaks::test_marking_keeps_indices_and_titles_stable`, which
pins the parity this change must not disturb.

The library-wide figures above are the measured baseline for manual
comparison; they are not an automated test, since they depend on the
user's book collection.

## Risks

- **`smooth()` omitted** → flattening silently no-ops. Covered by the
  word-rejoin test, which fails without it.
- **Nested inline tags** double-processed by `replace_with`. Covered by a
  test.
- **`<script>` / `<style>` text** is already included by `get_text` today.
  Pre-existing; explicitly out of scope.
