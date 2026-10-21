-- fix_users_writer.sql
-- Removes any table-level OR column-level privilege on users from the two chat roles,
-- then gives back read-only access. (Revoking on the table also removes column grants.)
-- The app's own employee tools use the separate app_agent role, which is not touched.
BEGIN;
REVOKE ALL ON users FROM agent_writer, agent_reader;
GRANT SELECT ON users TO agent_writer, agent_reader;
COMMIT;