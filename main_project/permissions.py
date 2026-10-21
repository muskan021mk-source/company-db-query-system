"""
permissions.py - hierarchy-based access control for the agent's employee changes.

RULES
  1. The person acting must exist and be ACTIVE (checked in Postgres on every call).
  2. You can only modify people BELOW you in the reporting chain (directly or
     indirectly). Not yourself, not peers, not people above you.
  3. Changing department, role, manager or EMAIL needs the HR/admin flag
     (users.is_hr_admin), and nobody changes their own. (Email is a login identity:
     accounts are verified against it, so a manager must not be able to change it.)
     Name can be changed by people ABOVE the target (or the admin).
  4. Creating employees and reverting changes to the users table need the HR/admin
     flag (users.is_hr_admin).
  5. Nobody can deactivate themselves, someone who still has active direct reports,
     someone who still has unfinished tasks (reassign them first), someone who still
     holds company assets that were not returned, or the last active HR/admin.
  6. Nobody acts across organizations (companies), not even the admin. That includes
     the DESTINATION of a change: a person can only be moved into a department, or
     given a role, of the admin's own company, and a new employee can only be created in it.
  7. Any error, missing data or unclear case means DENIED.

The hierarchy is read from POSTGRES (users.manager_id), not Neo4j. Neo4j can lag
behind and the agent can write to it, so it must never be the source of authority.

This file also holds the SQL guard helpers used by run_sql_query.
"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MAX_CHAIN_DEPTH = 50
CHECK_TIMEOUT = "5s"      # a permission check must never hang the database

SENSITIVE_FIELDS = {"department", "role", "manager", "email"}   # admin only, never your own
ORDINARY_FIELDS = {"name"}

# Tables the agent may write to through run_sql_query. Everything else
# (users, audit_log, anything unparseable) is refused.
WRITABLE_TABLES = {
    "orders", "expenses", "leave_requests", "leave_schedule", "tasks",
    "projects", "performance_reviews", "assets", "announcements", "attendance",
    "department", "role", "organization",     # admin only, own company only (row_permissions.py)
}


# ======================================================================
# SQL guard helpers (fail closed)
# ======================================================================
_DOLLAR_RE = re.compile(r"\$\w*\$")
_TARGET_RE = re.compile(
    r'^\s*(?:UPDATE\s+(?:ONLY\s+)?|DELETE\s+FROM\s+(?:ONLY\s+)?|INSERT\s+INTO\s+)'
    r'(?:"?([a-zA-Z_]\w*)"?\s*\.\s*)?"?([a-zA-Z_]\w*)"?',
    re.IGNORECASE,
)

# One pass, left to right: whichever token starts first wins.
_TOKEN_RE = re.compile(
    "|".join([
        r"(?<![\w$])[Ee]'(?:[^'\\]|\\.|'')*'",   # E'...' strings (backslash escapes)
        r"'(?:[^']|'')*'",                        # normal '...' strings
        r'"(?:[^"]|"")*"',                        # "quoted identifiers"
        r"/\*.*?\*/",                             # block comments
        r"--[^\n]*",                              # line comments
    ]),
    re.S,
)
_UNICODE_STR_RE = re.compile(r"""(?<![\w$])[Uu]&\s*['"]""")   # U&'..' is refused outright


def _blank(m):
    t = m.group(0)
    if t[0] == '"':
        return t                       # keep identifiers so table names stay visible
    if t.startswith(("--", "/*")):
        return " "                     # comment
    return " _s_ "                     # string literal


def normalize_sql(sql: str) -> str:
    """Remove string literals and comments so only real SQL structure remains."""
    return _TOKEN_RE.sub(_blank, sql)


def is_single_statement(sql: str) -> bool:
    """True only for exactly one statement. Anything unclear returns False."""
    if _UNICODE_STR_RE.search(sql):
        return False
    s = normalize_sql(sql)
    if "'" in s or "/*" in s or _DOLLAR_RE.search(s):
        return False
    s = s.strip().rstrip(";").strip()
    return ";" not in s


def has_sql_comment(sql: str) -> bool:
    """
    True if the SQL contains a -- or /* */ comment (also an unterminated /*).
    Text inside 'strings' and "quoted names" is not a comment.
    Comments are refused because they can hide a WHERE from the permission
    checks while Postgres ignores it.
    """
    for m in _TOKEN_RE.finditer(sql):
        if m.group(0).startswith(("--", "/*")):
            return True
    rest = _TOKEN_RE.sub(" ", sql)
    return "/*" in rest or "--" in rest


def write_target_table(sql: str) -> str:
    """
    Table an INSERT/UPDATE/DELETE writes to, or "" if it can't be determined.
    Handles comments, ONLY, quoted names and schema prefixes. Only the
    public schema is accepted.
    """
    m = _TARGET_RE.match(normalize_sql(sql))
    if not m:
        return ""
    schema, table = m.groups()
    if schema and schema.lower() != "public":
        return ""
    return table.lower()


# Anything that can change data, structure or session state, or that can run SQL
# hidden inside a string (which would dodge the table-name scanning).
_NOT_READ_ONLY_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY|CALL|DO|"
    r"VACUUM|REINDEX|CLUSTER|REFRESH|LOCK|SET|RESET|EXECUTE|PREPARE|DEALLOCATE|LISTEN|"
    r"NOTIFY|INTO|COMMIT|ROLLBACK|BEGIN|SAVEPOINT|EXPLAIN|ANALYZE)\b"
    r"|\bFOR\s+(?:NO\s+KEY\s+|KEY\s+)?SHARE\b",
    re.IGNORECASE,
)
_DANGEROUS_FUNC_RE = re.compile(
    r"\b(\w*_to_xml\w*|set_config|nextval|setval|currval|lastval|dblink\w*|lo_\w+|txid_\w+|"
    r"pg_(?:read|ls|sleep|terminate|cancel|reload|stat_file|advisory|notify|logical|file|"
    r"rotate|switch|create|drop|replication|promote|backup|start|stop)\w*)\b",
    re.IGNORECASE,
)
_READ_START_RE = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)


