"""
prompts.py
----------
Builds the two prompts that drive the processing pipeline:

  1. build_summary_prompt()  — asks the LLM to compress a chapter.
  2. build_rewrite_prompt()  — asks the LLM to rewrite the summary
                               in Spanish at a given CEFR level and
                               creativity setting.

Edit the string literals here to tune LLM behaviour without
touching any other part of the application.
"""


# ──────────────────────────────────────────────────────────────
#  CEFR LEVEL GUIDANCE
# ──────────────────────────────────────────────────────────────
_LEVEL_GUIDANCE: dict[str, str] = {
    "B1": (
        "Use short, simple sentences. Stick to the present and past tenses "
        "(preterite). Avoid idiomatic expressions and complex subordinate "
        "clauses. Vocabulary should be high-frequency and accessible."
    ),
    "B2": (
        "Use varied sentence structures including subordinate clauses. Mix "
        "present, past (preterite and imperfect), and future tenses naturally. "
        "Include some common idiomatic expressions. Vocabulary can be broader "
        "but avoid rare or literary terms."
    ),
    "C1": (
        "Write natural, fluid Spanish prose with full command of tenses "
        "including subjunctive. Use idiomatic expressions and figurative "
        "language where appropriate. Vary sentence length and rhythm for "
        "literary effect."
    ),
    "C2": (
        "Write at native literary level. Full command of all tenses, including "
        "complex subjunctive and conditional constructions. Rich vocabulary "
        "including stylistic register variation, rhythm, and literary devices."
    ),
}


# ──────────────────────────────────────────────────────────────
#  CREATIVITY GUIDANCE  (maps 1–10 to prose instructions)
# ──────────────────────────────────────────────────────────────
def _creativity_instruction(level: int) -> str:
    if level <= 2:
        return (
            "Stay extremely close to the source. Do not add any detail, "
            "metaphor, or imagery that is not explicitly present in the "
            "summary. Render it faithfully and plainly."
        )
    if level <= 4:
        return (
            "Follow the source closely but allow very minor stylistic "
            "embellishments — a descriptive adjective here, a sense of "
            "atmosphere there. No invented plot details."
        )
    if level <= 6:
        return (
            "You may enrich the prose with sensory details, emotional "
            "texture, and vivid imagery that feel consistent with the scene. "
            "Add colour and life without inventing new events."
        )
    if level <= 8:
        return (
            "Be a creative author. Add atmospheric descriptions, internal "
            "character thoughts, metaphors, and literary rhythm. You may "
            "elaborate scenes beyond what the summary states, as long as it "
            "serves the story."
        )
    return (
        "Write with maximum creative freedom. Use the summary as a loose "
        "skeleton — invent sensory details, inner monologue, dialogue beats, "
        "and poetic imagery liberally. Make it feel like a richly written "
        "novel chapter."
    )


# ──────────────────────────────────────────────────────────────
#  CONTINUITY CONTEXT
# ──────────────────────────────────────────────────────────────
def build_context_block(names: list[str] | None, prior_prose: str) -> str:
    """Assemble a delimited continuity-context block from a proper-noun
    protection list and/or the tail of the previous chunk's output. Returns
    "" when both are empty. The block is read-only context — the builders
    that embed it keep the operative 'output only the new text' rule last."""
    names = names or []
    prior_prose = (prior_prose or "").strip()
    if not names and not prior_prose:
        return ""
    parts = [
        "CONTINUITY CONTEXT (read for consistency only — do NOT translate, "
        "repeat, summarise, or output this block):"
    ]
    if names:
        parts.append(
            "- Keep these names exactly as written: " + ", ".join(names) + "."
        )
    if prior_prose:
        parts.append(
            "- The preceding passage ended like this (continue smoothly, do "
            f"not repeat it): \"{prior_prose}\""
        )
    return "\n".join(parts) + "\n\n"


