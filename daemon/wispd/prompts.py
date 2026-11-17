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
- The transcript comes from live speech recognition and has mistakes. Read through them to the words that were meant. It may be in English, Hindi (Devanagari) or a mix of both.
- Casual Hindi and Hinglish is full of fillers and address words: अरे, अबे, यार, भाई, मतलब, अच्छा, "क्या बोलते हैं", "क्या है कि", and a final "ना" that can be a tag question ("आएगा ना?"), a plea ("बोल ना") or plain emphasis ("नहीं ना"). Read past them to what is meant. Reactions such as "क्या यार", "और क्या" or "क्यों नहीं" are not questions.
- English words spoken inside Hindi are often written in Devanagari by the speech recognizer (कैशिंग is caching, डेटाबेस is database).
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


# How answers should be written. "auto" follows the conversation.
ANSWER_LANGUAGES = {
    "auto": ("Auto", "If the conversation is in English, answer in English. If it is in Hindi or Hinglish (Devanagari in the transcript), answer in Hinglish written in Latin script, the way people text it (e.g. \"Haan, isliye maine messages pehle database mein store kiye\"), with technical terms in English spelling. Do not answer in Devanagari unless the user types to you in Devanagari. Match how casual the conversation is, but never use rude address words such as abe or abbe, and keep interview answers professional."),
    "en": ("English", "Always answer in English, even when the conversation is in Hindi."),
    "hi": ("Hindi", "Always answer in Hindi, written in Devanagari. Keep technical terms, code and names in English."),
    "hinglish": ("Hinglish", "Always answer in Hinglish: natural Hindi-English mix written in Latin script, the way it is actually spoken (e.g. \"Maine is project mein caching use ki thi\"). Casual where the conversation is casual (yaar, matlab, na are fine), never rude (no abe or abbe), and professional in interview answers. Keep code in English."),
}


def system_prompt(mode: str, answer_language: str = "auto") -> str:
    _, extra = MODES.get(mode, MODES["general"])
    _, lang = ANSWER_LANGUAGES.get(answer_language, ANSWER_LANGUAGES["auto"])
    return f"{BASE}\n\nLanguage: {lang}\n\nMode: {extra}"


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


# Hindi has separate word families for questions (क-: क्या, कैसे, कब,
# कहाँ, कौन...) and for relative clauses (ज-: जब, जो, जहाँ...), so "जब मैं
# गूगल में था" ("when I was at Google") is never mistaken for a question,
# and a question word anywhere in the sentence counts: Hindi does not move
# it to the front ("आपने यह कैसे बनाया"). Romanized Hinglish is matched too.
#
# Casual Hinglish needs more than that. It is full of fillers and address
# words (अरे, अबे, यार, भाई, मतलब, "क्या बोलते हैं", "क्या है कि") and of
# reactions built from question words ("क्या यार", "और क्या", "क्यों
# नहीं"), and the sentence-final "ना" can be a tag question ("आएगा ना?"),
# a plea ("चल ना", "बोल ना") or emphasis ("नहीं ना"). Fillers are removed,
# reactions are removed and the rest is judged, and "ना" counts only after
# a finished verb.
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HI_WH = {
    "क्या", "क्यों", "क्यूँ", "क्यूं", "कैसे", "कैसा", "कैसी", "कब", "कहाँ", "कहां", "किधर",
    "कौन", "कौनसा", "कौनसी", "कौनसे", "कितना", "कितने", "कितनी", "किस", "किसने",
    "किसको", "किसका", "किसकी", "किसके", "किसे", "किन", "किन्हें",
    "kya", "kyu", "kyun", "kyon", "kaise", "kaisa", "kaisi", "kab", "kahan", "kahaan", "kidhar",
    "kaun", "kaunsa", "kaunsi", "kitna", "kitne", "kitni", "kis", "kisne", "kisko", "kiska",
}
# Polite or casual requests that ask for an answer without a question word.
_HI_ASK = {
    "बताइए", "बताइये", "बताएं", "बताएँ", "बतायें", "बताओ", "बताना", "बतायेंगे", "बताएंगे",
    "समझाइए", "समझाइये", "समझाओ", "समझाएं", "समझाएँ",
    "bataiye", "bataye", "batayein", "batao", "batana", "samjhaiye", "samjhao",
}
# Also requests, but only as the last word ("बता", "बोलो"); mid-sentence
# they are ordinary verbs ("मैंने बता दिया").
_HI_ASK_LAST = {"बता", "बोलो", "बोल", "समझा", "bata", "bolo", "bol", "samjha"}
# Fillers and address words, dropped from both ends of the sentence.
_HI_FILLERS = {
    "अरे", "अरेरे", "अबे", "ओए", "ओये", "यार", "भाई", "भैया", "बॉस", "अच्छा", "हाँ", "हां",
    "हम्म", "मतलब", "चल", "चलो", "सुनो", "सुन", "देखो", "देख", "बस", "वैसे", "तो", "जी",
    "ना", "न", "रे", "ओके", "बेसिकली", "एक्चुअली",
    "arre", "arey", "arrey", "abbe", "abe", "abey", "oye", "oy", "yaar", "yar", "bhai",
    "bhaiya", "bro", "boss", "accha", "acha", "achha", "achcha", "haan", "han", "hmm",
    "matlab", "chal", "chalo", "suno", "dekho", "dekh", "bas", "waise", "vaise", "toh",
    "ji", "na", "re", "basically", "actually",
}
# Filler phrases removed wherever they occur ("वो क्या बोलते हैं उसको...").
_HI_FILLER_PHRASES = re.compile(
    r"(क्या बोलते हैं|क्या कहते हैं|क्या बोलते|क्या कहते|क्या है कि|जो है ना|"
    r"kya bolte hain|kya kehte hain|kya bolte|kya kehte|kya hai ki|jo hai na)")
