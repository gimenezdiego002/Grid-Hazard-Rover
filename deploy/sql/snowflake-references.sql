-- Manual setup in the explicitly chosen existing database/schema/warehouse.
-- This file creates no warehouse, Cortex Search service, account, or role.
-- Review compute credits and reserve the bounded setup cost before executing.
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 5;
ALTER SESSION SET STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 5;

CREATE TABLE IF NOT EXISTS RELAY_REFERENCES (
    REFERENCE_ID VARCHAR(128) NOT NULL,
    HAZARD_TYPE VARCHAR(80) NOT NULL,
    TITLE VARCHAR(200) NOT NULL,
    BODY VARCHAR(2000) NOT NULL,
    SOURCE_URL VARCHAR(1024) NOT NULL,
    IS_SIMULATED BOOLEAN NOT NULL DEFAULT TRUE
);

-- Synthetic demo passages, not external guidance or real inspection history.
-- The merge is rerunnable. Execute setup serially; standard Snowflake table
-- primary/unique constraints would not enforce uniqueness for concurrent loads.
MERGE INTO RELAY_REFERENCES AS target
USING (
    SELECT column1 AS REFERENCE_ID, column2 AS HAZARD_TYPE, column3 AS TITLE,
           column4 AS BODY, column5 AS SOURCE_URL, column6 AS IS_SIMULATED
    FROM VALUES
      ('fixture-water-review-v1', 'standing_water', 'Synthetic water inspection procedure',
       'Demo procedure: keep a suspected water finding visible for human review. A second independent observation may help corroborate it.',
       'relay://fixtures/water-review-v1', TRUE),
      ('fixture-water-routing-v1', 'standing_water', 'Synthetic route review note',
       'Demo procedure: propose inspection of the affected area; route and actuator decisions remain with the deterministic coordinator and operator.',
       'relay://fixtures/water-routing-v1', TRUE)
) AS source ON target.REFERENCE_ID = source.REFERENCE_ID
WHEN NOT MATCHED THEN INSERT (REFERENCE_ID, HAZARD_TYPE, TITLE, BODY, SOURCE_URL, IS_SIMULATED)
VALUES (source.REFERENCE_ID, source.HAZARD_TYPE, source.TITLE, source.BODY, source.SOURCE_URL, source.IS_SIMULATED);

-- Give the runtime role only USAGE on the selected warehouse/database/schema
-- and SELECT on RELAY_REFERENCES. Suspend the warehouse when the demo is done.
