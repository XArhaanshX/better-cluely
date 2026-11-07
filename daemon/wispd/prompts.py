"""System prompts per mode, quick-action prompts, and transcript formatting.

The system prompt for a mode never changes during a session, so it stays
cached. The context block (notes, then transcript oldest-first) only grows,
so its earlier part stays cached too. Anything that changes per request
goes last, in the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BASE = """You are wisp, a real-time assistant shown in a small overlay at the top of the user's screen during a live conversation: a call, an interview, a meeting or a lecture. The user reads you at a glance while they keep talking or listening, so every word has to earn its place.

How to answer:
- The first line is the answer itself and must be usable on its own.
- Keep it short: one to three sentences, or at most five bullets, unless the user asks for more or the task is code.
- No preamble, no restating the question, no closing offer.
- Markdown is rendered. Use **bold** for the words the user should catch first. Put code in fenced blocks with a language tag.
- The transcript comes from live speech recognition and has mistakes. Read through them to the words that were meant.
- In the transcript, "Them" is the other side of the conversation and "You" is the user.
- A screenshot, when attached, is the user's screen at the moment they asked."""

MODES = {
    "general": ("General", "Help with whatever is happening on screen and in the conversation."),
    "interview": ("Interview", """The user is the candidate in a job interview.
- When the interviewer asks something, give the answer the user can say out loud, in first person: natural, specific, confident, with one concrete example where it helps.
- For coding or system design questions: state the approach and its time and space complexity first, then the code, then edge cases in one line.
- Behavioural questions: a tight STAR answer (situation, task, action, result) in four short lines."""),
    "meeting": ("Meeting", """The user is in a work meeting.
- Keep track of decisions, owners, deadlines and open questions.
- When asked what to say, suggest something short that moves the meeting forward."""),
    "lecture": ("Lecture", """The user is a student in a lecture or class.
- Explain concepts in plain words with one short example or analogy.
- Define jargon the first time it matters. Show formulas in LaTeX-free plain text."""),
}

ACTIONS = {
    "assist": ("Assist", """Give the most useful help for this exact moment. Decide from the end of the transcript and the screen:
- If Them just asked something, answer it (in interview mode, as the words the user should say).
- Otherwise, if the screen shows a problem, question, error or code, solve it.
- Otherwise, say the single most useful thing to say or do next."""),
    "say": ("What should I say?", "Give the exact words I should say next, ready to read out. No commentary."),
    "followup": ("Follow-up questions", "Suggest three sharp follow-up questions I could ask right now, one line each."),
    "recap": ("Recap", "Recap the conversation so far: key points, decisions, and open questions, as short bullets."),
    "factcheck": ("Fact-check", "Check the most recent factual claims made in the conversation. List any that are wrong or doubtful with a one-line correction. If they all hold up, say so in one line."),
    "explain": ("Explain", "Explain the most recent technical term, concept or reference from the conversation, briefly, with one example."),
    "notes": ("Meeting notes", """Write notes for this whole conversation, to keep and share. Ignore the usual length limit. Use exactly these sections, and leave out any that would be empty:

## Summary
Two or three sentences.

## Key points
Bullets.

## Decisions
Bullets.

## Next steps
A checklist ("- [ ] ..."), with the owner in bold when one was named.

## Follow-up email
A short email the user could send afterwards, with a subject line."""),
}

AUTO_PROMPT = """Them just asked: "{question}"
Answer it now, for the user. In interview mode, write the words the user should say."""


@dataclass
class Line:
    source: str  # "you" or "them"
    text: str
    t: float     # seconds since session start


def system_prompt(mode: str) -> str:
    _, extra = MODES.get(mode, MODES["general"])
    return f"{BASE}\n\nMode: {extra}"


