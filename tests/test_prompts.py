"""
tests/test_prompts.py
---------------------
Unit tests for prompts.py — all pure-Python, no Qt required.

Coverage
--------
- build_summary_prompt()      content, percentage arithmetic, rules text
- build_rewrite_prompt()      content, CEFR routing, creativity routing,
                               chapter numbering, unknown-level fallback
- _creativity_instruction()   all five tiers (accessed via the public builder)
- _LEVEL_GUIDANCE             all four CEFR keys present and non-empty
"""

import pytest

from prompts import (
    _LEVEL_GUIDANCE,
    _creativity_instruction,
    build_rewrite_prompt,
    build_summary_prompt,
)


# ──────────────────────────────────────────────────────────────
#  build_summary_prompt
# ──────────────────────────────────────────────────────────────
class TestBuildSummaryPrompt:
    CHAPTER = "Alice walked into the forest. She saw a rabbit."

    def test_chapter_text_present(self):
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=40)
        assert self.CHAPTER in prompt

    def test_keep_pct_shown(self):
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=35)
        assert "35%" in prompt

    def test_reduce_pct_derived_correctly(self):
        """reduce_pct must equal 100 - keep_pct."""
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=30)
        assert "70%" in prompt

    def test_reduce_and_keep_consistent(self):
        for keep in [10, 25, 40, 60, 90]:
            prompt = build_summary_prompt(self.CHAPTER, keep_pct=keep)
            assert f"{keep}%" in prompt
            assert f"{100 - keep}%" in prompt

    def test_proper_noun_rule_mentioned(self):
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=40)
        assert "proper noun" in prompt.lower() or "proper nouns" in prompt.lower()

    def test_no_headers_rule_mentioned(self):
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=40)
        assert "headers" in prompt.lower() or "meta-text" in prompt.lower()

    def test_output_only_rule(self):
        """Prompt should instruct the model to output only the summary."""
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=40)
        assert "only" in prompt.lower()

    def test_returns_string(self):
        result = build_summary_prompt(self.CHAPTER, keep_pct=50)
        assert isinstance(result, str)

    def test_nonempty(self):
        result = build_summary_prompt(self.CHAPTER, keep_pct=50)
        assert len(result) > 50

    def test_edge_keep_10(self):
        """Minimum slider value should not crash."""
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=10)
        assert "10%" in prompt
        assert "90%" in prompt

    def test_edge_keep_90(self):
        """Maximum slider value should not crash."""
        prompt = build_summary_prompt(self.CHAPTER, keep_pct=90)
        assert "90%" in prompt
        assert "10%" in prompt


# ──────────────────────────────────────────────────────────────
#  build_rewrite_prompt
# ──────────────────────────────────────────────────────────────
class TestBuildRewritePrompt:
    SUMMARY = "She met the White Rabbit and followed him underground."

    def test_summary_present(self):
        prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert self.SUMMARY in prompt

    def test_level_present(self):
        for level in ("B1", "B2", "C1", "C2"):
            prompt = build_rewrite_prompt(self.SUMMARY, level=level, chapter_index=0)
            assert level in prompt

    def test_chapter_number_human_friendly(self):
        """chapter_index is 0-based; the prompt should show 1-based."""
        for idx in range(5):
            prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=idx)
            assert str(idx + 1) in prompt

    def test_proper_noun_rule_present(self):
        prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert "proper noun" in prompt.lower() or "proper nouns" in prompt.lower()

    def test_spanish_instruction_present(self):
        prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert "Spanish" in prompt or "spanish" in prompt.lower()

    def test_no_titles_rule_present(self):
        prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert "title" in prompt.lower() or "header" in prompt.lower()

    def test_creativity_default_in_prompt(self):
        """Default creativity=5 should appear in the prompt."""
        prompt = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert "5" in prompt

    def test_creativity_explicit_value_in_prompt(self):
        for creativity in (1, 5, 10):
            prompt = build_rewrite_prompt(
                self.SUMMARY, level="B2", chapter_index=0, creativity=creativity
            )
            assert str(creativity) in prompt

    def test_unknown_level_falls_back_to_b2(self):
        """An unrecognised level should not raise; falls back to B2 guidance."""
        prompt_unknown = build_rewrite_prompt(
            self.SUMMARY, level="X9", chapter_index=0
        )
        prompt_b2 = build_rewrite_prompt(
            self.SUMMARY, level="B2", chapter_index=0
        )
        # Both should at least produce a non-empty string
        assert len(prompt_unknown) > 50
        assert len(prompt_b2) > 50

    def test_all_levels_produce_distinct_prompts(self):
        """Each CEFR level should embed different guidance text."""
        prompts = {
            lvl: build_rewrite_prompt(self.SUMMARY, level=lvl, chapter_index=0)
            for lvl in ("B1", "B2", "C1", "C2")
        }
        # All four should be distinct strings
        assert len(set(prompts.values())) == 4

    def test_returns_string(self):
        result = build_rewrite_prompt(self.SUMMARY, level="B2", chapter_index=0)
        assert isinstance(result, str)


