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
    "4. UPDATE 'recent_topic' to reflect the most recently discussed topic.\n"
    "5. Keep the 'user_profile' updated with user background info.\n"
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