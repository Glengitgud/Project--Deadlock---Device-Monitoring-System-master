-- Add reversible archive and retained soft-delete states to devices.
-- Back up devmonitor before applying this migration.

ALTER TABLE devices
    ADD COLUMN lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'active' AFTER status,
    ADD COLUMN archived_at DATETIME NULL,
    ADD COLUMN archived_by_user_id BIGINT NULL,
    ADD COLUMN deleted_at DATETIME NULL,
    ADD KEY ix_devices_lifecycle_owner (lifecycle_status, owner_user_id),
    ADD CONSTRAINT fk_devices_archived_by FOREIGN KEY (archived_by_user_id)
        REFERENCES users (id) ON DELETE SET NULL,
    ADD CONSTRAINT ck_devices_lifecycle_status CHECK (
        lifecycle_status IN ('active', 'archived', 'deleted')
    );

-- Older builds used the device status "retired" as an archive marker.
UPDATE devices
SET lifecycle_status = 'archived',
    archived_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
WHERE status = 'retired';