# ──────────────────────────────────────────────────────────────
#  PUBLIC BUILDERS
# ──────────────────────────────────────────────────────────────
def build_summary_prompt(
    chapter_text: str,
    keep_pct: int,
    context_block: str = "",
) -> str:
    """
    Return a prompt that asks the LLM to condense *chapter_text*,
    retaining approximately *keep_pct* percent of the original length.
    """
    word_count = len(chapter_text.split())
    target_words = round(word_count * keep_pct / 100)
    return (
        "You are a precise literary editor. "
        "Your task is to condense the following book chapter to a specific length.\n\n"
        "LENGTH REQUIREMENT (most important rule):\n"
        f"- The original text is approximately {word_count} words.\n"
        f"- Your output MUST be approximately {target_words} words "
        f"({keep_pct}% of the original).\n"
        f"- Do NOT produce a short summary. At {keep_pct}% you should retain "
        "most of the original prose, scenes, and detail.\n\n"
        "CONTENT RULES:\n"
        "- Preserve all plot events, character motivations, emotional beats, "
        "and narrative tension.\n"
        "- Keep all proper nouns exactly as written: character names, place "
        "names, and organisation names must NOT be translated or altered.\n"
        "- Write in clear, neutral English prose.\n"
        "- Do NOT add commentary, headers, or meta-text. "
        "Output only the condensed text.\n\n"
        f"{context_block}"
        f"CHAPTER TEXT:\n{chapter_text}\n"
    )


def build_translation_prompt(
    chunk_text: str,
    level: str,
    chapter_index: int,
    creativity: int = 5,
    context_block: str = "",
) -> str:
    """
    Return a prompt that asks the LLM to translate *chunk_text* directly
    into Spanish at CEFR *level* with the given *creativity* (1–10).
    No summarisation — the full source text is preserved.
    """
    guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["B2"])
    creativity_text = _creativity_instruction(creativity)

    return (
        "You are a skilled literary translator. Translate the following English "
        "book chapter text into natural, fluent Spanish, preserving the full "
        "content, structure, and meaning of the original.\n\n"
        f"TARGET LEVEL: CEFR {level}\n"
        f"LANGUAGE GUIDANCE: {guidance}\n\n"
        f"CREATIVITY LEVEL: {creativity}/10\n"
        f"CREATIVITY GUIDANCE: {creativity_text}\n\n"
        "STRICT RULES:\n"
        "- Translate the COMPLETE text — do not shorten, summarise, or omit anything.\n"
        "- Write entirely in Spanish.\n"
        "- Do NOT translate proper nouns: keep all character names, place "
        "names, and organisation names exactly as they appear in the source.\n"
        "- Do NOT add titles, headers, or meta-commentary. "
        "Output only the translated text.\n"
        "- Match the paragraph and sentence structure of the original as closely as possible.\n"
        f"- Do NOT use vocabulary, grammar, or constructions beyond CEFR {level} — "
        "stay within the target level throughout.\n"
        f"- This is chapter {chapter_index + 1}.\n\n"
        f"REMINDER — you are writing for a CEFR {level} reader. Apply the language guidance strictly.\n\n"
        f"{context_block}"
        f"SOURCE TEXT (English):\n{chunk_text}\n"
    )


def build_rewrite_prompt(
    summary: str,
    level: str,
    chapter_index: int,
    creativity: int = 5,
    context_block: str = "",
) -> str:
    """
    Return a prompt that asks the LLM to rewrite *summary* as a Spanish
    narrative chapter at CEFR *level* with the given *creativity* (1–10).
    """
    guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["B2"])
    creativity_text = _creativity_instruction(creativity)

    return (
        "You are a skilled Spanish author. Rewrite the following English "
        "chapter summary as a vivid, engaging Spanish narrative chapter.\n\n"
        f"TARGET LEVEL: CEFR {level}\n"
        f"LANGUAGE GUIDANCE: {guidance}\n\n"
        f"CREATIVITY LEVEL: {creativity}/10\n"
        f"CREATIVITY GUIDANCE: {creativity_text}\n\n"
        "STRICT RULES:\n"
        "- Write entirely in Spanish.\n"
        "- Do NOT translate proper nouns: keep all character names, place "
        "names, and organisation names exactly as they appear in the source.\n"
        "- Do NOT add titles, headers, or meta-commentary. "
        "Output only the narrative text.\n"
        "- Make it feel like a real book chapter, not a summary.\n"
        f"- This is chapter {chapter_index + 1}.\n\n"
        f"{context_block}"
        f"SOURCE SUMMARY (English):\n{summary}\n"
    )