# Reactions built from question words: removed, then the rest is judged
# ("क्या यार तू कब आएगा" still asks when).
_HI_REACTIONS = re.compile(
    r"(क्या यार|क्या बात है|क्या बकवास|क्या मज़ाक|क्या मजाक|और क्या|क्या ही|क्यों नहीं|"
    r"कैसे नहीं|कैसे भी|क्यों कि|"
    r"kya yaar|kya yar|kya baat hai|kya bakwas|kya mazaak|aur kya|kya hi|kyun nahi|kyu nahi|"
    r"kyon nahi|kaise nahi|kaise bhi|kyun ki)")
# The question word sits inside a statement ("पता नहीं क्या हुआ", "पता है
# क्या हुआ..." is a story opener): the whole sentence is a statement.
_HI_EMBEDDED = re.compile(
    r"(पता नहीं|नहीं पता|मालूम नहीं|नहीं मालूम|क्या पता|पता है क्या|कब से नहीं|"
    r"pata nahi|pata nahin|nahi pata|kya pata|pata hai kya)")
# A finished verb or auxiliary before a final "ना" makes it a tag question.
_HI_AUX = {"है", "हैं", "था", "थी", "थे", "हो", "होगा", "होगी", "होंगे",
           "hai", "hain", "tha", "thi", "the", "ho", "hoga", "hogi", "honge"}
_HI_TAG_ENDINGS_DEV = ("गा", "गी", "गे", "या", "यी", "ये", "ई", "ए")
_HI_TAG_ENDINGS_LAT = ("ga", "gi", "ge", "ya", "yi", "ye")
# Distinctive Hinglish words; one is enough to read romanized text as Hindi.
_HINGLISH = _HI_WH | _HI_ASK | (_HI_FILLERS - {"na", "re", "ji", "bro", "boss", "basically",
                                               "actually", "toh", "bas", "dekh", "han", "hmm"}) | {
    "hai", "hain", "tha", "thi", "nahi", "nahin", "mujhe", "aap", "aapne", "tum", "tumne",
    "tune", "humne", "kuch", "bhi", "kiya", "raha", "rahe", "rahi", "sakte", "karoge",
    "karenge", "karega", "karte", "karna", "mein", "bata", "bolo"}


def _hi_words(sentence: str) -> list[str]:
    out = []
    for w in sentence.split():
        w = w.strip(",;:\"'()।.!").lower()
        if not w:
            continue
        if not _DEVANAGARI.search(w):
            w = re.sub(r"(.)\1{2,}", r"\1", w)  # "kyaaa" -> "kya", "arreee" -> "are"... keep doubles
        out.append(w)
    return out


