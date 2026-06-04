CREATE TABLE IF NOT EXISTS notification_push_tokens (
    id SERIAL PRIMARY KEY,
    recipient_id VARCHAR(128) NOT NULL,
    expo_push_token VARCHAR(255) NOT NULL,
    platform VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_notification_push_tokens_token
ON notification_push_tokens(expo_push_token);

CREATE INDEX IF NOT EXISTS ix_notification_push_tokens_recipient_enabled
ON notification_push_tokens(recipient_id, enabled);