def fmt_time(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def format_transcript(lines: list[Line], max_chars: int = 24_000) -> str:
    out: list[str] = []
    size = 0
    for ln in reversed(lines):
        row = f"[{fmt_time(ln.t)}] {'You' if ln.source == 'you' else 'Them'}: {ln.text}"
        size += len(row) + 1
        if size > max_chars:
            break
        out.append(row)
    return "\n".join(reversed(out))


def context_block(notes: str, lines: list[Line]) -> str:
    parts = []
    if notes.strip():
        parts.append(f"## Notes from the user\n{notes.strip()}")
    transcript = format_transcript(lines)
    parts.append("## Live transcript, oldest first\n" + (transcript or "(nothing said yet)"))
    return "\n\n".join(parts)


# Question detection works on English word order. A question puts the verb
# before the subject ("what did you...", "can you..."); a statement keeps
# the subject first even when it opens with a question word ("what we did
# was...", "when I was at Google..."). Interviewers also ask without a
# question form at all ("give me an example...", "I'm curious about..."),
# so those phrasings are listed explicitly.

_FILLERS = {"so", "and", "but", "okay", "ok", "now", "great", "alright", "right", "well",
            "um", "uh", "cool", "yeah", "perfect", "awesome", "nice", "lastly", "finally",
            "also", "then", "next"}
_WH = {"what", "why", "how", "when", "where", "who", "whom", "whose", "which",
       "what's", "how's", "where's", "who's", "why's", "when's"}
_AUX = {"can", "could", "would", "will", "should", "shall", "do", "does", "did",
        "is", "are", "was", "were", "have", "has", "had", "may", "might", "must",
        "isn't", "aren't", "don't", "doesn't", "didn't", "won't", "wouldn't",
        "couldn't", "shouldn't", "haven't", "hasn't", "wasn't", "weren't"}
# Words that can follow a fronted verb in a real question ("can YOU", "is THERE").
_SUBJECTS = {"i", "you", "we", "they", "he", "she", "it", "there", "this", "that",
             "these", "those", "the", "a", "an", "your", "my", "our", "their", "his",
             "her", "its", "anyone", "anybody", "someone", "somebody", "everyone",
             "any", "one", "y'all"}
# Subject pronouns straight after a question word mark a statement.
_PRONOUNS = {"i", "we", "they", "he", "she", "you", "it", "i'm", "we're", "they're", "you're"}
_INDIRECT = re.compile(
    r"\b("
    r"i'?d (?:like|love|want) to (?:know|hear|understand)|i would (?:like|love) to (?:know|hear)|"
    r"i'?m (?:curious|wondering)|i was wondering|i wonder (?:if|whether|how|what|why)|"
    r"tell (?:me|us) (?:about|how|why|what|more|a bit|a little)|"
    r"talk (?:me |us )?(?:about|through)|walk (?:me|us) through|"
    r"give (?:me|us) (?:an? |some )?(?:example|examples|sense|overview|rundown)|"
    r"describe (?:a|an|the|your|how|what|one)|explain (?:how|why|what|the|your|a)|"
    r"any (?:questions|thoughts|ideas|concerns|blockers)|thoughts on|"
    r"how about|what about|share (?:an?|your|some) (?:example|experience|thoughts)"
    r")\b")
_INVERTED = re.compile(r"\b(?:can|could|would|will|do|did|have|are|were|should|is)\s+(?:you|we|they)\b")


def _words(sentence: str) -> list[str]:
    return [w.strip(",;:\"'()").lower() for w in sentence.split() if w.strip(",;:\"'()")]


def looks_like_question(text: str) -> bool:
    """Cheap check for whether an utterance asks something worth answering."""
    t = text.strip()
    if len(t.split()) < 4:
        return False
    sentences = [x for x in re.split(r"(?<=[.!?])\s+", t) if x]
    # The model writes "?" when it hears one; "Can you...? Take your time."
    # still asked something.
    if any(x.rstrip().endswith("?") for x in sentences[-2:]):
        return True
    words = _words(sentences[-1])
    while words and words[0] in _FILLERS:
        words = words[1:]
    if len(words) < 2:
        return False
    line = " ".join(words)
    if _INDIRECT.search(line):
        return True
    first, second = words[0], words[1]
    if first in _WH:
        return second not in _PRONOUNS
    if first in _AUX:
        return second in _SUBJECTS
    return bool(_INVERTED.search(line))