def _looks_like_hindi_question(sentence: str) -> bool:
    line = " ".join(_hi_words(sentence))
    if _HI_EMBEDDED.search(line):
        return False
    line = _HI_FILLER_PHRASES.sub(" ", line)
    line = _HI_REACTIONS.sub(" ", line)
    words = line.split()

    # Final "ना": a tag question only after a finished verb ("आएगा ना",
    # "है ना", "kiya na"); after "नहीं" it is emphasis, after a bare verb
    # stem ("चल ना", "बोल ना") it is a plea.
    tag = False
    if len(words) >= 2 and words[-1] in ("ना", "न", "na"):
        prev = words[-2]
        if prev not in ("नहीं", "nahi", "nahin"):
            tag = (prev in _HI_AUX or prev.endswith(_HI_TAG_ENDINGS_DEV)
                   or prev.endswith(_HI_TAG_ENDINGS_LAT))

    while words and words[0] in _HI_FILLERS:
        words = words[1:]
    while words and words[-1] in _HI_FILLERS:
        words = words[:-1]
    if not words:
        return False
    if tag and len(words) >= 2:
        return True
    if words[-1] in _HI_ASK_LAST or any(w in _HI_ASK for w in words):
        return True
    return len(words) >= 2 and any(w in _HI_WH for w in words)


# Romanized Hindi verb forms: future (aayega, karoge), polite imperative
# (bataiye), progressive and perfect (raha, kiya) endings.
_HI_VERB_FORM = re.compile(r"^[a-z]{2,}(ega|egi|enge|oge|ogi|unga|ungi|iye|aiye|rahe|raha|rahi)$")


# English words that also end like Hindi verbs ("challenge", "omega") only
# count as Hindi when the sentence doesn't read as English.
_EN_STOP = {"the", "a", "an", "is", "are", "was", "were", "you", "me", "about", "what", "how",
            "why", "when", "where", "do", "did", "can", "could", "would", "to", "of", "in", "on",
            "for", "with", "that", "this", "it", "i", "we", "they", "your", "my", "have", "has"}


def _is_hindi(text: str) -> bool:
    if _DEVANAGARI.search(text):
        return True
    words = set(_hi_words(text))
    if words & _HINGLISH:
        return True
    return any(_HI_VERB_FORM.match(w) for w in words) and len(words & _EN_STOP) < 2


def looks_like_question(text: str) -> bool:
    """Cheap check for whether an utterance asks something worth answering."""
    t = text.strip()
    if _is_hindi(t):
        if t.rstrip("। ").endswith("?"):
            return len(t.split()) >= 2
        # Hindi sentences end with "।" (danda) as well as "."
        last = [x for x in re.split(r"(?<=[.!?।])\s+", t) if x][-1]
        return _looks_like_hindi_question(last)
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


# The system prompt states the language rule, but a transcript full of
# Devanagari outweighs it, so the language is also decided here and
# restated at the end of each request, where it carries the most weight.
_REMINDERS = {
    "en": "Write the answer in English.",
    "hi": "Write the answer in Hindi in Devanagari script; keep technical terms, names and code in English.",
    "hinglish": "Write the answer in Hinglish using only Latin (English) letters, no Devanagari, the way people text it.",
}


def answer_language(setting: str, lines: list[Line], typed: str | None = None) -> str:
    """The language this answer should be written in: en, hi or hinglish."""
    if setting in _REMINDERS:
        return setting
    if typed:
        if _DEVANAGARI.search(typed):
            return "hi"
        return "hinglish" if _is_hindi(typed) else "en"
    recent = " ".join(ln.text for ln in lines[-6:])
    return "hinglish" if recent and _is_hindi(recent) else "en"


def language_reminder(setting: str, lines: list[Line], typed: str | None = None) -> str:
    """Suffix for the request. Empty for an English conversation on auto, so
    English prompts are exactly as before."""
    lang = answer_language(setting, lines, typed)
    if setting == "auto" and lang == "en":
        return ""
    return f"\n\n({_REMINDERS[lang]})"
