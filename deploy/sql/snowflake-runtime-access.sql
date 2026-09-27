-- ONE-TIME APPROVED SETUP RECORD -- EXECUTED. DO NOT RERUN THIS FILE.
-- The user explicitly approved this isolated ShellHacks Relay service credential,
-- its inherited PUBLIC privileges, current-IP restriction, encrypted local storage
-- and one budgeted SQL API query. That proof completed on the first dispatch.
-- This record does not authorize replacement credentials or additional queries.
-- No token, password or actual operator IP is included. Credential-returning and
-- activation commands remain commented as historical reference, not instructions.
-- Evidence: artifacts/snowflake-live-proof.json and snowflake-access-proof.json.
-- The role, user, network rule and policy below already exist. DDL is not a
-- transaction; do not replace, recreate or blindly rerun the recorded setup.
--
-- Prerequisites already managed separately:
--   transient database SHELLHACKS_RELAY; schema INSPECTION; RELAY_REFERENCES table
--   RELAY_REFERENCE_WH: XSMALL Gen1, AUTO_SUSPEND=60, AUTO_RESUME=FALSE,
--   STATEMENT_TIMEOUT_IN_SECONDS=5, STATEMENT_QUEUED_TIMEOUT_IN_SECONDS=5
-- An authorized administrator must verify these resources and the existing
-- cumulative spending reservation before setup or a deliberate compute resume.
-- Use an administrator with the necessary creation, ownership/grant and network
-- policy privileges. No administrator role is assigned to the runtime user.
--
-- The private executed copy substituted the verified operator public IPv4 for
-- <OPERATOR_PUBLIC_IPV4>, retaining /32. This published record keeps the placeholder.
-- Keep the real address in the local copy, not the committed file.
-- Do not widen the CIDR, add an unrestricted address, or bypass network policy.
-- If the operator's address changes, re-review the exact replacement address.
--
-- EFFECTIVE ACCESS IS BROADER THAN THE FOUR EXPLICIT READER GRANTS.
-- The operator's 2026-09-26 SHOW GRANTS TO ROLE PUBLIC inspection returned 109
-- grants, including USE AI FUNCTIONS, EXECUTE AGENT TASK, BIND SERVICE ENDPOINT,
-- MANAGE ARTIFACT PUBLICATION, USAGE on SYSTEM_COMPUTE_POOL_CPU/GPU, and access
-- to the sample database. These are observed account grants, not added here.
-- PUBLIC is automatically granted to every role and user. PAT ROLE_RESTRICTION
-- limits the role used for authorization and excludes secondary roles; it does
-- not remove the chosen role's inherited PUBLIC privileges. Consequently, this
-- credential is NOT strictly read-only or limited to a table-only permission set.
-- The /32 network policy, one-day PAT, warehouse settings and bounded application
-- query do not remove those inherited permissions or establish an account cost cap.
-- The user expressly approved this effective scope for the one-time credential
-- and query. Re-review changed grants before any separately authorized future
-- operation. This setup did not change PUBLIC or any account-wide security or
-- authentication setting.
-- Preflight metadata, executed separately by the administrator:
-- SHOW GRANTS TO ROLE PUBLIC;
-- SHOW USERS LIKE 'RELAY_REFERENCE_CLIENT';
-- SHOW ROLES LIKE 'RELAY_REFERENCE_READER';
-- SHOW WAREHOUSES LIKE 'RELAY_REFERENCE_WH';
-- SHOW PARAMETERS IN WAREHOUSE RELAY_REFERENCE_WH;

-- 1. Restrict ingress to one operator address. This network rule lives only in
-- the Relay schema; the policy is attached to the new service user below.
CREATE NETWORK RULE SHELLHACKS_RELAY.INSPECTION.RELAY_REFERENCE_OPERATOR_IPV4
    TYPE = IPV4
    VALUE_LIST = ('<OPERATOR_PUBLIC_IPV4>/32')
    MODE = INGRESS
    COMMENT = 'Relay reference client operator IPv4 only';

CREATE NETWORK POLICY RELAY_REFERENCE_OPERATOR_ONLY
    ALLOWED_NETWORK_RULE_LIST = (
        'SHELLHACKS_RELAY.INSPECTION.RELAY_REFERENCE_OPERATOR_IPV4'
    )
    COMMENT = 'User-level policy for Relay reference client only';

-- 2. The reader receives exactly four explicit object privileges. No write,
-- ownership, future-object, grant-option or warehouse OPERATE privilege is added.
CREATE ROLE RELAY_REFERENCE_READER
    COMMENT = 'Read synthetic Relay inspection references';

GRANT USAGE ON WAREHOUSE RELAY_REFERENCE_WH
    TO ROLE RELAY_REFERENCE_READER;
GRANT USAGE ON DATABASE SHELLHACKS_RELAY
    TO ROLE RELAY_REFERENCE_READER;
GRANT USAGE ON SCHEMA SHELLHACKS_RELAY.INSPECTION
    TO ROLE RELAY_REFERENCE_READER;
GRANT SELECT ON TABLE SHELLHACKS_RELAY.INSPECTION.RELAY_REFERENCES
    TO ROLE RELAY_REFERENCE_READER;

