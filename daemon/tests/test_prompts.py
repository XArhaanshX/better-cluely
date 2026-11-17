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


# Interview and meeting phrasings beyond direct "wh-" questions.
@pytest.mark.parametrize("text", [
    "I'd like to know how you approached the migration",
    "I'm curious about your experience with Kubernetes",
    "Give me an example of a time you disagreed with your manager",
    "Describe a project you are really proud of",
    "Talk about a time when a release went wrong",
    "Do you have any questions for us",
    "Is there anything you would change about the design",
    "Have you worked with Kafka before",
    "And lastly can you explain the difference between a process and a thread",
    "What would you say is your biggest weakness",
    "How many users does the system handle today",
    "Any questions before we wrap up today",
    "So what are your thoughts on microservices",
    "Are there any blockers for this week",
    "Can you do it in linear time? Take your time.",
])
def test_more_questions(text):
    assert looks_like_question(text)


# Statements that start like questions.
@pytest.mark.parametrize("text", [
    "What we did was move everything to Postgres",
    "So what I mean is the cache was stale",
    "When I was at Google we used Spanner for this",
    "How we handled it was by sharding the table",
    "Would love to hear back from you soon",
    "Can't wait to get started on the project",
    "Should be done by Friday at the latest",
    "Where we ended up was a hybrid approach",
    "Will is joining us from the platform team today",
])
def test_more_statements(text):
    assert not looks_like_question(text)


# -- Hindi and Hinglish ------------------------------------------------------

@pytest.mark.parametrize("text", [
    "आपने यह प्रोजेक्ट कैसे बनाया",                 # question word mid-sentence
    "क्या आपने कभी Kubernetes पर काम किया है",       # yes/no with क्या, code-mixed
    "अपने बारे में थोड़ा बताइए",                     # polite request, no question word
    "आपकी सबसे बड़ी कमज़ोरी क्या है",
    "ये तो ठीक है ना",                               # tag question
    "आपने कितने साल काम किया",
    "इस सिस्टम को कैसे स्केल करेंगे?",
    "aapne ye project kaise banaya",                 # romanized Hinglish
    "apne baare mein thoda bataiye",
])
def test_hindi_questions(text):
    assert looks_like_question(text)


@pytest.mark.parametrize("text", [
    "जब मैं गूगल में था तब हमने यही किया",           # जब is relative, not कब
    "पता नहीं क्या हुआ था उस दिन",                   # embedded "no idea what"
    "मैंने यह काम क्योंकि ज़रूरी था इसलिए किया",       # क्योंकि is "because"
    "हमने पूरा डेटाबेस बदल दिया",
    "क्या बात है बहुत बढ़िया",                        # exclamation
    "humne caching use ki thi",
])
def test_hindi_statements(text):
    assert not looks_like_question(text)


def test_answer_language_goes_into_the_system_prompt():
    from wispd.prompts import ANSWER_LANGUAGES
    for key in ANSWER_LANGUAGES:
        assert "Language: " in system_prompt("general", key)
    assert system_prompt("general") == system_prompt("general", "auto")
    assert "Latin script" in system_prompt("interview", "hinglish")


# -- casual Hinglish -----------------------------------------------------------

@pytest.mark.parametrize("text", [
    "abbe tu kab aayega",
    "chal na bata kya hua",                       # fillers in front of a real question
    "yaar mujhe batao na tumne kaise kiya",
    "kya yaar tu kab aayega",                     # reaction, then a real question
    "tu aayega na",                               # tag question after a future verb
    "kal aaoge na",
    "तुम कल आओगे ना",
    "कोड चल गया है ना",                           # tag after an auxiliary
    "वो क्या बोलते हैं उसको कैशिंग उसके बारे में बताइए",  # filler phrase, then a request
    "अरे भाई ये कैसे हुआ",
    "kya scene hai",
    "kyaaa hua",                                  # stretched spelling
    "arre bhai bata",                             # bare request as the last word
    "तू बोल ना कि तूने क्या सोचा",
    "bhai kidhar hai tu",
    "aap karenge kya",
])
def test_casual_hinglish_questions(text):
    assert looks_like_question(text)


@pytest.mark.parametrize("text", [
    "arre kya yaar",                              # exasperation
    "aur kya obviously maine kiya",               # "of course"
    "kyun nahi bilkul",                           # "why not": agreement
    "kya bakwas hai yaar",
    "क्या है कि मैं उस दिन बिज़ी था",               # "the thing is..."
    "वो क्या बोलते हैं उसको हम कैशिंग यूज़ करते थे",  # "what do you call it" filler
    "पता है क्या हुआ कल ऑफिस में",                 # story opener
    "मुझे पता नहीं ना",                            # emphatic "na"
    "nahi na yaar aisa nahi hota",
    "arre bhai sun na",                           # plea, not a question
    "chal na yaar",
    "accha theek hai",
    "हाँ हाँ ठीक है",
    "मैंने बता दिया था उसको",                      # "bata" mid-sentence is just a verb
])
def test_casual_hinglish_statements(text):
    assert not looks_like_question(text)


@pytest.mark.parametrize("text,expected", [
    ("Tell me about a challenge you faced", True),  # "-enge" ending, but English
    ("What was the biggest challenge", True),
    ("We used omega for the release", False),
])
def test_english_words_with_hindi_looking_endings(text, expected):
    assert looks_like_question(text) is expected


# -- answer language decided per request ----------------------------------------

from wispd.prompts import answer_language, language_reminder  # noqa: E402

HINDI_CALL = [Line("them", "अरे यार तो बताओ अपने प्रोजेक्ट के बारे में", 0.0)]
ENGLISH_CALL = [Line("them", "Tell me about your last project", 0.0)]


def test_auto_answers_hindi_calls_in_hinglish_latin_script():
    assert answer_language("auto", HINDI_CALL) == "hinglish"
    assert "Latin" in language_reminder("auto", HINDI_CALL)


def test_auto_leaves_english_calls_exactly_as_before():
    assert answer_language("auto", ENGLISH_CALL) == "en"
    assert language_reminder("auto", ENGLISH_CALL) == ""
    assert language_reminder("auto", []) == ""


def test_typed_questions_follow_the_language_typed():
    assert answer_language("auto", HINDI_CALL, typed="How do I explain caching?") == "en"
    assert answer_language("auto", ENGLISH_CALL, typed="caching kaise samjhaun yaar") == "hinglish"
    assert answer_language("auto", ENGLISH_CALL, typed="कैशिंग कैसे समझाऊँ") == "hi"


def test_a_fixed_setting_always_wins():
    assert answer_language("hi", ENGLISH_CALL) == "hi"
    assert answer_language("en", HINDI_CALL) == "en"
    assert "English" in language_reminder("en", HINDI_CALL)
    assert "Devanagari" in language_reminder("hi", ENGLISH_CALL)
