-- test_tables.sql
-- Checks the permissions of ALL 15 tables, one by one, at the DATABASE level.
-- Run as postgres:   psql -U postgres -d company_db -f test_tables.sql
-- (or paste the whole file into psql).
--
-- It builds a second fake company (ids 9001+) inside a transaction, tests every table
-- as the app's database roles, prints one result line per table, and ROLLS BACK.
-- Nothing is saved. Your real data is only read.
--
-- Actors used (picked automatically from your data):
--   admin1  = an active HR/admin          mgr = a non-admin who has reports
--   leaf    = a non-admin with no reports 9001 = admin of the fake company 2

BEGIN;

CREATE TEMP TABLE results (grp text, test text, status text, detail text);

CREATE FUNCTION pg_temp.rec(g text, t text, s text, d text DEFAULT '') RETURNS void
LANGUAGE sql AS $f$ INSERT INTO results VALUES (g, t, s, d) $f$;

CREATE FUNCTION pg_temp.try(q text) RETURNS text LANGUAGE plpgsql AS $f$
BEGIN EXECUTE q; RETURN 'ok'; EXCEPTION WHEN OTHERS THEN RETURN 'err:' || SQLERRM; END $f$;

-- run a count as a database role + user id; -1 means the query errored
CREATE FUNCTION pg_temp.as_count(r text, actor int, q text) RETURNS bigint LANGUAGE plpgsql AS $f$
DECLARE n bigint;
BEGIN
  EXECUTE format('SET LOCAL ROLE %I', r);
  PERFORM set_config('app.user_id', COALESCE(actor::text, ''), true);
  EXECUTE q INTO n;
  RESET ROLE;
  RETURN n;
EXCEPTION WHEN OTHERS THEN
  RESET ROLE;
  RETURN -1;
END $f$;

-- run a statement as a database role + user id; returns 'ok:<rows>' or 'err:<sqlstate>:<message>'
CREATE FUNCTION pg_temp.as_exec(r text, actor int, q text) RETURNS text LANGUAGE plpgsql AS $f$
DECLARE n bigint;
BEGIN
  EXECUTE format('SET LOCAL ROLE %I', r);
  PERFORM set_config('app.user_id', COALESCE(actor::text, ''), true);
  EXECUTE q;
  GET DIAGNOSTICS n = ROW_COUNT;
  RESET ROLE;
  RETURN 'ok:' || n;
EXCEPTION WHEN OTHERS THEN
  RESET ROLE;
  RETURN 'err:' || SQLSTATE || ':' || SQLERRM;
END $f$;

CREATE FUNCTION pg_temp.j_err(r text) RETURNS text LANGUAGE sql AS $f$
  SELECT CASE WHEN r LIKE 'err:42501%' THEN 'PASS' WHEN r LIKE 'ok:%' THEN 'FAIL' ELSE 'INCONCLUSIVE' END $f$;
CREATE FUNCTION pg_temp.j_zero(r text) RETURNS text LANGUAGE sql AS $f$
  SELECT CASE WHEN r = 'ok:0' THEN 'PASS' WHEN r LIKE 'ok:%' THEN 'FAIL' ELSE 'INCONCLUSIVE' END $f$;
CREATE FUNCTION pg_temp.j_ok(r text) RETURNS text LANGUAGE sql AS $f$
  SELECT CASE WHEN r LIKE 'ok:%' THEN 'PASS' ELSE 'FAIL' END $f$;
CREATE FUNCTION pg_temp.j_eq(a bigint, b bigint) RETURNS text LANGUAGE sql AS $f$
  SELECT CASE WHEN a = b THEN 'PASS' ELSE 'FAIL' END $f$;

CREATE FUNCTION pg_temp.org_of_sql(actor int) RETURNS text LANGUAGE sql AS $f$
  SELECT format('(SELECT d2.org_id FROM users u2 JOIN department d2 ON d2.id = u2.department_id WHERE u2.id = %s)', actor) $f$;
CREATE FUNCTION pg_temp.orgusers_sql(actor int) RETURNS text LANGUAGE sql AS $f$
  SELECT format('SELECT u.id FROM users u JOIN department d ON d.id = u.department_id WHERE d.org_id = %s', pg_temp.org_of_sql(actor)) $f$;