-- 3. Initial creation used a disabled service identity with no password or key
-- pair; it was subsequently enabled for the approved proof. The policy was set
-- only on this user, never on the account or the operator's user.
CREATE USER RELAY_REFERENCE_CLIENT
    TYPE = SERVICE
    DISABLED = TRUE
    DEFAULT_ROLE = 'RELAY_REFERENCE_READER'
    DEFAULT_SECONDARY_ROLES = ()
    DEFAULT_WAREHOUSE = 'RELAY_REFERENCE_WH'
    DEFAULT_NAMESPACE = 'SHELLHACKS_RELAY.INSPECTION'
    COMMENT = 'One-time approved bounded Relay SQL API proof'
    NETWORK_POLICY = 'RELAY_REFERENCE_OPERATOR_ONLY'
    STATEMENT_TIMEOUT_IN_SECONDS = 5
    STATEMENT_QUEUED_TIMEOUT_IN_SECONDS = 5;

GRANT ROLE RELAY_REFERENCE_READER TO USER RELAY_REFERENCE_CLIENT;

-- 4. Metadata checks verified TYPE=SERVICE, this network policy, the sole explicit
-- role RELAY_REFERENCE_READER and the four explicit grants above. PUBLIC's
-- inherited privileges remain part of the approved effective scope.
-- SHOW GRANTS TO USER RELAY_REFERENCE_CLIENT;
-- SHOW GRANTS TO ROLE RELAY_REFERENCE_READER;
-- DESCRIBE USER RELAY_REFERENCE_CLIENT;
-- DESCRIBE NETWORK POLICY RELAY_REFERENCE_OPERATOR_ONLY;
-- DESCRIBE NETWORK RULE SHELLHACKS_RELAY.INSPECTION.RELAY_REFERENCE_OPERATOR_IPV4;

-- ONE-TIME ENABLE / TOKEN GENERATION COMPLETED -- DO NOT REPEAT.
-- Metadata showed the PAT ACTIVE, restricted to RELAY_REFERENCE_READER, created
-- 2026-09-27T00:34:29.052Z and expiring 2026-09-28T00:34:29.052Z (one day).
-- No network policy bypass was set. Windows DPAPI storage and an in-memory
-- decryption comparison were verified without disclosing the token.
-- The statements below remain commented. Token output is secret and must never
-- enter logs, screenshots, Git or chat. This approval covers no future token.
-- ALTER USER RELAY_REFERENCE_CLIENT SET DISABLED = FALSE;
-- ALTER USER RELAY_REFERENCE_CLIENT
--     ADD PROGRAMMATIC ACCESS TOKEN RELAY_REFERENCE_PROOF_1DAY
--     ROLE_RESTRICTION = 'RELAY_REFERENCE_READER'
--     DAYS_TO_EXPIRY = 1
--     COMMENT = 'One-day bounded Relay reference retrieval proof';
--
-- The guarded CLI separately requires explicit live opt-in and spending admission.
-- AUTO_RESUME remains FALSE. An administrator resumed the warehouse for the
-- reserved proof and successfully suspended it afterward. AUTO_SUSPEND=60 remains.
-- The runtime role's explicit warehouse grant does not include OPERATE.
-- A completed retrieval alone does not prove Gemini used the passages.

-- SHUTDOWN / REVOCATION -- administrator actions, intentionally commented.
-- Disable access when the proof window ends; disabling the user also interrupts
-- its running queries. Remove the named token only if it was actually created.
-- Token removal must use an administrator session not authenticated with a PAT.
-- ALTER USER RELAY_REFERENCE_CLIENT SET DISABLED = TRUE;
-- ALTER USER RELAY_REFERENCE_CLIENT
--     REMOVE PROGRAMMATIC ACCESS TOKEN IF EXISTS RELAY_REFERENCE_PROOF_1DAY;
-- REVOKE ROLE RELAY_REFERENCE_READER FROM USER RELAY_REFERENCE_CLIENT;
-- ALTER WAREHOUSE RELAY_REFERENCE_WH SUSPEND;
-- Verify warehouse suspension and account usage; retain unresolved spending holds.
-- Keep the restrictive user policy in place. No database/table deletion is proposed.

-- Official syntax references, checked 2026-09-26:
-- https://docs.snowflake.com/en/sql-reference/sql/create-network-rule
-- https://docs.snowflake.com/en/sql-reference/sql/create-network-policy
-- https://docs.snowflake.com/en/sql-reference/sql/create-user
-- https://docs.snowflake.com/en/sql-reference/sql/create-role
-- https://docs.snowflake.com/en/sql-reference/sql/grant-privilege
-- https://docs.snowflake.com/en/sql-reference/sql/grant-role
-- https://docs.snowflake.com/en/sql-reference/sql/alter-user
-- https://docs.snowflake.com/en/sql-reference/sql/alter-user-add-programmatic-access-token
-- https://docs.snowflake.com/en/sql-reference/sql/alter-user-remove-programmatic-access-token
-- https://docs.snowflake.com/en/sql-reference/sql/revoke-role
-- https://docs.snowflake.com/en/sql-reference/sql/alter-warehouse
-- https://docs.snowflake.com/en/user-guide/programmatic-access-tokens
-- https://docs.snowflake.com/en/user-guide/security-access-control-overview