# ──────────────────────────────────────────────────────────────
#  KEY-IDEAS HEADERS  (single source of truth — used by the prompt
#  builders for instruction text and by the worker for rendering
#  and extraction)
# ──────────────────────────────────────────────────────────────
KEY_IDEAS_HEADER: dict[str, str] = {"en": "Key ideas", "es": "Ideas clave"}
BOOK_KEY_IDEAS_HEADER: dict[str, str] = {
    "en": "Key ideas of the book",
    "es": "Ideas clave del libro",
}


def _key_ideas_lang_line(lang: str, level: str) -> str:
    """Shared language directive for the key-idea builders."""
    if lang == "es":
        guidance = _LEVEL_GUIDANCE.get(level, _LEVEL_GUIDANCE["B2"])
        return (
            f"Write entirely in Spanish at CEFR {level}.\n"
            f"LANGUAGE GUIDANCE: {guidance}"
        )
    return "Write entirely in English."


def build_key_ideas_prompt(
    summary_text: str,
    lang: str,
    level: str = "B2",
) -> str:
    """
    Return a prompt asking the LLM to extract 1–5 key ideas from
    *summary_text*, each a bullet plus a ≤2-sentence explanation, written
    in *lang* (`"en"` or `"es"` at CEFR *level*). Output begins with the
    localized chapter header so the worker can render and later locate it.
    """
    header = KEY_IDEAS_HEADER.get(lang, KEY_IDEAS_HEADER["en"])
    return (
        "You are a precise literary analyst. Identify the key ideas or key "
        "moments of the following chapter summary.\n\n"
        "RULES:\n"
        "- Identify AT LEAST ONE and AT MOST FIVE key ideas. Only include an "
        "idea if it is genuinely important; never pad to reach five.\n"
        f"- Begin your output with this exact header line on its own: {header}\n"
        "- Then list each idea as a bullet starting with '- '. After the idea "
        "statement, add a short explanation of NO MORE THAN 2 sentences.\n"
        f"- {_key_ideas_lang_line(lang, level)}\n"
        "- Do NOT translate proper nouns: keep character, place, and "
        "organisation names exactly as written.\n"
        "- Output ONLY the header and the bullet list — no other commentary.\n\n"
        f"CHAPTER SUMMARY:\n{summary_text}\n"
    )


def build_book_key_ideas_prompt(
    chapter_ideas_text: str,
    lang: str,
    level: str = "B2",
) -> str:
    """
    Return a prompt that synthesises the most important book-wide ideas
    (5–7) from *chapter_ideas_text* (the concatenated per-chapter key-idea
    sections). Each idea is a bullet plus a ≤2-sentence explanation, in
    *lang*. The book header is NOT emitted here — the worker applies it as
    the result entry's title.
    """
    return (
        "You are a precise literary analyst. Below are the key ideas collected "
        "from every chapter of a book. Synthesise the MOST IMPORTANT ideas "
        "across the whole book.\n\n"
        "RULES:\n"
        "- Identify between 5 and 7 of the most important, book-wide ideas. "
        "Merge related chapter ideas; do not simply repeat them verbatim.\n"
        "- List each idea as a bullet starting with '- '. After the idea "
        "statement, add a short explanation of NO MORE THAN 2 sentences.\n"
        f"- {_key_ideas_lang_line(lang, level)}\n"
        "- Do NOT translate proper nouns.\n"
        "- Output ONLY the bullet list — no header line, no other commentary.\n\n"
        f"PER-CHAPTER KEY IDEAS:\n{chapter_ideas_text}\n"
    )