CREATE FUNCTION pg_temp.scope_sql(actor int) RETURNS text LANGUAGE plpgsql AS $f$
DECLARE adm boolean;
BEGIN
  SELECT is_hr_admin INTO adm FROM users WHERE id = actor;
  IF adm THEN RETURN pg_temp.orgusers_sql(actor); END IF;
  RETURN format('WITH RECURSIVE sub AS (SELECT id FROM users WHERE id = %s UNION SELECT u.id FROM users u JOIN sub s ON u.manager_id = s.id) SELECT id FROM sub', actor);
END $f$;

DO $main$
DECLARE
  admin1 int := (SELECT id FROM users WHERE is_hr_admin AND is_active AND id < 9000 ORDER BY id LIMIT 1);
  leaf   int := (SELECT u.id FROM users u WHERE u.is_active AND NOT u.is_hr_admin AND u.id < 9000
                   AND NOT EXISTS (SELECT 1 FROM users r WHERE r.manager_id = u.id) ORDER BY u.id LIMIT 1);
  mgr    int := (SELECT u.id FROM users u WHERE u.is_active AND NOT u.is_hr_admin AND u.id < 9000
                   AND EXISTS (SELECT 1 FROM users r WHERE r.manager_id = u.id) ORDER BY u.id LIMIT 1);
  tbl record;
  actor int;
  rolename text;
  n bigint;
  expq text;
  expn bigint;
  res text;
  seed text;
  actors int[];
