-- Add business_logic_model_name and business_logic_model_id fields to ag_tenant_agent_t table
-- These fields store the LLM model used for generating business logic prompts

ALTER TABLE nexent.ag_tenant_agent_t 
ADD COLUMN IF NOT EXISTS business_logic_model_name VARCHAR(100);

ALTER TABLE nexent.ag_tenant_agent_t 
ADD COLUMN IF NOT EXISTS business_logic_model_id INTEGER;

COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_name IS 'Model name used for business logic prompt generation';
COMMENT ON COLUMN nexent.ag_tenant_agent_t.business_logic_model_id IS 'Model ID used for business logic prompt generation, foreign key reference to model_record_t.model_id';

