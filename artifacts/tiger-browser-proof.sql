-- Browser SQL Editor setup/proof recipe using one synthetic telemetry event.
-- Requires an existing authorized Tiger Data service and relay_telemetry schema
-- from deploy/sql/tiger-telemetry.sql. This does not provision any resources.
-- The one-time initial-insert assertion intentionally blocks rerunning the
-- transaction after its event has committed. Do not delete data to bypass it.
-- Confirm successful COMMIT before running the separate read-only SELECT below.
-- Browser SQL success does not demonstrate local adapter connectivity.

BEGIN;
SET LOCAL statement_timeout = '5s';
SET LOCAL lock_timeout = '2s';
SET LOCAL transaction_timeout = '10s';

DO $proof$
DECLARE
    inserted_rows INTEGER;
    replay_rows INTEGER;
    window_rows INTEGER;
    payload_matches BOOLEAN;
BEGIN
    INSERT INTO relay_telemetry (
        mission_id, event_id, robot_id, observed_at,
        kind, value_milli, simulated, latitude, longitude
    ) VALUES (
        'relay-browser-proof-20260926-v1', 'water-proof-001', 'station-a',
        TIMESTAMPTZ '2026-09-26T18:00:00Z',
        'water', 850, TRUE, NULL, NULL
    )
    ON CONFLICT (mission_id, event_id) DO NOTHING;

    GET DIAGNOSTICS inserted_rows = ROW_COUNT;
    IF inserted_rows <> 1 THEN
        RAISE EXCEPTION 'Proof blocked: initial insert must create exactly one row.';
    END IF;

    INSERT INTO relay_telemetry (
        mission_id, event_id, robot_id, observed_at,
        kind, value_milli, simulated, latitude, longitude
    ) VALUES (
        'relay-browser-proof-20260926-v1', 'water-proof-001', 'station-a',
        TIMESTAMPTZ '2026-09-26T18:00:00Z',
        'water', 850, TRUE, NULL, NULL
    )
    ON CONFLICT (mission_id, event_id) DO NOTHING;

    GET DIAGNOSTICS replay_rows = ROW_COUNT;
    IF replay_rows <> 0 THEN
        RAISE EXCEPTION 'Proof failed: identical replay inserted another row.';
    END IF;

    SELECT COUNT(*),
           BOOL_AND(
               event_id = 'water-proof-001'
               AND robot_id = 'station-a'
               AND observed_at = TIMESTAMPTZ '2026-09-26T18:00:00Z'
               AND kind = 'water'
               AND value_milli = 850
               AND simulated IS TRUE
               AND latitude IS NULL
               AND longitude IS NULL
           )
    INTO window_rows, payload_matches
    FROM (
        SELECT *
        FROM relay_telemetry
        WHERE mission_id = 'relay-browser-proof-20260926-v1'
          AND observed_at >= TIMESTAMPTZ '2026-09-26T17:59:00Z'
          AND observed_at < TIMESTAMPTZ '2026-09-26T18:01:00Z'
        ORDER BY observed_at, event_id
        LIMIT 2
    ) AS bounded_window;

    IF window_rows <> 1 OR payload_matches IS DISTINCT FROM TRUE THEN
        RAISE EXCEPTION 'Proof failed: window count or stored payload differs.';
    END IF;
END
$proof$;

COMMIT;

-- Separate read-only verification after the transaction succeeds.
SELECT
    mission_id, event_id, robot_id, observed_at,
    kind, value_milli, simulated, latitude, longitude
FROM relay_telemetry
WHERE mission_id = 'relay-browser-proof-20260926-v1'
  AND observed_at >= TIMESTAMPTZ '2026-09-26T17:59:00Z'
  AND observed_at < TIMESTAMPTZ '2026-09-26T18:01:00Z'
ORDER BY observed_at, event_id
LIMIT 2;