BEGIN
  IF admin1 IS NULL OR leaf IS NULL THEN
    PERFORM pg_temp.rec('setup', 'find test users', 'FAIL', 'need at least one active admin and one active non-admin without reports');
    RETURN;
  END IF;
  PERFORM pg_temp.rec('setup', 'actors', 'INFO', format('admin1=%s manager=%s leaf=%s', admin1, mgr, leaf));

  -- ---------- a second fake company ----------
  -- every step is checked; if your tables need other values, the test stops with a clear message
  FOREACH seed IN ARRAY ARRAY[
    $q$INSERT INTO organization (id, name) VALUES (9001, 'TEST_ORG2')$q$,
    $q$INSERT INTO department (id, name, org_id) VALUES (9001, 'TEST_DEPT2', 9001)$q$,
    $q$INSERT INTO role (id, title, department_id, seniority) VALUES (9001, 'TEST_ROLE2', 9001, 1)$q$,
    $q$INSERT INTO users (id, name, email, role_id, department_id, joined_at, is_active, is_hr_admin)
         VALUES (9001, 'T Admin2', 't9001@example.invalid', 9001, 9001, current_date, true, true)$q$,
    $q$INSERT INTO users (id, name, email, role_id, department_id, joined_at, is_active, is_hr_admin)
         VALUES (9002, 'T Staff2', 't9002@example.invalid', 9001, 9001, current_date, true, false)$q$,
    $q$INSERT INTO projects (id, name, department_id, status) VALUES (9001, 'TEST_PROJ2', 9001, 'active')$q$
  ] LOOP
    res := pg_temp.try(seed);
    IF res <> 'ok' THEN
      PERFORM pg_temp.rec('setup', 'create the fake company 2', 'FAIL', res || '  <-- while running: ' || left(regexp_replace(seed, '\s+', ' ', 'g'), 90));
      RETURN;
    END IF;
  END LOOP;
  res := pg_temp.try($q$INSERT INTO audit_log (actor_id, action, table_name, status) VALUES (9001, 'TEST', 'x', 'success')$q$);

  actors := ARRAY[admin1, mgr, leaf, 9001];

  -- =====================================================================
  -- tables whose rows belong to a person
  -- =====================================================================
  FOR tbl IN SELECT * FROM (VALUES
    ('tasks',               'assigned_to',  $s$INSERT INTO tasks (title, assigned_to, status) VALUES ('TEST', 9002, 'pending')$s$),
    ('assets',              'assigned_to',  $s$INSERT INTO assets (asset_type, asset_name, assigned_to, status) VALUES ('Laptop', 'TEST', 9002, 'assigned')$s$),
    ('attendance',          'user_id',      $s$INSERT INTO attendance (user_id, date, status) VALUES (9002, current_date, 'present')$s$),
    ('leave_requests',      'user_id',      $s$INSERT INTO leave_requests (user_id, start_date, end_date, status) VALUES (9002, current_date, current_date, 'pending')$s$),
    ('leave_schedule',      'user_id',      $s$INSERT INTO leave_schedule (user_id, day_of_week, is_recurring) VALUES (9002, 'Friday', true)$s$),
    ('expenses',            'submitted_by', $s$INSERT INTO expenses (submitted_by, department_id, category, amount, status) VALUES (9002, 9001, 'x', 1, 'pending')$s$),
    ('orders',              'requested_by', $s$INSERT INTO orders (item_name, requested_by, department_id, quantity, status) VALUES ('x', 9002, 9001, 1, 'pending')$s$),
    ('performance_reviews', 'user_id',      $s$INSERT INTO performance_reviews (user_id, reviewer_id, review_period, rating) VALUES (9002, 9001, '2026', 3)$s$),
    ('announcements',       'posted_by',    $s$INSERT INTO announcements (title, content, posted_by, department_id) VALUES ('TEST', 'x', 9002, 9001)$s$)
  ) v(t, c, seed)
  LOOP
    seed := tbl.seed;
    -- make sure there is a company-2 row to try to reach
    EXECUTE format('SELECT count(*) FROM %I WHERE %I IN (9001, 9002)', tbl.t, tbl.c) INTO n;
    IF n = 0 THEN
      res := pg_temp.try(seed);
      EXECUTE format('SELECT count(*) FROM %I WHERE %I IN (9001, 9002)', tbl.t, tbl.c) INTO n;
    END IF;
    IF n = 0 THEN
      PERFORM pg_temp.rec(tbl.t, 'setup', 'SKIPPED', 'could not create a company-2 test row: ' || COALESCE(res, ''));
      CONTINUE;
    END IF;

    -- 1. company 1 cannot see company 2 (reader and writer)
    FOREACH rolename IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
      n := pg_temp.as_count(rolename, admin1, format('SELECT count(*) FROM %I WHERE %I IN (9001, 9002)', tbl.t, tbl.c));
      PERFORM pg_temp.rec(tbl.t, rolename || ': admin of company 1 cannot see company 2 rows',
                          CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
      n := pg_temp.as_count(rolename, 9001, format('SELECT count(*) FROM %I WHERE %I NOT IN (9001, 9002)', tbl.t, tbl.c));
      PERFORM pg_temp.rec(tbl.t, rolename || ': admin of company 2 cannot see company 1 rows',
                          CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
    END LOOP;

    -- 2. no identity -> no rows
    FOREACH rolename IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
      n := pg_temp.as_count(rolename, NULL, format('SELECT count(*) FROM %I', tbl.t));
      PERFORM pg_temp.rec(tbl.t, rolename || ': no identity sees nothing', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
    END LOOP;

    -- 3. exactly the rows each person is allowed to see (reader)
    FOREACH actor IN ARRAY actors LOOP
      CONTINUE WHEN actor IS NULL;
      IF tbl.t = 'announcements' THEN
        expq := format('SELECT count(*) FROM announcements WHERE posted_by IN (%s)', pg_temp.orgusers_sql(actor));
      ELSE
        expq := format('SELECT count(*) FROM %I WHERE %I IN (%s)%s', tbl.t, tbl.c, pg_temp.scope_sql(actor),
                       CASE WHEN tbl.t = 'performance_reviews' THEN format(' OR reviewer_id = %s', actor) ELSE '' END);
      END IF;
      EXECUTE expq INTO expn;
      n := pg_temp.as_count('agent_reader', actor, format('SELECT count(*) FROM %I', tbl.t));
      PERFORM pg_temp.rec(tbl.t, format('reader: user %s sees exactly the rows they should', actor),
                          pg_temp.j_eq(n, expn), format('expected %s, saw %s', expn, n));
    END LOOP;

    -- 4. writes
    res := pg_temp.as_exec('agent_writer', admin1, format('UPDATE %I SET %I = %I WHERE %I IN (9001, 9002)', tbl.t, tbl.c, tbl.c, tbl.c));
    PERFORM pg_temp.rec(tbl.t, 'writer: admin of company 1 cannot UPDATE company 2 rows', pg_temp.j_zero(res), res);
    res := pg_temp.as_exec('agent_writer', 9001, format('UPDATE %I SET %I = %I WHERE %I NOT IN (9001, 9002)', tbl.t, tbl.c, tbl.c, tbl.c));
    PERFORM pg_temp.rec(tbl.t, 'writer: admin of company 2 cannot UPDATE company 1 rows', pg_temp.j_zero(res), res);
    res := pg_temp.as_exec('agent_writer', admin1, seed);
    PERFORM pg_temp.rec(tbl.t, 'writer: admin of company 1 cannot INSERT a company 2 row', pg_temp.j_err(res), res);
    res := pg_temp.as_exec('agent_writer', admin1, format('DELETE FROM %I WHERE false', tbl.t));
    PERFORM pg_temp.rec(tbl.t, 'writer: DELETE is not allowed', pg_temp.j_err(res), res);
    res := pg_temp.as_exec('agent_reader', admin1, format('UPDATE %I SET %I = %I WHERE false', tbl.t, tbl.c, tbl.c));
    PERFORM pg_temp.rec(tbl.t, 'reader: UPDATE is not allowed', pg_temp.j_err(res), res);
    res := pg_temp.as_exec('agent_writer', NULL, format('UPDATE %I SET %I = %I', tbl.t, tbl.c, tbl.c));
    PERFORM pg_temp.rec(tbl.t, 'writer: no identity cannot UPDATE anything', pg_temp.j_zero(res), res);
  END LOOP;

  -- unassigned tasks / assets must not be shared between companies
  FOR tbl IN SELECT * FROM (VALUES ('tasks', 'title', $s$INSERT INTO tasks (title, assigned_to, status) VALUES ('TEST-NULL', NULL, 'pending')$s$),
                                   ('assets', 'asset_name', $s$INSERT INTO assets (asset_type, asset_name, assigned_to, status) VALUES ('Laptop', 'TEST-NULL', NULL, 'assigned')$s$)) v(t, c, seed)
  LOOP
    res := pg_temp.try(tbl.seed);
    n := pg_temp.as_count('agent_writer', 9001, format('SELECT count(*) FROM %I WHERE %I = ''TEST-NULL''', tbl.t, tbl.c));
    PERFORM pg_temp.rec(tbl.t, 'writer: admin of company 2 cannot touch UNASSIGNED rows of company 1',
                        CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n || ' unassigned row(s) (they cannot be tied to a company)');
  END LOOP;

  -- unassigned tasks that belong to a project: only the project's own company may reach them
  res := pg_temp.try($s$INSERT INTO tasks (title, assigned_to, project_id, status) VALUES ('TEST-NULL-P2', NULL, 9001, 'pending')$s$);
  n := pg_temp.as_count('agent_writer', 9001, 'SELECT count(*) FROM tasks WHERE title = ''TEST-NULL-P2''');
  PERFORM pg_temp.rec('tasks', 'writer: admin of company 2 CAN reach unassigned tasks of its OWN project (control)',
                      CASE WHEN n = 1 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
  n := pg_temp.as_count('agent_writer', admin1, 'SELECT count(*) FROM tasks WHERE title = ''TEST-NULL-P2''');
  PERFORM pg_temp.rec('tasks', 'writer: admin of company 1 cannot reach unassigned tasks of company 2 projects',
                      CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);

  -- =====================================================================
  -- company structure tables
  -- =====================================================================
  FOR tbl IN SELECT * FROM (VALUES
    ('users',        'id IN (9001, 9002)',     'SELECT count(*) FROM users WHERE department_id IN (SELECT id FROM department WHERE org_id = %s)'),
    ('department',   'org_id = 9001',          'SELECT count(*) FROM department WHERE org_id = %s'),
    ('role',         'department_id = 9001',   'SELECT count(*) FROM role WHERE department_id IN (SELECT id FROM department WHERE org_id = %s)'),
    ('organization', 'id = 9001',              'SELECT count(*) FROM organization WHERE id = %s'),
    ('projects',     'department_id = 9001',   'SELECT count(*) FROM projects WHERE department_id IN (SELECT id FROM department WHERE org_id = %s)')
  ) v(t, cond, expfmt)
  LOOP
    FOREACH rolename IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
      n := pg_temp.as_count(rolename, admin1, format('SELECT count(*) FROM %I WHERE %s', tbl.t, tbl.cond));
      PERFORM pg_temp.rec(tbl.t, rolename || ': admin of company 1 cannot see company 2 rows', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
      n := pg_temp.as_count(rolename, NULL, format('SELECT count(*) FROM %I', tbl.t));
      PERFORM pg_temp.rec(tbl.t, rolename || ': no identity sees nothing', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
    END LOOP;
    n := pg_temp.as_count('agent_reader', 9001, format('SELECT count(*) FROM %I WHERE NOT (%s)', tbl.t, tbl.cond));
    PERFORM pg_temp.rec(tbl.t, 'reader: admin of company 2 cannot see company 1 rows', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);

    FOREACH actor IN ARRAY actors LOOP
      CONTINUE WHEN actor IS NULL;
      EXECUTE format(tbl.expfmt, pg_temp.org_of_sql(actor)) INTO expn;
      n := pg_temp.as_count('agent_reader', actor, format('SELECT count(*) FROM %I', tbl.t));
      PERFORM pg_temp.rec(tbl.t, format('reader: user %s sees exactly their own company', actor), pg_temp.j_eq(n, expn), format('expected %s, saw %s', expn, n));
    END LOOP;

    res := pg_temp.as_exec('agent_writer', admin1, format('DELETE FROM %I WHERE false', tbl.t));
    PERFORM pg_temp.rec(tbl.t, 'writer: DELETE is not allowed', pg_temp.j_err(res), res);
  END LOOP;

  -- users: nobody can write it through the chat roles, nobody can touch the admin flag
  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE users SET name = name WHERE false');
  PERFORM pg_temp.rec('users', 'writer: UPDATE is not allowed', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('agent_reader', admin1, 'UPDATE users SET name = name WHERE false');
  PERFORM pg_temp.rec('users', 'reader: UPDATE is not allowed', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO users (name) VALUES (''x'')');
  PERFORM pg_temp.rec('users', 'writer: INSERT is not allowed', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('app_agent', NULL, 'UPDATE users SET is_hr_admin = is_hr_admin WHERE false');
  PERFORM pg_temp.rec('users', 'backend: cannot UPDATE is_hr_admin', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('app_agent', NULL, 'INSERT INTO users (name, is_hr_admin) VALUES (''x'', true)');
  PERFORM pg_temp.rec('users', 'backend: cannot INSERT is_hr_admin', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('app_agent', NULL, 'UPDATE users SET name = name WHERE false');
  PERFORM pg_temp.rec('users', 'backend: can UPDATE allowed columns (control)', pg_temp.j_ok(res), res);

  -- department / role / organization / projects: company 1 cannot change company 2
  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE department SET name = name WHERE org_id = 9001');
  PERFORM pg_temp.rec('department', 'writer: cannot UPDATE company 2 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', 9001, 'UPDATE department SET name = name WHERE org_id <> 9001');
  PERFORM pg_temp.rec('department', 'writer: admin of company 2 cannot UPDATE company 1 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO department (id, name, org_id) VALUES (9100, ''x'', 9001)');
  PERFORM pg_temp.rec('department', 'writer: cannot INSERT into company 2', pg_temp.j_err(res), res);

  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE role SET title = title WHERE department_id = 9001');
  PERFORM pg_temp.rec('role', 'writer: cannot UPDATE company 2 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', 9001, 'UPDATE role SET title = title WHERE department_id <> 9001');
  PERFORM pg_temp.rec('role', 'writer: admin of company 2 cannot UPDATE company 1 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO role (id, title, department_id, seniority) VALUES (9100, ''x'', 9001, 1)');
  PERFORM pg_temp.rec('role', 'writer: cannot INSERT into company 2', pg_temp.j_err(res), res);

  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE organization SET name = name WHERE id = 9001');
  PERFORM pg_temp.rec('organization', 'writer: cannot UPDATE company 2', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', 9001, 'UPDATE organization SET name = name WHERE id <> 9001');
  PERFORM pg_temp.rec('organization', 'writer: admin of company 2 cannot UPDATE company 1', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO organization (id, name) VALUES (9100, ''x'')');
  PERFORM pg_temp.rec('organization', 'writer: INSERT is not allowed', pg_temp.j_err(res), res);

  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE projects SET name = name WHERE department_id = 9001');
  PERFORM pg_temp.rec('projects', 'writer: cannot UPDATE company 2 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', 9001, 'UPDATE projects SET name = name WHERE department_id <> 9001');
  PERFORM pg_temp.rec('projects', 'writer: admin of company 2 cannot UPDATE company 1 rows', pg_temp.j_zero(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO projects (id, name, department_id, status) VALUES (9100, ''x'', 9001, ''active'')');
  PERFORM pg_temp.rec('projects', 'writer: cannot INSERT into company 2', pg_temp.j_err(res), res);

  -- =====================================================================
  -- audit_log
  -- =====================================================================
  n := pg_temp.as_count('agent_reader', leaf, 'SELECT count(*) FROM audit_log');
  PERFORM pg_temp.rec('audit_log', 'reader: a regular employee sees nothing', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
  n := pg_temp.as_count('agent_reader', NULL, 'SELECT count(*) FROM audit_log');
  PERFORM pg_temp.rec('audit_log', 'reader: no identity sees nothing', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
  n := pg_temp.as_count('agent_writer', admin1, 'SELECT count(*) FROM audit_log');
  PERFORM pg_temp.rec('audit_log', 'writer: cannot read the log back', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
  n := pg_temp.as_count('agent_reader', admin1, 'SELECT count(*) FROM audit_log');
  PERFORM pg_temp.rec('audit_log', 'reader: admin can read the log', CASE WHEN n > 0 THEN 'PASS' ELSE 'FAIL' END, 'saw ' || n);
  n := pg_temp.as_count('agent_reader', admin1, 'SELECT count(*) FROM audit_log WHERE actor_id = 9001');
  PERFORM pg_temp.rec('audit_log', 'admin of company 1 sees company 2 audit entries', CASE WHEN n = 0 THEN 'PASS' ELSE 'FAIL' END,
                      'saw ' || n || ' (the log has no company column, so admins see every company''s entries)');
  res := pg_temp.as_exec('agent_writer', admin1, 'INSERT INTO audit_log (action, table_name, status) VALUES (''T'', ''t'', ''success'')');
  PERFORM pg_temp.rec('audit_log', 'writer: can append entries (control)', pg_temp.j_ok(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'UPDATE audit_log SET action = action WHERE false');
  PERFORM pg_temp.rec('audit_log', 'writer: cannot edit entries', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('agent_writer', admin1, 'DELETE FROM audit_log WHERE false');
  PERFORM pg_temp.rec('audit_log', 'writer: cannot delete entries', pg_temp.j_err(res), res);
  res := pg_temp.as_exec('agent_reader', admin1, 'INSERT INTO audit_log (action, table_name, status) VALUES (''T'', ''t'', ''success'')');
  PERFORM pg_temp.rec('audit_log', 'reader: cannot write entries', pg_temp.j_err(res), res);
END
$main$;

-- ---- results ----
SELECT grp AS "table",
       count(*) FILTER (WHERE status = 'PASS')                               AS passed,
       count(*) FILTER (WHERE status = 'FAIL')                               AS failed,
       count(*) FILTER (WHERE status IN ('SKIPPED', 'INCONCLUSIVE'))         AS unclear
FROM results WHERE grp <> 'setup' GROUP BY grp ORDER BY grp;

SELECT grp AS "table", test, status, detail
FROM results WHERE status NOT IN ('PASS', 'INFO') ORDER BY grp, test;

SELECT status, count(*) FROM results WHERE grp <> 'setup' GROUP BY status ORDER BY status;

ROLLBACK;