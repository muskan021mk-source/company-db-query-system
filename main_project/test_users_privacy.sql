-- test_users_privacy.sql  (run as postgres, after users_privacy.sql)
-- Builds a tiny second company inside a transaction, tests the privacy rule, ROLLS BACK.
-- Your real data is only read.

BEGIN;

CREATE TEMP TABLE r (test text, status text, detail text);

-- run a query as a database role + user id; returns the single value as text,
-- or 'err:<sqlstate>' if the query failed
CREATE FUNCTION pg_temp.as_val(role_name text, actor int, q text) RETURNS text
LANGUAGE plpgsql AS $f$
DECLARE v text;
BEGIN
  EXECUTE format('SET LOCAL ROLE %I', role_name);
  PERFORM set_config('app.user_id', COALESCE(actor::text, ''), true);
  EXECUTE q INTO v;
  RESET ROLE;
  RETURN v;
EXCEPTION WHEN OTHERS THEN
  RESET ROLE;
  RETURN 'err:' || SQLSTATE;
END $f$;

CREATE FUNCTION pg_temp.rec(t text, ok boolean, d text) RETURNS void
LANGUAGE sql AS $f$ INSERT INTO r VALUES (t, CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END, d) $f$;

DO $main$
DECLARE
  admin1 int := (SELECT id FROM users WHERE is_hr_admin AND is_active AND id < 9000 ORDER BY id LIMIT 1);
  leaf   int := (SELECT u.id FROM users u WHERE u.is_active AND NOT u.is_hr_admin AND u.id < 9000
                   AND NOT EXISTS (SELECT 1 FROM users x WHERE x.manager_id = u.id) ORDER BY u.id LIMIT 1);
  mgr    int := (SELECT u.id FROM users u WHERE u.is_active AND NOT u.is_hr_admin AND u.id < 9000
                   AND EXISTS (SELECT 1 FROM users x WHERE x.manager_id = u.id) ORDER BY u.id LIMIT 1);
  actor int;
  rn text;
  q text;
  v text;
  expn bigint;
  is_adm boolean;
BEGIN
  IF admin1 IS NULL OR leaf IS NULL OR mgr IS NULL THEN
    PERFORM pg_temp.rec('setup: need an admin, a manager and an employee without reports', false, '');
    RETURN;
  END IF;

  -- fake company 2
  INSERT INTO organization (id, name) VALUES (9001, 'TEST_ORG2');
  INSERT INTO department (id, name, org_id) VALUES (9001, 'TEST_DEPT2', 9001);
  INSERT INTO role (id, title, department_id, seniority) VALUES (9001, 'TEST_ROLE2', 9001, 1);
  INSERT INTO users (id, name, email, role_id, department_id, joined_at, is_active, is_hr_admin)
    VALUES (9001, 'T Admin2', 't9001@example.invalid', 9001, 9001, current_date, true, true),
           (9002, 'T Staff2', 't9002@example.invalid', 9001, 9001, current_date, true, false);

  -- 1. sensitive columns on users are refused (permission denied = 42501), for both roles
  FOREACH rn IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
    FOREACH actor IN ARRAY ARRAY[admin1, mgr, leaf] LOOP
      FOREACH q IN ARRAY ARRAY[
        'SELECT count(email) FROM users',
        'SELECT count(manager_id) FROM users',
        'SELECT count(is_hr_admin) FROM users',
        'SELECT count(deactivated_by) FROM users',
        'SELECT count(deactivated_at) FROM users',
        'SELECT count(*) FROM (SELECT * FROM users) x'
      ] LOOP
        v := pg_temp.as_val(rn, actor, q);
        PERFORM pg_temp.rec(format('%s, user %s: refused  [%s]', rn, actor, q), v = 'err:42501', v);
      END LOOP;
    END LOOP;
  END LOOP;

  -- 2. safe columns still show the whole company
  FOREACH rn IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
    FOREACH actor IN ARRAY ARRAY[admin1, mgr, leaf, 9001] LOOP
      SELECT count(*) INTO expn FROM users u JOIN department d ON d.id = u.department_id
       WHERE d.org_id = (SELECT d2.org_id FROM users u2 JOIN department d2 ON d2.id = u2.department_id WHERE u2.id = actor);
      v := pg_temp.as_val(rn, actor, 'SELECT count(name) FROM users');
      PERFORM pg_temp.rec(format('%s, user %s: sees every colleague''s name in own company', rn, actor), v = expn::text,
                          format('expected %s, got %s', expn, v));
    END LOOP;
  END LOOP;

  -- 3. users_private shows exactly: own row / own + reports / whole company
  FOREACH actor IN ARRAY ARRAY[admin1, mgr, leaf, 9001] LOOP
    SELECT is_hr_admin INTO is_adm FROM users WHERE id = actor;
    IF is_adm THEN
      SELECT count(*) INTO expn FROM users u JOIN department d ON d.id = u.department_id
       WHERE d.org_id = (SELECT d2.org_id FROM users u2 JOIN department d2 ON d2.id = u2.department_id WHERE u2.id = actor);
    ELSE
      WITH RECURSIVE sub AS (
        SELECT id FROM users WHERE id = actor
        UNION SELECT u.id FROM users u JOIN sub s ON u.manager_id = s.id)
      SELECT count(*) INTO expn FROM sub;
    END IF;
    FOREACH rn IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
      v := pg_temp.as_val(rn, actor, 'SELECT count(*) FROM users_private');
      PERFORM pg_temp.rec(format('%s, user %s: users_private shows exactly the right people', rn, actor), v = expn::text,
                          format('expected %s, got %s', expn, v));
    END LOOP;
  END LOOP;

  -- 4. an employee sees no one else's email
  v := pg_temp.as_val('agent_reader', leaf, format('SELECT count(*) FROM users_private WHERE id <> %s', leaf));
  PERFORM pg_temp.rec('employee cannot see any other row of users_private', v = '0', v);

  -- 5. company wall on the view
  v := pg_temp.as_val('agent_reader', admin1, 'SELECT count(*) FROM users_private WHERE id IN (9001, 9002)');
  PERFORM pg_temp.rec('admin of company 1 cannot see company 2 in users_private', v = '0', v);
  v := pg_temp.as_val('agent_reader', 9001, 'SELECT count(*) FROM users_private WHERE id < 9000');
  PERFORM pg_temp.rec('admin of company 2 cannot see company 1 in users_private', v = '0', v);

  -- 6. no identity sees nothing
  FOREACH rn IN ARRAY ARRAY['agent_reader', 'agent_writer'] LOOP
    v := pg_temp.as_val(rn, NULL, 'SELECT count(*) FROM users_private');
    PERFORM pg_temp.rec(rn || ': no identity sees nothing in users_private', v = '0', v);
  END LOOP;

  -- 7. the view cannot be written through
  v := pg_temp.as_val('agent_writer', admin1, 'WITH x AS (UPDATE users_private SET email = email WHERE false RETURNING 1) SELECT count(*) FROM x');
  PERFORM pg_temp.rec('agent_writer cannot UPDATE users_private', v = 'err:42501', v);

  -- 8. the backend role is not affected
  v := pg_temp.as_val('app_agent', NULL, 'SELECT count(email) FROM users');
  PERFORM pg_temp.rec('backend app_agent can still read email (control)', v NOT LIKE 'err:%', v);
END
$main$;

SELECT count(*) FILTER (WHERE status = 'PASS') AS passed,
       count(*) FILTER (WHERE status = 'FAIL') AS failed
FROM r;

SELECT test, status, detail FROM r WHERE status <> 'PASS' ORDER BY test;

ROLLBACK;