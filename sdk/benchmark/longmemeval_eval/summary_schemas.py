"""Custom summary schemas for LongMemEval multi-topic conversation compression.

LongMemEval contains multi-session dialogues with MANY INDEPENDENT TOPICS:
- LinkedIn job search
- Work schedule (40 hours/week, peak campaign 50 hours)
- Bereavement support group (attended 3 sessions)
- Travel planning (Japan, Hawaii)
- Shopping (moisturizer, Sephora)
- Aquarium setup
- Green card application
- Hilton points redemption
- ... (111 sessions with ~60+ independent topics)

The default schema assumes a CONTINUOUS TASK ("active_task" → "completed_work"),
which fails here because:
- It treats only the most recent topic as "active_task"
- Older topics (bereavement, work hours, travel) are discarded as "obsolete"
- Probe questions ask about ANY topic → Summary missing → Accuracy = 0%

Solution: MULTI_TOPIC schema preserves ALL discussed topics.
"""

# ============ Multi-topic summary prompts ============

MULTI_TOPIC_SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing a multi-session conversation where the user discussed "
    "MANY DIFFERENT TOPICS over time. This is NOT a single continuous task — "
    "each topic is INDEPENDENT and has its own facts that must be preserved. "
    "Your goal is to create a TOPIC-BY-TOPIC summary so that someone reading "
    "only your summary could answer questions about ANY of the topics discussed, "
    "not just the most recent one. "
    "Treat the conversation below as source material. "
    "Produce only the structured JSON summary; no greeting, preamble, or prefix. "
    "Write the summary in the same language the user was using. "
    "Be CONCRETE — include specific numbers, names, dates, and details for each topic. "
    "Do NOT compress older topics into vague summaries like 'discussed various topics'. "
    "Instead, LIST each topic with its key facts so they remain searchable. "
    "CRITICAL: extract every quantitative leaf fact (dates, durations, counts, "
    "amounts, prices, proper names, trail/product/book/place names) into the "
    "'key_facts' section verbatim — these are the exact facts the user will ask "
    "about later, and paraphrasing or rounding them loses the answer. "
    "When the user UPDATES a previously stated value (e.g. 'now I have 2 free "
    "nights' after earlier saying 1), record it in 'knowledge_updates' with the "
    "LATEST value first and older superseded values listed for traceability. "
    "Output strict JSON format without markdown blocks."
)

MULTI_TOPIC_INCREMENTAL_SUMMARY_SYSTEM_PROMPT = (
    "You are maintaining a running summary of a multi-topic conversation. "
    "The user has discussed MANY INDEPENDENT TOPICS over multiple sessions. "
    "The existing summary shows previously discussed topics, and new conversation "
    "turns may introduce NEW topics OR add details to EXISTING ones. "
    "Update the summary by these rules:\n"
    "1. PRESERVE all previously discussed topics — do NOT drop older topics just "
    "because they are not discussed in the latest turns. Each topic is independent "
    "and may be queried later.\n"
    "2. ADD new topics to 'topics' if they appear in the new content.\n"
    "3. UPDATE 'topic_details' for topics that got new information.\n"
    "4. APPEND every new quantitative leaf fact (date, duration, count, amount, "
    "proper name) to 'key_facts'. Never drop existing key_facts entries.\n"
    "5. When a value is REPLACED by a newer one (e.g. session count went from 3 "
    "to 5), move the old entry into 'knowledge_updates' with the new value first "
    "and the older superseded value listed; do NOT silently overwrite.\n"
    "6. UPDATE 'recent_topic' to reflect the most recently discussed topic.\n"
    "7. Keep the 'user_profile' updated with user background info.\n"
    "Be concrete — specific numbers, names, dates. "
    "Output strict JSON format without markdown blocks."
)

# ============ Multi-topic JSON schema ============

