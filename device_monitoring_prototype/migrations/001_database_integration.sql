-- Apply once to databases created with the earlier schema.sql.
-- Back up the database first. Assign owners to any existing ownerless devices
-- before the NOT NULL alteration below.

ALTER TABLE users MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE roles MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE permissions MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE devices MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE network_interfaces MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE network_observations MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE diagnostic_runs MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE diagnostic_checks MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE device_metrics MODIFY id BIGINT NOT NULL AUTO_INCREMENT;
ALTER TABLE activity_logs MODIFY id BIGINT NOT NULL AUTO_INCREMENT;

ALTER TABLE devices ADD COLUMN device_name VARCHAR(120) NULL AFTER asset_tag;
UPDATE devices SET device_name = hostname WHERE device_name IS NULL;
ALTER TABLE devices MODIFY device_name VARCHAR(120) NOT NULL;
ALTER TABLE devices DROP FOREIGN KEY fk_devices_owner;
ALTER TABLE devices MODIFY owner_user_id BIGINT NOT NULL;
ALTER TABLE devices ADD CONSTRAINT fk_devices_owner FOREIGN KEY (owner_user_id)
    REFERENCES users (id) ON DELETE RESTRICT;

RENAME TABLE hardware_specs TO device_specifications;
ALTER TABLE device_specifications
    ADD COLUMN operating_system_version VARCHAR(255) NULL;

ALTER TABLE diagnostic_runs
    ADD COLUMN detected_problem TEXT NULL,
    ADD COLUMN recommendation TEXT NULL;

CREATE TABLE network_records (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NOT NULL,
    ip_address VARCHAR(45) NULL,
    subnet_mask VARCHAR(45) NULL,
    default_gateway VARCHAR(45) NULL,
    dns_server VARCHAR(255) NULL,
    connectivity_status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    recorded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_network_records_device_time (device_id, recorded_at),
    CONSTRAINT fk_network_records_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE,
    CONSTRAINT ck_network_records_connectivity CHECK (
        connectivity_status IN ('connected', 'disconnected', 'unknown')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