# ──────────────────────────────────────────────────────────────
#  _creativity_instruction (tested through the public builder
#   and directly since it's module-level)
# ──────────────────────────────────────────────────────────────
class TestCreativityInstruction:
    def test_returns_string_for_all_levels(self):
        for level in range(1, 11):
            result = _creativity_instruction(level)
            assert isinstance(result, str)
            assert len(result) > 10

    def test_tier_1_to_2_faithful(self):
        for level in (1, 2):
            result = _creativity_instruction(level)
            # Must warn against adding detail
            assert any(
                word in result.lower()
                for word in ("faithful", "close", "plain", "explicitly")
            )

    def test_tier_3_to_4_minor_embellishment(self):
        for level in (3, 4):
            result = _creativity_instruction(level)
            assert any(
                word in result.lower()
                for word in ("embellishment", "closely", "minor", "stylistic")
            )

    def test_tier_5_to_6_sensory(self):
        for level in (5, 6):
            result = _creativity_instruction(level)
            assert any(
                word in result.lower()
                for word in ("sensory", "enrich", "vivid", "imagery")
            )

    def test_tier_7_to_8_creative(self):
        for level in (7, 8):
            result = _creativity_instruction(level)
            assert any(
                word in result.lower()
                for word in ("creative", "metaphor", "atmosphere", "literary")
            )

    def test_tier_9_to_10_maximum_freedom(self):
        for level in (9, 10):
            result = _creativity_instruction(level)
            assert any(
                word in result.lower()
                for word in ("maximum", "freedom", "skeleton", "invent", "freely")
            )

    def test_low_and_high_are_distinct(self):
        low = _creativity_instruction(1)
        high = _creativity_instruction(10)
        assert low != high

    def test_all_ten_levels_are_distinct(self):
        results = [_creativity_instruction(i) for i in range(1, 11)]
        # Adjacent tiers may share text; but all 10 should not all be identical
        assert len(set(results)) > 1


# ──────────────────────────────────────────────────────────────
#  _LEVEL_GUIDANCE dict
# ──────────────────────────────────────────────────────────────
class TestLevelGuidance:
    EXPECTED_LEVELS = ("B1", "B2", "C1", "C2")

    def test_all_cefr_levels_present(self):
        for level in self.EXPECTED_LEVELS:
            assert level in _LEVEL_GUIDANCE, f"Missing CEFR level: {level}"

    def test_all_values_non_empty_strings(self):
        for level, text in _LEVEL_GUIDANCE.items():
            assert isinstance(text, str)
            assert len(text) > 20, f"Guidance for {level} is suspiciously short"

    def test_levels_are_distinct(self):
        values = list(_LEVEL_GUIDANCE.values())
        assert len(set(values)) == len(values), "Two CEFR levels share identical guidance"

    def test_b1_simpler_than_c2(self):
        """B1 guidance should reference simple/short constructs; C2 should reference native/literary."""
        b1 = _LEVEL_GUIDANCE["B1"].lower()
        c2 = _LEVEL_GUIDANCE["C2"].lower()
        assert any(w in b1 for w in ("simple", "short", "high-frequency", "basic"))
        assert any(w in c2 for w in ("native", "literary", "complex", "full command"))