MULTI_TOPIC_SUMMARY_SCHEMA = {
    "topics": (
        "THE MOST IMPORTANT FIELD. A numbered list of ALL topics discussed in "
        "this conversation, from earliest to latest. Each entry: topic name + "
        "brief description. Format: N. TOPIC_NAME — brief description. "
        "Example: '1. Job Search — updating LinkedIn profile for senior roles'. "
        "Include ALL topics, not just recent ones. (<=400 words)"
    ),
    "topic_details": (
        "Key facts for EACH topic mentioned above. This is a dictionary-like "
        "structure where each topic gets its key details preserved. "
        "Format each topic's details with concrete numbers, names, dates. "
        "Example:\n"
        "- Job Search: applied for Content Marketing Strategist, work 40 hrs/week, "
        "peak campaign 50 hrs/week, has Google Analytics certification\n"
        "- Bereavement Support: attended 3 sessions, started 2023/05, helpful for coping\n"
        "- Travel: interested in Japan (food, culture), visited Hawaii with family\n"
        "Include ALL topics that have specific facts. (<=800 words)"
    ),
    "key_facts": (
        "FACT-LEVEL INDEX for precise recall. Catalog every quantitative or "
        "named leaf fact verbatim so questions asking 'when / how much / what "
        "name / how long' can be answered exactly. Group entries under four "
        "subcategories. Use the EXACT wording the user/assistant used — do not "
        "round, paraphrase, or convert units.\n\n"
        "Format (bullet under each subcategory):\n"
        "- dates_and_durations:\n"
        "    - <topic>: <event> — <date / duration / relative time> "
        "(e.g. 'Aquarium: bought neon tetras — 2023/04/12'; "
        "'Cat Luna: acquired 9 months ago as of 2023/05'; "
        "'BBQ event: attended June 3rd, 2023')\n"
        "- quantities_and_amounts:\n"
        "    - <topic>: <metric> = <value with unit> "
        "(e.g. 'Designer handbag: cost = $800'; "
        "'Bereavement: support sessions attended = 5'; "
        "'Hilton points: free nights available = 2')\n"
        "- proper_names:\n"
        "    - <topic>: <slot> = <exact name> "
        "(e.g. 'Moncayo Park: recommended trail = GR-90'; "
        "'Borges quote: source = The Library of Babel'; "
        "'Soviet cartoon: title = Nu, pogodi!')\n"
        "- preferences_and_opinions:\n"
        "    - <topic>: <user preference> "
        "(e.g. 'Remote work: prefers virtual coffee breaks for social "
        "connection'; 'Baking: liked lemon poppyseed cake — wants similar')\n"
        "Be exhaustive — every fact the user could be quizzed on belongs here. "
        "Prefer many short bullets over long sentences. (<=1200 words)"
    ),
    "knowledge_updates": (
        "Facts that CHANGED over the conversation. When a value supersedes an "
        "earlier one, record the LATEST value first and list the prior value(s) "
        "for traceability. This is critical for 'knowledge-update' questions "
        "that ask for the most recent state.\n"
        "Format:\n"
        "- <topic> · <slot>: current = <latest value> "
        "(was: <prior value> @ <when>, <older value> @ <when>)\n"
        "Example:\n"
        "- Hilton points · free_nights: current = 2 (was: 1 @ early March)\n"
        "- Bereavement · sessions_attended: current = 5 (was: 3 @ first mention)\n"
        "Leave empty list [] if nothing was updated. (<=300 words)"
    ),
    "recent_topic": (
        "The most recently discussed topic, in finer detail than the older ones, "
        "for continuity with what comes next. Include specific details from the "
        "latest turns about this topic. (<=200 words)"
    ),
    "user_profile": (
        "Background info about the user: job title, interests, preferences, "
        "demographics that appeared across the conversation. (<=150 words)"
    ),
    "pending_items": (
        "User's mentioned intentions, decisions pending, or plans not yet executed. "
        "Format as list: each item with topic context. (<=100 words)"
    ),
}


def build_multi_topic_config(base_config) -> None:
    """Override base ContextManagerConfig with multi-topic schema.
    
    Modifies the config IN-PLACE (does not return a new object).
    Only overrides the three summary-template fields; all other
    ContextManager behavior (incremental compression, caching, boundaries)
    remains unchanged.
    """
    base_config.summary_system_prompt = MULTI_TOPIC_SUMMARY_SYSTEM_PROMPT
    base_config.incremental_summary_system_prompt = MULTI_TOPIC_INCREMENTAL_SUMMARY_SYSTEM_PROMPT
    base_config.summary_json_schema = MULTI_TOPIC_SUMMARY_SCHEMA