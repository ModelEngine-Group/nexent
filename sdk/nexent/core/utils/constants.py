# A think block must include its opening tag.  Making that tag optional lets a
# closing tag consume all preceding answer text during final-answer cleanup.
THINK_TAG_PATTERN = r"<think>.*?</think>"
RERANK_OVERSEARCH_MULTIPLIER = 10 #5

# Pattern to match "思考：" or "思考:" followed by content until two newlines
THINK_PREFIX_PATTERN = r"思考[：:].*?\n\n"
