-- MySQL 8.0.16+ (InnoDB); select the target database before running this file.

CREATE TABLE users (
    id BIGINT NOT NULL AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    email VARCHAR(254) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(120) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_users_username (username),
    UNIQUE KEY uq_users_email (email),
    CONSTRAINT ck_users_status CHECK (status IN ('active', 'inactive', 'locked'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE roles (
    id BIGINT NOT NULL AUTO_INCREMENT,
    name VARCHAR(64) NOT NULL,
    description VARCHAR(255) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE permissions (
    id BIGINT NOT NULL AUTO_INCREMENT,
    code VARCHAR(100) NOT NULL,
    description VARCHAR(255) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_permissions_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE devices (
    id BIGINT NOT NULL AUTO_INCREMENT,
    asset_tag VARCHAR(64) NOT NULL,
    device_name VARCHAR(120) NOT NULL,
    hostname VARCHAR(255) NOT NULL,
    device_type VARCHAR(64) NOT NULL,
    serial_number VARCHAR(128) NULL,
    manufacturer VARCHAR(120) NULL,
    model VARCHAR(120) NULL,
    operating_system VARCHAR(120) NULL,
    operating_system_version VARCHAR(120) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'unknown',
    owner_user_id BIGINT NOT NULL,
    registered_by_user_id BIGINT NULL,
    registered_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_seen_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_devices_asset_tag (asset_tag),
    UNIQUE KEY uq_devices_serial_number (serial_number),
    KEY ix_devices_owner_status (owner_user_id, status),
    CONSTRAINT fk_devices_owner FOREIGN KEY (owner_user_id)
        REFERENCES users (id) ON DELETE RESTRICT,
    CONSTRAINT fk_devices_registered_by FOREIGN KEY (registered_by_user_id)
        REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT ck_devices_status CHECK (
        status IN ('online', 'offline', 'maintenance', 'retired', 'unknown')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE logs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NOT NULL,
    event VARCHAR(255) NOT NULL,
    `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_logs_device_timestamp (device_id, `timestamp`),
    CONSTRAINT fk_logs_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE user_roles (
    user_id BIGINT NOT NULL,
    role_id BIGINT NOT NULL,
    PRIMARY KEY (user_id, role_id),
    KEY ix_user_roles_role_id (role_id),
    CONSTRAINT fk_user_roles_user FOREIGN KEY (user_id)
        REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_user_roles_role FOREIGN KEY (role_id)
        REFERENCES roles (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE role_permissions (
    role_id BIGINT NOT NULL,
    permission_id BIGINT NOT NULL,
    PRIMARY KEY (role_id, permission_id),
    KEY ix_role_permissions_permission_id (permission_id),
    CONSTRAINT fk_role_permissions_role FOREIGN KEY (role_id)
        REFERENCES roles (id) ON DELETE CASCADE,
    CONSTRAINT fk_role_permissions_permission FOREIGN KEY (permission_id)
        REFERENCES permissions (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE device_specifications (
    device_id BIGINT NOT NULL,
    cpu_model VARCHAR(255) NULL,
    cpu_cores SMALLINT NULL,
    cpu_threads SMALLINT NULL,
    memory_bytes BIGINT NULL,
    storage_bytes BIGINT NULL,
    gpu_model VARCHAR(255) NULL,
    bios_version VARCHAR(120) NULL,
    motherboard_model VARCHAR(120) NULL,
    operating_system_version VARCHAR(255) NULL,
    collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (device_id),
    CONSTRAINT fk_device_specifications_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE network_interfaces (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NOT NULL,
    interface_name VARCHAR(128) NOT NULL,
    mac_address VARCHAR(17) NULL,
    interface_type VARCHAR(32) NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_interface_device_name (device_id, interface_name),
    KEY ix_network_interfaces_mac (mac_address),
    CONSTRAINT fk_network_interfaces_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE network_observations (
    id BIGINT NOT NULL AUTO_INCREMENT,
    interface_id BIGINT NOT NULL,
    ip_address VARCHAR(45) NULL,
    subnet_prefix SMALLINT NULL,
    gateway VARCHAR(45) NULL,
    dns_servers JSON NULL,
    ssid VARCHAR(255) NULL,
    connection_type VARCHAR(32) NULL,
    observed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_network_observations_interface_time (interface_id, observed_at),
    CONSTRAINT fk_network_observations_interface FOREIGN KEY (interface_id)
        REFERENCES network_interfaces (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE diagnostic_runs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NOT NULL,
    initiated_by_user_id BIGINT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    summary TEXT NULL,
    detected_problem TEXT NULL,
    recommendation TEXT NULL,
    started_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME NULL,
    PRIMARY KEY (id),
    KEY ix_diagnostic_runs_device_started (device_id, started_at),
    CONSTRAINT fk_diagnostic_runs_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE,
    CONSTRAINT fk_diagnostic_runs_initiated_by FOREIGN KEY (initiated_by_user_id)
        REFERENCES users (id) ON DELETE SET NULL,
    CONSTRAINT ck_diagnostic_runs_status CHECK (
        status IN ('running', 'completed', 'failed', 'cancelled')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE diagnostic_checks (
    id BIGINT NOT NULL AUTO_INCREMENT,
    run_id BIGINT NOT NULL,
    check_name VARCHAR(120) NOT NULL,
    category VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL,
    result_summary TEXT NULL,
    details JSON NULL,
    measured_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_diagnostic_check_run_name (run_id, check_name),
    CONSTRAINT fk_diagnostic_checks_run FOREIGN KEY (run_id)
        REFERENCES diagnostic_runs (id) ON DELETE CASCADE,
    CONSTRAINT ck_diagnostic_checks_status CHECK (
        status IN ('passed', 'warning', 'failed', 'skipped')
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE device_metrics (
    id BIGINT NOT NULL AUTO_INCREMENT,
    device_id BIGINT NOT NULL,
    cpu_percent DECIMAL(5,2) NULL,
    memory_percent DECIMAL(5,2) NULL,
    storage_percent DECIMAL(5,2) NULL,
    memory_used_bytes BIGINT NULL,
    storage_used_bytes BIGINT NULL,
    network_rx_bytes BIGINT NULL,
    network_tx_bytes BIGINT NULL,
    collected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_device_metrics_device_time (device_id, collected_at),
    CONSTRAINT fk_device_metrics_device FOREIGN KEY (device_id)
        REFERENCES devices (id) ON DELETE CASCADE,
    CONSTRAINT ck_device_metrics_cpu_percent CHECK (
        cpu_percent IS NULL OR (cpu_percent >= 0 AND cpu_percent <= 100)
    ),
    CONSTRAINT ck_device_metrics_memory_percent CHECK (
        memory_percent IS NULL OR (memory_percent >= 0 AND memory_percent <= 100)
    ),
    CONSTRAINT ck_device_metrics_storage_percent CHECK (
        storage_percent IS NULL OR (storage_percent >= 0 AND storage_percent <= 100)
    )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE activity_logs (
    id BIGINT NOT NULL AUTO_INCREMENT,
    actor_user_id BIGINT NULL,
    event_type VARCHAR(100) NOT NULL,
    entity_type VARCHAR(64) NULL,
    entity_id BIGINT NULL,
    details JSON NULL,
    occurred_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_activity_logs_actor_time (actor_user_id, occurred_at),
    KEY ix_activity_logs_entity (entity_type, entity_id),
    CONSTRAINT fk_activity_logs_actor FOREIGN KEY (actor_user_id)
        REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
