CREATE TABLE IF NOT EXISTS nexent.conversation_share_t (
    share_id integer NOT NULL PRIMARY KEY,
    share_token varchar(64) NOT NULL UNIQUE,
    conversation_id integer NOT NULL,
    tenant_id varchar(100),
    title varchar(200),
    mode varchar(30) DEFAULT 'selected',
    selected_message_ids jsonb,
    snapshot_json jsonb NOT NULL,
    status varchar(30) DEFAULT 'active',
    expire_time timestamp without time zone,
    create_time timestamp without time zone DEFAULT now(),
    update_time timestamp without time zone DEFAULT now(),
    created_by varchar(100),
    updated_by varchar(100),
    delete_flag varchar(1) DEFAULT 'N'
);

CREATE SEQUENCE IF NOT EXISTS nexent.conversation_share_t_share_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE nexent.conversation_share_t_share_id_seq OWNED BY nexent.conversation_share_t.share_id;
ALTER TABLE ONLY nexent.conversation_share_t ALTER COLUMN share_id SET DEFAULT nextval('nexent.conversation_share_t_share_id_seq'::regclass);

CREATE INDEX IF NOT EXISTS idx_conversation_share_token ON nexent.conversation_share_t (share_token);
CREATE INDEX IF NOT EXISTS idx_conversation_share_conversation_id ON nexent.conversation_share_t (conversation_id);

CREATE TABLE IF NOT EXISTS nexent.conversation_share_asset_t (
    share_asset_id integer NOT NULL PRIMARY KEY,
    asset_id varchar(64) NOT NULL UNIQUE,
    share_token varchar(64) NOT NULL,
    object_name varchar(1000) NOT NULL,
    filename varchar(500),
    content_type varchar(200),
    size bigint,
    source_kind varchar(50),
    metadata_json jsonb,
    create_time timestamp without time zone DEFAULT now(),
    update_time timestamp without time zone DEFAULT now(),
    created_by varchar(100),
    updated_by varchar(100),
    delete_flag varchar(1) DEFAULT 'N'
);

CREATE SEQUENCE IF NOT EXISTS nexent.conversation_share_asset_t_share_asset_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;

ALTER SEQUENCE nexent.conversation_share_asset_t_share_asset_id_seq OWNED BY nexent.conversation_share_asset_t.share_asset_id;
ALTER TABLE ONLY nexent.conversation_share_asset_t ALTER COLUMN share_asset_id SET DEFAULT nextval('nexent.conversation_share_asset_t_share_asset_id_seq'::regclass);

CREATE INDEX IF NOT EXISTS idx_conversation_share_asset_token ON nexent.conversation_share_asset_t (share_token);
CREATE INDEX IF NOT EXISTS idx_conversation_share_asset_id ON nexent.conversation_share_asset_t (asset_id);
