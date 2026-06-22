-- Step 1: Create sequence for auto-increment
CREATE SEQUENCE IF NOT EXISTS "nexent"."ag_tool_instance_t_tool_instance_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;

CREATE SEQUENCE IF NOT EXISTS "nexent"."ag_agent_relation_t_relation_id_seq" 
INCREMENT 1
MINVALUE  1
MAXVALUE 2147483647
START 1
CACHE 1;
