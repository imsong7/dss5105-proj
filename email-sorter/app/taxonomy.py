"""The two classification schemes. Edit labels/descriptions here only.
The prompt, validation and web UI all read from these dictionaries."""

CONTENT_CATEGORIES = {
    "medical": {
        "label": "Medical",
        "desc": "Health, clinic or hospital messages, appointments, insurance, vaccination, counselling, medical certificates.",
    },
    "promotional": {
        "label": "Promotional",
        "desc": "Marketing, offers, discounts, newsletters, sales, advertising of events or products.",
    },
    "career": {
        "label": "Career related",
        "desc": "Jobs, internships, recruiters, career fairs, CV or interview help, networking, professional development.",
    },
    "canva": {
        "label": "Canva",
        "desc": "Anything sent by or about Canva: design invites, shared designs, comments, team or licence notices.",
    },
    "general": {
        "label": "General",
        "desc": "Everyday university or personal messages that fit nothing else: announcements, timetables, campus notices, lecturers, classmates.",
    },
    "others": {
        "label": "Others",
        "desc": "Anything that clearly does not fit the categories above.",
    },
}

# Listed in priority order: if several apply, the first one wins.
REPLY_NATURE = {
    "needs_action": {
        "label": "Needs action",
        "desc": "The reader must do something other than write back: fill a form, submit a document, register, pay, sign, upload, confirm online.",
    },
    "needs_reply": {
        "label": "Needs a reply",
        "desc": "A person is asking a question or expecting a written response.",
    },
    "reminder": {
        "label": "Reminder",
        "desc": "Contains a date or time limit but asks for no specific action or reply (for example a reminder or notice).",
    },
    "no_immediate_action": {
        "label": "No immediate action",
        "desc": "Purely informational, automated or promotional. Nothing needs to be done.",
    },
}

DEFAULT_CONTENT = "others"
DEFAULT_REPLY = "no_immediate_action"
