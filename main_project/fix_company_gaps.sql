-- fix_company_gaps.sql
-- Closes the three gaps found by test_tables.sql. Run as postgres.
--
--  1. tasks     : an UNASSIGNED task could be reached by the admin of ANY company.
--                 Now it is reachable only through its project's company. A task with no
--                 project and no assignee cannot be reached through the chat at all.
--  2. assets    : same problem, but assets have no company link at all (no department or
--                 project column). Unassigned assets can no longer be created or changed
--                 through the chat. Assign the asset to a person instead.
--                 (To allow them again you would add an org/department column to assets.)
--  3. audit_log : an admin could read the audit entries of EVERY company. Now an admin reads
--                 only entries made by people of their own company, plus entries where the
--                 person could not be identified (actor_id is empty).
BEGIN;

DROP POLICY IF EXISTS agent_write_org ON tasks;
CREATE POLICY agent_write_org ON tasks FOR ALL TO agent_writer
  USING (
    assigned_to IN (SELECT id FROM app_org_users())
    OR (assigned_to IS NULL AND app_is_admin()
        AND project_id IN (SELECT p.id FROM projects p JOIN department d ON d.id = p.department_id
                           WHERE d.org_id = app_org()))
  )
  WITH CHECK (
    assigned_to IN (SELECT id FROM app_org_users())
    OR (assigned_to IS NULL AND app_is_admin()
        AND project_id IN (SELECT p.id FROM projects p JOIN department d ON d.id = p.department_id
                           WHERE d.org_id = app_org()))
  );

DROP POLICY IF EXISTS agent_write_org ON assets;
CREATE POLICY agent_write_org ON assets FOR ALL TO agent_writer
  USING (assigned_to IN (SELECT id FROM app_org_users()))
  WITH CHECK (assigned_to IN (SELECT id FROM app_org_users()));

DROP POLICY IF EXISTS agent_read_scope ON audit_log;
CREATE POLICY agent_read_scope ON audit_log FOR SELECT TO agent_reader
  USING (app_is_admin() AND (actor_id IS NULL OR actor_id IN (SELECT id FROM app_org_users())));

COMMIT;