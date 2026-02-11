-- Create prompt template table
CREATE SEQUENCE IF NOT EXISTS nexent.prompt_template_t_template_id_seq;

CREATE TABLE IF NOT EXISTS nexent.prompt_template_t (
  template_id INTEGER PRIMARY KEY DEFAULT nextval('nexent.prompt_template_t_template_id_seq'),
  name VARCHAR(200),
  description VARCHAR(2000),
  prompt_text TEXT,
  is_builtin BOOLEAN DEFAULT FALSE,
  tenant_id VARCHAR(100),
  create_time TIMESTAMP DEFAULT now(),
  update_time TIMESTAMP DEFAULT now(),
  created_by VARCHAR(100),
  updated_by VARCHAR(100),
  delete_flag VARCHAR(1) DEFAULT 'N'
);
