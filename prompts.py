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
#  PUBLIC BUILDERS
# ──────────────────────────────────────────────────────────────
def build_summary_prompt(chapter_text: str, keep_pct: int) -> str:
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
        f"CHAPTER TEXT:\n{chapter_text}\n"
    )


def build_rewrite_prompt(
    summary: str,
    level: str,
    chapter_index: int,
    creativity: int = 5,
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
        f"SOURCE SUMMARY (English):\n{summary}\n"
    )
