-- Persist an immutable execution framework on every Agent version row.

ALTER TABLE nexent.ag_tenant_agent_t
ADD COLUMN IF NOT EXISTS runtime_framework VARCHAR(20);

UPDATE nexent.ag_tenant_agent_t
SET runtime_framework = 'smolagents'
WHERE runtime_framework IS NULL;

ALTER TABLE nexent.ag_tenant_agent_t
DROP CONSTRAINT IF EXISTS ck_ag_tenant_agent_runtime_framework;
ALTER TABLE nexent.ag_tenant_agent_t
ADD CONSTRAINT ck_ag_tenant_agent_runtime_framework
CHECK (runtime_framework IS NULL OR runtime_framework IN ('smolagents', 'openjiuwen'));

COMMENT ON COLUMN nexent.ag_tenant_agent_t.runtime_framework
IS 'Immutable execution framework: smolagents or openjiuwen';

CREATE OR REPLACE FUNCTION nexent.enforce_agent_runtime_framework_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.runtime_framework IS NOT NULL
       AND NEW.runtime_framework IS DISTINCT FROM OLD.runtime_framework THEN
        RAISE EXCEPTION 'AGENT_RUNTIME_FRAMEWORK_IMMUTABLE'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS enforce_agent_runtime_framework_immutable_trigger
ON nexent.ag_tenant_agent_t;
CREATE TRIGGER enforce_agent_runtime_framework_immutable_trigger
BEFORE UPDATE OF runtime_framework ON nexent.ag_tenant_agent_t
FOR EACH ROW
EXECUTE FUNCTION nexent.enforce_agent_runtime_framework_immutable();
