-- users_privacy.sql  (run as postgres)
--
-- Goal: regular people can still see colleagues' name, department, role, join date and
-- active flag, but NOT email, manager_id, is_hr_admin, deactivated_at, deactivated_by.
-- Those come only from the view users_private, which shows:
--   * a regular employee: only their own row
--   * a manager: their own row and everyone below them
--   * an HR/admin: everyone in their own company
-- The backend role (app_agent) is not affected.
--
-- OPTIONAL CHECK BEFORE RUNNING: policies on other tables that read users columns directly
-- (not through the app_* functions) would break. This should return 0 rows:
--   SELECT tablename, policyname FROM pg_policies
--   WHERE tablename <> 'users' AND (qual ILIKE '%users%' OR with_check ILIKE '%users%');

BEGIN;

-- 1. the filtered view with the sensitive columns
DROP VIEW IF EXISTS users_private;
CREATE VIEW users_private WITH (security_barrier = true) AS
SELECT id, name, email, manager_id, is_hr_admin, deactivated_at, deactivated_by
FROM users
WHERE id IN (SELECT id FROM app_scope_users())
  AND id IN (SELECT id FROM app_org_users());   -- company wall, kept as a second lock

REVOKE ALL ON users_private FROM PUBLIC;
GRANT SELECT ON users_private TO agent_reader, agent_writer;

-- 2. the AI's roles can read only the safe columns of users itself
REVOKE SELECT ON users FROM agent_reader, agent_writer;
GRANT SELECT (id, name, role_id, department_id, joined_at, is_active)
  ON users TO agent_reader, agent_writer;

COMMIT;

-- ------------------------------------------------------------------
-- UNDO (run this if something breaks):
--   BEGIN;
--   DROP VIEW IF EXISTS users_private;
--   GRANT SELECT ON users TO agent_reader, agent_writer;
--   COMMIT;
-- ------------------------------------------------------------------