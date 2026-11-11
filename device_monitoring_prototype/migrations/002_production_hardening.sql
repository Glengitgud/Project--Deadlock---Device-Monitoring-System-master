-- Migration 002: Production Hardening, Endpoint Agent Tokens, and Alerts

ALTER TABLE users
    ADD COLUMN failed_login_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN locked_until DATETIME NULL,
    ADD COLUMN totp_secret VARCHAR(64) NULL,
    ADD COLUMN mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE devices
    ADD COLUMN api_token VARCHAR(64) NULL,
    ADD UNIQUE KEY uq_devices_api_token (api_token);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'warning',
    title VARCHAR(120) NOT NULL,
    message TEXT NOT NULL,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_alerts_device_time (device_id, created_at),
    CONSTRAINT fk_alerts_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE,
    CONSTRAINT ck_alerts_severity CHECK (
        severity IN ('info', 'warning', 'critical')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
