CREATE TABLE app_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  backlog_minutes INTEGER NOT NULL DEFAULT 1,
  quiet_start_local TEXT NOT NULL DEFAULT '20:00',
  quiet_end_local TEXT NOT NULL DEFAULT '07:00',
  quiet_timezone TEXT NOT NULL DEFAULT 'Europe/Kyiv',
  rate_limit_seconds INTEGER NOT NULL DEFAULT 30,
  source_group_id TEXT,
  source_group_name TEXT,
  target_group_id TEXT,
  target_group_name TEXT,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE account_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  status TEXT NOT NULL CHECK (status IN ('UNLINKED', 'LINKING', 'LINKED', 'ERROR')),
  signal_account TEXT,
  phone_number TEXT,
  device_id INTEGER,
  linked_at_ms INTEGER,
  last_error TEXT,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE runtime_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  worker_state TEXT NOT NULL CHECK (worker_state IN ('STOPPED', 'STARTING', 'RUNNING', 'ERROR')),
  jsonrpc_state TEXT NOT NULL CHECK (jsonrpc_state IN ('STOPPED', 'CONNECTING', 'CONNECTED', 'ERROR')),
  link_session_id TEXT,
  last_reconnect_at_ms INTEGER,
  last_quiet_exit_at_ms INTEGER,
  last_forward_confirmed_at_ms INTEGER,
  updated_at_ms INTEGER NOT NULL
);

CREATE TABLE forwarded_messages (
  message_key TEXT PRIMARY KEY,
  source_group_id TEXT NOT NULL,
  message_ts_ms INTEGER NOT NULL,
  forwarded_at_ms INTEGER NOT NULL
);

CREATE INDEX idx_forwarded_messages_ts
ON forwarded_messages (message_ts_ms);

CREATE TABLE known_groups (
  group_id TEXT PRIMARY KEY,
  group_name TEXT NOT NULL,
  is_active INTEGER NOT NULL,
  is_blocked INTEGER NOT NULL,
  last_seen_at_ms INTEGER NOT NULL
);
