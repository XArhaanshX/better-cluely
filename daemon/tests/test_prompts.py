import pytest

from wispd.prompts import (ACTIONS, MODES, Line, context_block, format_transcript,
                           looks_like_question, system_prompt)


@pytest.mark.parametrize("text", [
    "Can you tell me about a time you handled conflict in a team",
    "so what is the time complexity of your solution",
    "Thanks for joining. Walk me through your resume",
    "Okay how would you design a rate limiter",
    "Why did you choose Postgres over Mongo?",
    "I'd love to hear what you think of the roadmap?",
])
def test_questions(text):
    assert looks_like_question(text)


@pytest.mark.parametrize("text", [
    "Yeah",
    "okay sounds good",
    "Let's move on to the next slide",
    "I worked at L and T on symbol detection last summer",
    "That was the last item on the agenda.",
])
def test_not_questions(text):
    assert not looks_like_question(text)


def test_transcript_format_and_order():
    lines = [Line("them", "Hi there", 3), Line("you", "Hello", 65.4)]
    assert format_transcript(lines) == "[00:03] Them: Hi there\n[01:05] You: Hello"


def test_transcript_keeps_newest_when_too_long():
    lines = [Line("them", f"line {i} " + "x" * 50, i) for i in range(100)]
    out = format_transcript(lines, max_chars=600)
    assert out.splitlines()[-1].startswith("[01:39] Them: line 99")
    assert "line 0 " not in out
    assert len(out) <= 600


def test_context_block_is_append_only():
    """Adding a line must only append to the context, so the cached prefix holds."""
    lines = [Line("them", "first", 1)]
    before = context_block("notes", lines)
    lines.append(Line("you", "second", 2))
    after = context_block("notes", lines)
    assert after.startswith(before)


def test_every_mode_has_a_prompt():
    for mode in MODES:
        assert system_prompt(mode).startswith("You are wisp")
    assert system_prompt("nope") == system_prompt("general")
    assert {"assist", "say", "followup", "recap", "factcheck"} <= set(ACTIONS)
