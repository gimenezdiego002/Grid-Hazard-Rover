-- Manual, reviewed schema setup on an already authorized Tiger Data service.
-- Does not create a service, extension, role, or paid background process.
BEGIN;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';
CREATE TABLE IF NOT EXISTS relay_telemetry (
    mission_id VARCHAR(128) NOT NULL,
    event_id VARCHAR(128) NOT NULL,
    robot_id VARCHAR(128) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    kind VARCHAR(40) NOT NULL,
    value_milli BIGINT,
    simulated BOOLEAN NOT NULL,
    latitude DOUBLE PRECISION CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION CHECK (longitude BETWEEN -180 AND 180),
    PRIMARY KEY (mission_id, event_id)
);
CREATE INDEX IF NOT EXISTS relay_telemetry_mission_time
    ON relay_telemetry (mission_id, observed_at, event_id);
COMMIT;

-- The regular table retains a unique event identity independent of event time.
-- This is deliberately not a hypertable: time-partitioned unique constraints
-- would also have to include time, weakening that identity without another table.
-- Grant the runtime user only SELECT/INSERT on this table through the account UI.
