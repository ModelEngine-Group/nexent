-- Support bounded cleanup scans without reading every NL2AGENT session.
CREATE INDEX IF NOT EXISTS idx_nl2agent_session_status_update
ON nexent.nl2agent_session_t (status, update_time);
