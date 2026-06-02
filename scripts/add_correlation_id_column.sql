ALTER TABLE notifications
ADD COLUMN IF NOT EXISTS correlation_id VARCHAR(64);
