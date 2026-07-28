"""
Small-talk handler — intercepts casual / greeting messages and
returns a friendly static reply so the LLM is never called.

How it works
------------
1. Normalise the input (lowercase, strip punctuation & extra spaces).
2. Walk through RULES — each rule has a set of trigger phrases and
   a list of replies (picked randomly for variety).
3. If nothing matches → return None  (caller should proceed to LLM).
"""

import random
import re
from utils.logger import get_logger

logger = get_logger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)   # remove punctuation
    text = re.sub(r"\s+", " ", text)       # collapse spaces
    return text


def _exact(phrases: set, text: str) -> bool:
    """True if the normalised text exactly matches any phrase."""
    return text in phrases


def _contains_any(phrases: set, text: str) -> bool:
    """True if the normalised text contains any of the phrases as a word/substring."""
    for phrase in phrases:
        if re.search(r"\b" + re.escape(phrase) + r"\b", text):
            return True
    return False


# ── Rule table ─────────────────────────────────────────────────────────────
# Each rule:
#   "match"   → "exact" (full match) | "contains" (substring/word match)
#   "phrases" → set of normalised trigger strings
#   "replies" → list of friendly human-style responses

RULES = [

    # Greetings
    {
        "match": "contains",
        "phrases": {
            "hi", "hello", "hey", "hiya", "howdy", "sup", "whats up",
            "what's up", "yo", "greetings", "good day",
        },
        "replies": [
            "Hey there! How can I help you with your document today?",
            "Hi! Feel free to ask me anything about the PDF you've uploaded.",
            "Hello! What would you like to know from your document?",
            "Hey! I'm here and ready — what's your question?",
        ],
    },

    # Good morning
    {
        "match": "contains",
        "phrases": {"good morning", "gm", "morning"},
        "replies": [
            "Good morning! Hope your day's off to a great start. What can I help you find in your document?",
            "Morning! Ready to dig into your PDF — what do you need?",
            "Good morning! Ask away, I'm all set to help.",
        ],
    },

    # Good afternoon
    {
        "match": "contains",
        "phrases": {"good afternoon", "afternoon"},
        "replies": [
            "Good afternoon! What would you like to explore in your document?",
            "Afternoon! Happy to help — what's on your mind?",
        ],
    },

    # Good evening / night
    {
        "match": "contains",
        "phrases": {"good evening", "good night", "evening", "gn"},
        "replies": [
            "Good evening! Still got questions? I'm here for you.",
            "Evening! What can I help you with?",
            "Good night — but before you go, feel free to ask anything about your PDF!",
        ],
    },

    # How are you
    {
        "match": "contains",
        "phrases": {
            "how are you", "how r u", "how are u", "hows it going",
            "how's it going", "how do you do", "you good", "you ok",
        },
        "replies": [
            "I'm doing great, thanks for asking! What can I help you with today?",
            "All good on my end! What would you like to know from your document?",
            "Doing well! Ready to answer your questions — what's up?",
        ],
    },

    # Thank you
    {
        "match": "contains",
        "phrases": {
            "thank you", "thanks", "thank u", "thx", "ty",
            "many thanks", "much appreciated", "appreciate it",
        },
        "replies": [
            "You're welcome! Let me know if there's anything else you'd like to know.",
            "Happy to help! Feel free to ask more questions anytime.",
            "Anytime! Is there anything else you'd like me to look into?",
            "Glad I could help! Any other questions?",
        ],
    },

    # Bye / farewell
    {
        "match": "contains",
        "phrases": {
            "bye", "goodbye", "see you", "see ya", "later", "take care",
            "cya", "adios", "farewell", "ttyl", "gtg",
        },
        "replies": [
            "Take care! Come back anytime you have more questions.",
            "Goodbye! It was great helping you out.",
            "See you! Feel free to drop by whenever you need help.",
            "Bye! Hope I was helpful today.",
        ],
    },

    # Who are you / what are you
    {
        "match": "contains",
        "phrases": {
            "who are you", "what are you", "what is your name",
            "whats your name", "your name", "introduce yourself",
        },
        "replies": [
            "I'm DocMind, your AI assistant for reading and understanding PDF documents. Upload a PDF and ask me anything about it!",
            "I'm DocMind! I help you get answers from your uploaded PDF — just ask.",
            "DocMind here — think of me as a smart reader for your documents. What would you like to know?",
        ],
    },

    # What can you do / help
    {
        "match": "contains",
        "phrases": {
            "what can you do", "how can you help", "help me",
            "what do you do", "your capabilities", "how does this work",
            "how do you work",
        },
        "replies": [
            "I can read through any PDF you upload and answer questions about it — summaries, specific details, comparisons, you name it. Just upload a PDF and start asking!",
            "Upload a PDF and I'll help you find answers, summarise content, or explain anything in it. Give it a try!",
            "Pretty simple — upload your PDF, then ask me anything about it. I'll find the answer for you.",
        ],
    },

    # OK / Okay / Alright / Sure
    {
        "match": "exact",
        "phrases": {"ok", "okay", "alright", "sure", "got it", "noted", "cool", "nice", "great"},
        "replies": [
            "Great! What would you like to know from the document?",
            "Sure thing! Feel free to ask your next question.",
            "Got it! Anything else I can help with?",
        ],
    },

    # Laughter / jokes
    {
        "match": "contains",
        "phrases": {"haha", "hehe", "lol", "lmao", "funny", "joke"},
        "replies": [
            "Ha! Glad to lighten the mood. Now, any serious questions about your document?",
            "Ha, I try! Anything I can actually help you find in the PDF?",
        ],
    },

    # Wow / amazing / awesome
    {
        "match": "contains",
        "phrases": {"wow", "amazing", "awesome", "incredible", "impressive", "brilliant"},
        "replies": [
            "Thanks! I do my best. Anything else you'd like to explore in your document?",
            "Glad you think so! What else can I help you with?",
        ],
    },

]


# ── Public API ──────────────────────────────────────────────────────────────

def get_smalltalk_reply(text: str):
    """
    Returns a friendly string reply if the message is small talk,
    or None if the question should go to the LLM.
    """
    normalised = _normalise(text)

    for rule in RULES:
        matched = False
        if rule["match"] == "exact":
            matched = _exact(rule["phrases"], normalised)
        else:
            matched = _contains_any(rule["phrases"], normalised)

        if matched:
            reply = random.choice(rule["replies"])
            logger.info(f"💬 Small-talk matched | input='{text}' | reply='{reply}'")
            return reply

    return None  # not small talk → let the LLM handle it