def is_read_only_query(sql: str) -> bool:
    """
    True only for a plain read: one statement that starts with SELECT or WITH and
    contains nothing that writes, locks, changes settings, or runs SQL from a string.
    Catches the classic bypasses: WITH x AS (UPDATE ... RETURNING *) SELECT ...,
    SELECT ... INTO newtable, SELECT ... FOR UPDATE, query_to_xml('select ...').
    Unclear input returns False.
    """
    if not isinstance(sql, str) or not is_single_statement(sql):
        return False
    s = normalize_sql(sql)
    if not _READ_START_RE.match(s):
        return False
    return not (_NOT_READ_ONLY_RE.search(s) or _DANGEROUS_FUNC_RE.search(s))


# ======================================================================
# Permission checks
# ======================================================================
@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    fixable: bool = False   # True = "do this first, then try again" (not a permission problem)


def _yes() -> Decision:
    return Decision(True)


def _no(reason: str) -> Decision:
    return Decision(False, reason)


def _not_yet(reason: str) -> Decision:
    return Decision(False, reason, fixable=True)


def _to_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _user_row(cur, user_id):
    """(is_active, is_hr_admin) or None if the user doesn't exist."""
    cur.execute("SELECT is_active, is_hr_admin FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return None if row is None else (bool(row[0]), bool(row[1]))


def _ancestors(cur, user_id) -> list:
    """
    Ids of everyone above user_id: manager, manager's manager, and so on.
    Deactivated managers are included, so authority passes through them.
    Raises on a reporting loop or an absurdly deep chain (caller denies).
    """
    seen, chain, current = {user_id}, [], user_id
    for _ in range(MAX_CHAIN_DEPTH):
        cur.execute("SELECT manager_id FROM users WHERE id = %s", (current,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            return chain
        nxt = int(row[0])
        if nxt in seen:
            raise ValueError("reporting loop detected")
        seen.add(nxt)
        chain.append(nxt)
        current = nxt
    raise ValueError("reporting chain too deep")


def _org_of(cur, user_id):
    """Organization (company) a user belongs to, via their department. None if unknown."""
    cur.execute("SELECT department_id FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return _org_of_department(cur, row[0])


def _org_of_department(cur, dept_id):
    """Organization a department belongs to. None if the department is unknown."""
    if dept_id is None:
        return None
    cur.execute("SELECT org_id FROM department WHERE id = %s", (dept_id,))
    row = cur.fetchone()
    return None if row is None else row[0]


def _org_of_role(cur, role_id):
    """Organization a role belongs to (role -> department -> organization). None if unknown."""
    if role_id is None:
        return None
    cur.execute("SELECT department_id FROM role WHERE id = %s", (role_id,))
    row = cur.fetchone()
    return None if row is None else _org_of_department(cur, row[0])


def _same_org(cur, a, b) -> bool:
    org = _org_of(cur, a)
    return org is not None and org == _org_of(cur, b)


def _decide(cur, actor_id, action, target_id=None, field=None,
            new_manager_id=None, new_value=None) -> Decision:
    """
    new_value = the department id being set (update_field/department), the role id
    being set (update_field/role), or the new employee's department id (create).
    Required for those, so the DESTINATION can be checked against the admin's company.
    """
    me = _user_row(cur, actor_id)
    if me is None:
        return _no("Your account could not be found.")
    my_active, is_admin = me
    if not my_active:
        return _no("Your account is deactivated.")

    if action == "revert_users":
        return _yes() if is_admin else _no("This action requires HR/admin permission.")

    if action == "create":
        if not is_admin:
            return _no("This action requires HR/admin permission.")
        actor_org = _org_of(cur, actor_id)
        if actor_org is None:
            return _no("Your organization could not be determined.")
        dept = _to_int(new_value)
        if dept is None:
            return _no("The new employee's department could not be identified.")
        new_org = _org_of_department(cur, dept)
        if new_org is None or new_org != actor_org:
            return _no("That department belongs to another organization (or does not exist).")
        if new_manager_id is not None:
            mgr = _to_int(new_manager_id)
            mgr_row = None if mgr is None else _user_row(cur, mgr)
            if mgr_row is None or not mgr_row[0]:
                return _no("The new employee's manager must be an active employee.")
            if not _same_org(cur, actor_id, mgr):
                return _no("The new manager belongs to another organization.")
        return _yes()

    if action not in ("deactivate", "activate", "update_field"):
        return _no("Unknown action.")

    target_id = _to_int(target_id)
    if target_id is None:
        return _no("The target employee could not be identified.")
    target = _user_row(cur, target_id)
    if target is None:
        return _no("The target employee was not found.")
    _target_active, target_is_admin = target

    is_self = target_id == actor_id
    same_org = _same_org(cur, actor_id, target_id)          # nobody acts across companies
    above_target = (not is_self) and same_org and (actor_id in _ancestors(cur, target_id))
    admin_here = is_admin and same_org
    may_modify = admin_here or above_target

    if action == "deactivate":
        if is_self:
            return _no("You cannot deactivate your own account.")
        if not may_modify:
            return _no("You can only deactivate people who report to you (directly or indirectly).")
        cur.execute(
            "SELECT COUNT(*) FROM users WHERE manager_id = %s AND is_active",
            (target_id,),
        )
        if cur.fetchone()[0] > 0:
            return _not_yet("This person still has active direct reports. Reassign them to another manager first.")
        cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE assigned_to = %s AND status IS DISTINCT FROM 'done'",
            (target_id,),
        )
        open_tasks = cur.fetchone()[0]
        if open_tasks > 0:
            return _not_yet(
                f"This person still has {open_tasks} unfinished task(s). "
                "Reassign them to someone else first."
            )
        cur.execute(
            "SELECT COUNT(*) FROM assets WHERE assigned_to = %s AND returned_at IS NULL",
            (target_id,),
        )
        held_assets = cur.fetchone()[0]
        if held_assets > 0:
            return _not_yet(
                f"This person still holds {held_assets} company asset(s) that were not returned. "
                "Record the return (or reassign the asset) first."
            )
        if target_is_admin:
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE is_hr_admin AND is_active AND id <> %s",
                (target_id,),
            )
            if cur.fetchone()[0] == 0:
                return _no("This is the last active HR/admin and cannot be deactivated.")
        return _yes()

    if action == "activate":
        if not may_modify:
            return _no("You can only reactivate people who report to you (directly or indirectly).")
        return _yes()

    # action == "update_field"
    field = (field or "").lower().strip()
    if field in SENSITIVE_FIELDS:
        if not is_admin:
            return _no(f"Changing {field} requires HR/admin permission.")
        if is_self:
            return _no(f"You cannot change your own {field}.")
        if not same_org:
            return _no("That person belongs to another organization (or has none).")
        if field == "department":
            dept = _to_int(new_value)
            if dept is None:
                return _no("The new department could not be identified.")
            new_org, my_org = _org_of_department(cur, dept), _org_of(cur, actor_id)
            if new_org is None or new_org != my_org:
                return _no("That department belongs to another organization (or does not exist).")
        if field == "role":
            role = _to_int(new_value)
            if role is None:
                return _no("The new role could not be identified.")
            new_org, my_org = _org_of_role(cur, role), _org_of(cur, actor_id)
            if new_org is None or new_org != my_org:
                return _no("That role belongs to another organization (or does not exist).")
        if field == "manager":
            new_mgr = _to_int(new_manager_id)
            if new_mgr is None:
                return _no("The new manager could not be identified.")
            if new_mgr == target_id:
                return _no("An employee cannot be their own manager.")
            if not _same_org(cur, actor_id, new_mgr):
                return _no("The new manager belongs to another organization.")
            new_row = _user_row(cur, new_mgr)
            if new_row is None or not new_row[0]:
                return _no("The new manager must be an active employee.")
            if target_id in _ancestors(cur, new_mgr):
                return _no("That change would create a reporting loop.")
        return _yes()

    if field in ORDINARY_FIELDS:
        if may_modify:
            return _yes()
        return _no("You can only modify people who report to you (directly or indirectly).")

    return _no("That field cannot be changed.")


def authorize(actor_id, action, target_id=None, field=None,
              new_manager_id=None, new_value=None) -> Decision:
    """Runs the checks against Postgres. Any error means denied."""
    actor_id = _to_int(actor_id)
    if actor_id is None:
        return _no("Your identity could not be verified.")

    conn = None
    try:
        from mcp_tools import get_connection  # lazy: keeps the SQL helpers importable alone
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{CHECK_TIMEOUT}'")
            return _decide(cur, actor_id, action, target_id, field, new_manager_id, new_value)
    except Exception:
        logger.exception("Permission check failed; denying.")
        return _no("The permission check could not be completed, so the action was refused.")
    finally:
        if conn is not None:
            from mcp_tools import release_connection
            try:
                conn.rollback()
            except Exception:
                pass
            release_connection(conn)


def check(actor, thread_id, action, target_id=None, field=None,
          new_manager_id=None, new_value=None) -> Optional[str]:
    """
    Tool-facing helper. `actor` is the (user_id, user_name) tuple from agent._actor().
    Returns None if allowed, otherwise an "ERROR: Permission denied..." string
    for the tool to return, after writing the denial to the audit log.
    """
    try:
        raw_id = actor[0]
    except (TypeError, IndexError):
        raw_id = None

    decision = authorize(raw_id, action, target_id, field, new_manager_id, new_value)
    if decision.allowed:
        return None

    try:
        from mcp_tools import write_audit
        write_audit(
            actor if actor else (None, "unknown"), "DENIED", "users",
            new={"attempted": action, "target_id": target_id, "field": field,
                 "new_value": new_value, "reason": decision.reason},
            thread_id=thread_id, status="blocked",
        )
    except Exception:
        logger.exception("Could not audit a permission denial.")

    if decision.fixable:
        return (
            f"ERROR: Not possible yet. {decision.reason} Nothing was changed. "
            "Tell the user exactly what must be done first and offer to help with that step "
            "(for example reassigning the tasks). Do not deactivate anyone until it is done."
        )
    return (
        f"ERROR: Permission denied. {decision.reason} Nothing was changed. "
        "Tell the user this plainly. Do not retry or try another tool or SQL to get around it."
    )


def is_active_employee(user_id) -> bool:
    """True only if this person exists in Postgres and is still active. Any error = False."""
    uid = _to_int(user_id)
    if uid is None:
        return False
    conn = None
    try:
        from mcp_tools import get_connection
        conn = get_connection()
        with conn.cursor() as cur:
            row = _user_row(cur, uid)
        return row is not None and row[0]
    except Exception:
        logger.exception("Active-employee check failed; treating as inactive.")
        return False
    finally:
        if conn is not None:
            from mcp_tools import release_connection
            try:
                conn.rollback()
            except Exception:
                pass
            release_connection(conn)


# ======================================================================
# Undo of changes to the users table (added by patch_revert_rules.py)
# Rule: an undo is allowed when the person could make the same change
# directly right now. HR/admin keep their old behaviour.
# ======================================================================
_REVERT_USER_COLS = ["name", "email", "role_id", "department_id", "manager_id",
                     "is_active", "deactivated_at", "deactivated_by"]
_REVERT_SKIP_COLS = {"id", "is_hr_admin", "joined_at"}   # never restored by an undo
_REVERT_STATUS_COLS = {"is_active", "deactivated_at", "deactivated_by"}


def _revert_users_decision(cur, actor_id, before_rows) -> Decision:
    me = _user_row(cur, actor_id)
    if me is None:
        return _no("Your account could not be found.")
    if not me[0]:
        return _no("Your account is deactivated.")
    if me[1]:
        return _yes()                      # HR/admin: unchanged behaviour

    if not before_rows:
        return _no("There is nothing recorded to restore, so the undo was refused.")

    for snap in before_rows:
        target_id = _to_int(snap.get("id"))
        if target_id is None:
            return _no("The target employee could not be identified.")

        unknown = [c for c in snap
                   if c not in _REVERT_SKIP_COLS and c not in _REVERT_USER_COLS]
        if unknown:
            return _no("This undo would restore fields that cannot be verified, "
                       "so it was refused.")

        cur.execute("SELECT " + ", ".join(_REVERT_USER_COLS) + " FROM users WHERE id = %s",
                    (target_id,))
        row = cur.fetchone()
        if row is None:
            return _no("The target employee was not found.")
        now = dict(zip(_REVERT_USER_COLS, row))
        changed = [c for c in _REVERT_USER_COLS if c in snap and now[c] != snap[c]]

        if not changed:
            # nothing to restore: still require that you may modify this person
            d = _decide(cur, actor_id, "update_field", target_id, "name")
            if not d.allowed:
                return d
            continue

        if _REVERT_STATUS_COLS & set(changed):
            if "is_active" not in changed:
                return _no("This undo would change deactivation details only, "
                           "so it was refused.")
            action = "activate" if snap.get("is_active") else "deactivate"
            d = _decide(cur, actor_id, action, target_id)
            if not d.allowed:
                return d

        for c in changed:
            if c in _REVERT_STATUS_COLS:
                continue
            if c == "name":
                d = _decide(cur, actor_id, "update_field", target_id, "name")
            elif c == "email":
                d = _decide(cur, actor_id, "update_field", target_id, "email")
            elif c == "department_id":
                d = _decide(cur, actor_id, "update_field", target_id, "department",
                            new_value=snap[c])
            elif c == "role_id":
                d = _decide(cur, actor_id, "update_field", target_id, "role",
                            new_value=snap[c])
            elif c == "manager_id":
                d = _decide(cur, actor_id, "update_field", target_id, "manager",
                            new_manager_id=snap[c])
            else:
                d = _no("That field cannot be changed.")
            if not d.allowed:
                return d

    return _yes()


def check_revert_users(actor, thread_id, operation, before_rows) -> Optional[str]:
    """
    Tool-facing check for undoing a change to the users table.
    Returns None if allowed, otherwise an "ERROR: ..." string (same style as check()).
    """
    if operation != "UPDATE":
        # undoing a creation (or a delete) is HR/admin only, as before
        return check(actor, thread_id, "revert_users")

    try:
        raw_id = actor[0]
    except (TypeError, IndexError):
        raw_id = None
    actor_id = _to_int(raw_id)

    if actor_id is None:
        decision = _no("Your identity could not be verified.")
    else:
        conn = None
        release = None
        try:
            from mcp_tools import get_connection, release_connection
            release = release_connection
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL statement_timeout = '{CHECK_TIMEOUT}'")
                decision = _revert_users_decision(cur, actor_id, before_rows)
        except Exception:
            logger.exception("Undo permission check failed; denying.")
            decision = _no("The permission check could not be completed, "
                           "so the undo was refused.")
        finally:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                if release is not None:
                    try:
                        release(conn)
                    except Exception:
                        logger.exception("Could not release the connection.")

    if decision.allowed:
        return None

    try:
        from mcp_tools import write_audit
        write_audit(
            actor if actor else (None, "unknown"), "DENIED", "users",
            new={"attempted": "revert_users", "reason": decision.reason},
            thread_id=thread_id, status="blocked",
        )
    except Exception:
        logger.exception("Could not audit a permission denial.")

    if decision.fixable:
        return (
            f"ERROR: Not possible yet. {decision.reason} Nothing was changed. "
            "Tell the user exactly what must be done first and offer to help with that step."
        )
    return (
        f"ERROR: Permission denied. {decision.reason} Nothing was changed. "
        "Tell the user this plainly. Do not retry or try another tool or SQL to get around it."
    )
