-- Upgrade the original empty XAMPP prototype tables to the current ORM schema.
-- Back up devmonitor before applying this migration.
-- This migration assumes users, devices, and logs contain no rows because the
-- original schema does not record enough information to assign device owners
-- or to safely convert existing plaintext passwords to password hashes.

ALTER TABLE logs DROP FOREIGN KEY logs_ibfk_1;

ALTER TABLE users
    MODIFY id BIGINT NOT NULL AUTO_INCREMENT,
    MODIFY username VARCHAR(64) NOT NULL,
    ADD COLUMN email VARCHAR(254) NOT NULL AFTER username,
    ADD COLUMN password_hash VARCHAR(255) NOT NULL AFTER password,
    ADD COLUMN display_name VARCHAR(120) NULL AFTER password_hash,
    ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active' AFTER display_name,
    ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    ADD COLUMN last_login_at DATETIME NULL,
    ADD UNIQUE KEY uq_users_email (email);

ALTER TABLE devices
    MODIFY id BIGINT NOT NULL AUTO_INCREMENT,
    MODIFY device_name VARCHAR(120) NOT NULL,
    ADD COLUMN asset_tag VARCHAR(64) NOT NULL,
    ADD COLUMN hostname VARCHAR(255) NOT NULL,
    ADD COLUMN device_type VARCHAR(64) NOT NULL,
    ADD COLUMN serial_number VARCHAR(128) NULL,
    ADD COLUMN manufacturer VARCHAR(120) NULL,
    ADD COLUMN model VARCHAR(120) NULL,
    ADD COLUMN operating_system VARCHAR(120) NULL,
    ADD COLUMN operating_system_version VARCHAR(120) NULL,
    MODIFY status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    ADD COLUMN owner_user_id BIGINT NOT NULL,
    ADD COLUMN registered_by_user_id BIGINT NULL,
    ADD COLUMN registered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    ADD COLUMN last_seen_at DATETIME NULL,
    ADD UNIQUE KEY uq_devices_asset_tag (asset_tag),
    ADD UNIQUE KEY uq_devices_serial_number (serial_number),
    ADD KEY ix_devices_owner_status (owner_user_id, status),
    ADD CONSTRAINT fk_devices_owner FOREIGN KEY (owner_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    ADD CONSTRAINT fk_devices_registered_by FOREIGN KEY (registered_by_user_id)
        REFERENCES users (id) ON DELETE SET NULL;

ALTER TABLE logs
    MODIFY id BIGINT NOT NULL AUTO_INCREMENT,
    MODIFY device_id BIGINT NOT NULL,
    MODIFY event VARCHAR(255) NOT NULL,
    MODIFY `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD KEY ix_logs_device_timestamp (device_id, `timestamp`),
    ADD CONSTRAINT fk_logs_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE;
