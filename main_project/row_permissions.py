"""
row_permissions.py - rules for the OTHER tables (tasks, expenses, leave, ...).
Works together with permissions.py (same hierarchy, same "any error = denied").

WRITES (run_sql_query INSERT / UPDATE / DELETE)
  Every affected row has an "owner" (the person it is about). The rows are looked
  up in Postgres, so the rules cannot be dodged by how the SQL is written.
  * You can touch rows of people BELOW you, and (where allowed) your own rows.
  * Nobody approves/rejects their own request (expenses, leave, orders), not even
    the admin. A request you made can only be edited or cancelled while pending.
  * A DECIDED request (approved, rejected, delivered ...) is final for everybody:
    nobody can edit or delete it afterwards, not the owner, not a manager, not the admin.
  * Requests (expenses, leave, orders) are submitted by the person themselves, for
    themselves, even the admin. An approver can only change the decision (status): not
    the amount, dates or reason, and cannot delete it (reject it instead). Only the
    owner can withdraw a pending request.
  * Columns that point at a department or project (expenses, orders, announcements,
    tasks) must point inside the person's own company. Announcements go to your own
    department; company-wide ones (no department) are admin only, also when editing.
  * Performance reviews: only by someone above the person, under their own name.
  * Tasks / assets can only be handed to yourself or to people below you.
  * Announcements to the whole company (no department) and records with no owner
    are admin only. Projects: the admin, or a manager of that project's department.
  * Values in INSERT / UPDATE must be plain values. A sub-SELECT inside a value is
    refused (it could copy protected data into a table the person can read).
  * Statements this module cannot verify (joins, ON CONFLICT, odd forms) are refused.
  * Nobody acts across companies, not even the admin (organization boundary).
  * department / role / organization: admin only, own company only, never created or
    deleted through the agent (organization is rename-only).
  * audit_log: never writable by the agent (it is not in the writable list).

READS (run_sql_query SELECT)
  * audit_log: admin only.
  * performance_reviews, leave_requests, expenses: only rows of yourself and the
    people below you. The query is rewritten to enforce this. If it cannot be
    rewritten safely, it is refused. The admin sees everything.

REVERTS of changes to these tables are checked like the original change.
"""
import datetime as _dt
import logging
import re
from dataclasses import dataclass
from typing import Optional

from permissions import (
    CHECK_TIMEOUT,
    _ancestors,
    _org_of,
    _to_int,
    _user_row,
    is_single_statement,
    normalize_sql,
    write_target_table,
)

logger = logging.getLogger(__name__)

_EXPR = object()          # "this value is not a plain literal"
MAX_ROWS_CHECKED = 500
MAX_INSERT_ROWS = 50
MAX_VISIBLE = 5000


@dataclass(frozen=True)
class RowRule:
    owner: Optional[str]              # column saying whose row it is (None = no owner)
    self_edit: bool = True            # may you update/delete your OWN rows?
    self_insert: bool = True          # may you add rows for yourself?
    self_status: bool = True          # may you change the status of your OWN rows?
    self_pending_only: bool = False   # own rows editable only while status = 'pending'
    owner_change: bool = False        # may the owner column be changed (reassign)?
    locked: tuple = ()                # columns UPDATE may never change
    author: Optional[str] = None      # on INSERT this column must be YOU
    admin_if_null: Optional[str] = None   # if this column is NULL, only the admin
    scope_col: Optional[str] = None   # column that says which company/department a row belongs to
    admin_only: bool = False          # (scoped tables) only the admin; else admin or that department's manager
    no_insert: bool = False
    no_delete: bool = False
    transitions: Optional[dict] = None    # allowed status changes: {from_status: {to_status, ...}}
                                          # a status that is not a key here is FINAL
    request: bool = False             # an approval workflow: self-submit only, approvers change status only
    dept_col: Optional[str] = None    # column holding a department id that must be in your company
    dept_own_only: bool = False       # non-admins may only use their OWN department there
    project_col: Optional[str] = None # column holding a project id that must be in your company
    needs_reports: bool = False       # non-admins may only add rows if they manage people
    today_col: Optional[str] = None   # adding a row for YOURSELF: this date column must be today
    admin_delete_only: bool = False   # only the admin may delete these rows


_DECISION_FLOW = {"pending": {"approved", "rejected"}}   # decided requests are final

ROW_RULES = {
    "tasks":               RowRule("assigned_to", owner_change=True, project_col="project_id"),
    "expenses":            RowRule("submitted_by", self_status=False, self_pending_only=True,
                                   transitions=_DECISION_FLOW, request=True, dept_col="department_id"),
    "orders":              RowRule("requested_by", self_status=False, self_pending_only=True,
                                   transitions={"pending": {"approved"}, "approved": {"delivered"}},
                                   request=True, dept_col="department_id"),
    "leave_requests":      RowRule("user_id", self_status=False, self_pending_only=True,
                                   transitions=_DECISION_FLOW, request=True),
    "leave_schedule":      RowRule("user_id"),
    "attendance":          RowRule("user_id", self_edit=False, today_col="date"),
    "performance_reviews": RowRule("user_id", self_edit=False, self_insert=False,
                                   locked=("reviewer_id",), author="reviewer_id",
                                   admin_delete_only=True),
    "assets":              RowRule("assigned_to", self_edit=False, self_insert=False,
                                   owner_change=True, admin_delete_only=True),
    "announcements":       RowRule("posted_by", admin_if_null="department_id",
                                   dept_col="department_id", dept_own_only=True,
                                   author="posted_by", needs_reports=True),
    # Company structure: admin only, own company only, never created/deleted by the agent
    "department":          RowRule(None, scope_col="org_id", admin_only=True, no_delete=True),
    "role":                RowRule(None, scope_col="department_id", admin_only=True, no_delete=True),
    "organization":        RowRule(None, scope_col="id", admin_only=True, no_insert=True, no_delete=True),
    # Projects: the admin, or a manager of that project's department
    "projects":            RowRule(None, scope_col="department_id"),
}

READ_RULES = {                        # table -> owner column
    "performance_reviews": "user_id",
    "leave_requests": "user_id",
    "expenses": "submitted_by",
    "attendance": "user_id",
    "leave_schedule": "user_id",
    "orders": "requested_by",
}
ADMIN_ONLY_READ = {"audit_log"}


# ======================================================================
# Small SQL scanner (knows about 'strings' and parentheses)
# ======================================================================
def _mask(s):
    """Per-character paren depth, or None inside a string literal. Returns (mask, ok)."""
    out, depth, in_str, i, n, ok = [], 0, False, 0, len(s), True
    while i < n:
        ch = s[i]
        if in_str:
            out.append(None)
            if ch == "'":
                if i + 1 < n and s[i + 1] == "'":
                    out.append(None)
                    i += 2
                    continue
                in_str = False
        elif ch == "'":
            in_str = True
            out.append(None)
        elif ch == "(":
            out.append(depth)
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                ok = False
            out.append(depth)
        else:
            out.append(depth)
        i += 1
    if in_str or depth != 0:
        ok = False
    return out, ok


def _find_kw(s, kw, mask):
    """Index of keyword kw at the top level (outside strings/parentheses), or -1."""
    for m in re.finditer(rf"\b{kw}\b", s, re.IGNORECASE):
        if mask[m.start()] == 0:
            return m.start()
    return -1


def _split_commas(s):
    mask, ok = _mask(s)
    if not ok:
        raise ValueError("unbalanced")
    parts, last = [], 0
    for i, ch in enumerate(s):
        if ch == "," and mask[i] == 0:
            parts.append(s[last:i])
            last = i + 1
    parts.append(s[last:])
    return parts


def _literal(token):
    """int, None (NULL), str, or _EXPR for anything that is not a plain literal."""
    t = token.strip()
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if t.upper() == "NULL":
        return None
    m = re.fullmatch(r"'((?:[^']|'')*)'", t, re.S)
    if m:
        return m.group(1).replace("''", "'")
    return _EXPR


def _no_subquery(text):
    """Values must be plain values: a SELECT inside one could copy protected data."""
    if re.search(r"\bselect\b", normalize_sql(text), re.IGNORECASE):
        raise ValueError("subquery inside a value")


_NAME = r'(?:"?public"?\s*\.\s*)?"?([A-Za-z_]\w*)"?'
_UPDATE_RE = re.compile(
    r"^\s*UPDATE\s+(?:ONLY\s+)?" + _NAME +
    r"(?:\s+(?:AS\s+)?(?!SET\b)([A-Za-z_]\w*))?\s+SET\s+", re.IGNORECASE)
_DELETE_RE = re.compile(
    r"^\s*DELETE\s+FROM\s+(?:ONLY\s+)?" + _NAME +
    r"(?:\s+(?:AS\s+)?(?!WHERE\b|USING\b)([A-Za-z_]\w*))?\s+WHERE\s+", re.IGNORECASE)
_INSERT_RE = re.compile(
    r"^\s*INSERT\s+INTO\s+" + _NAME + r"\s*\(([^)]*)\)\s*VALUES\s*", re.IGNORECASE)
_ASSIGN_RE = re.compile(r'^\s*"?([A-Za-z_]\w*)"?\s*=\s*(.+?)\s*$', re.S)


def _analyze_write(sql):
    """Breaks a simple single-table write into parts. Raises ValueError if unsure."""
    s = re.sub(r";\s*$", "", sql.strip())
    mask, ok = _mask(s)
    if not ok:
        raise ValueError("unbalanced quotes or parentheses")

    m = _UPDATE_RE.match(s)
    if m:
        rest, rmask = s[m.end():], mask[m.end():]
        where_i = _find_kw(rest, "WHERE", rmask)
        ret_i = _find_kw(rest, "RETURNING", rmask)
        if where_i < 0 or _find_kw(rest, "FROM", rmask) >= 0 or (0 <= ret_i < where_i):
            raise ValueError("unsupported UPDATE form")
        where_end = ret_i if ret_i > where_i else len(rest)
        assigns = []
        for part in _split_commas(rest[:where_i]):
            am = _ASSIGN_RE.match(part)
            if not am:
                raise ValueError("unsupported SET clause")
            _no_subquery(am.group(2))
            assigns.append((am.group(1).lower(), am.group(2)))
        return {"kind": "UPDATE", "table": m.group(1).lower(), "alias": m.group(2),
                "assigns": assigns, "where": rest[where_i + 5:where_end].strip()}

    m = _DELETE_RE.match(s)
    if m:
        rest, rmask = s[m.end():], mask[m.end():]
        ret_i = _find_kw(rest, "RETURNING", rmask)
        where_part = rest[:ret_i] if ret_i >= 0 else rest
        return {"kind": "DELETE", "table": m.group(1).lower(), "alias": m.group(2),
                "assigns": [], "where": where_part.strip()}

    m = _INSERT_RE.match(s)
    if m:
        table = m.group(1).lower()
        cols = [c.strip().strip('"').lower() for c in m.group(2).split(",")]
        vals, vmask = s[m.end():], mask[m.end():]
        n, pos, rows = len(vals), 0, []
        while True:
            while pos < n and vals[pos].isspace():
                pos += 1
            if pos >= n or vals[pos] != "(":
                raise ValueError("unsupported VALUES")
            j = pos + 1
            while j < n and not (vals[j] == ")" and vmask[j] == 0):
                j += 1
            if j >= n:
                raise ValueError("unbalanced VALUES")
            row = [t.strip() for t in _split_commas(vals[pos + 1:j])]
            if len(row) != len(cols):
                raise ValueError("column/value count mismatch")
            for token in row:
                _no_subquery(token)
            rows.append(row)
            pos = j + 1
            while pos < n and vals[pos].isspace():
                pos += 1
            if pos < n and vals[pos] == ",":
                pos += 1
                continue
            break
        tail = vals[pos:].strip()
        if tail and not re.match(r"^RETURNING\b", tail, re.IGNORECASE):
            raise ValueError("unsupported text after VALUES")
        if len(rows) > MAX_INSERT_ROWS:
            raise ValueError("too many rows")
        return {"kind": "INSERT", "table": table, "alias": None,
                "cols": cols, "rows": rows, "assigns": [], "where": ""}

    raise ValueError("unsupported statement form")


# ======================================================================
# Decisions
# ======================================================================
REWRITE_HINT = (
    "I can only verify plain single-table statements: "
    "UPDATE <table> SET col = value WHERE ..., DELETE FROM <table> WHERE ..., or "
    "INSERT INTO <table> (cols) VALUES (...), where every value is a plain value "
    "(no sub-SELECT). Rewrite it in that form."
)


def _has_reports(cur, actor_id) -> bool:
    cur.execute("SELECT COUNT(*) FROM users WHERE manager_id = %s AND is_active", (actor_id,))
    return cur.fetchone()[0] > 0


def _org_of_user(cur, uid, cache=None):
    key = ("org", uid)
    if cache is not None and key in cache:
        return cache[key]
    org = _org_of(cur, uid)
    if cache is not None:
        cache[key] = org
    return org


def _same_org_users(cur, a, b, cache=None):
    org = _org_of_user(cur, a, cache)
    return org is not None and org == _org_of_user(cur, b, cache)


def _org_of_dept(cur, dept_id):
    if dept_id is None:
        return None
    cur.execute("SELECT org_id FROM department WHERE id = %s", (dept_id,))
    row = cur.fetchone()
    return None if row is None else row[0]


def _dept_of_user(cur, uid):
    cur.execute("SELECT department_id FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    return None if row is None else row[0]


def _row_org(cur, rule, row):
    if rule.scope_col == "department_id":
        return _org_of_dept(cur, row.get("department_id"))
    return row.get(rule.scope_col)          # 'org_id' (department) or 'id' (organization)


def _scope_denial(cur, cache, actor_id, is_admin, rule, row):
    """Company-structure tables: reason this actor may not touch this row, or None."""
    actor_org = _org_of_user(cur, actor_id, cache)
    if actor_org is None:
        return "Your organization could not be determined."
    org = _row_org(cur, rule, row)
    if org is None or org != actor_org:
        return "That record belongs to another organization (or has none)."
    if is_admin:
        return None
    if rule.admin_only:
        return "Only the HR/admin can change this."
    if _has_reports(cur, actor_id) and _dept_of_user(cur, actor_id) == row.get("department_id"):
        return None
    return "Only the HR/admin or a manager of that department can change this."


def _scoped_write(cur, actor_id, is_admin, rule, a):
    """(reason, kind) for writes to department / role / organization / projects."""
    kind, table = a["kind"], a["table"]
    if (kind == "INSERT" and rule.no_insert) or (kind == "DELETE" and rule.no_delete):
        return f"{kind.title()} is not permitted on this table through the agent.", "denied"
    cache = {}
    if kind == "INSERT":
        for raw in a["rows"]:
            vals = dict(zip(a["cols"], [_literal(t) for t in raw]))
            v = vals.get(rule.scope_col)
            if not isinstance(v, int):
                return f"State {rule.scope_col} as a plain number.", "denied"
            reason = _scope_denial(cur, cache, actor_id, is_admin, rule, {rule.scope_col: v})
            if reason:
                return reason, "denied"
        return None, None

    set_cols = {n for n, _ in a["assigns"]}
    if "id" in set_cols:
        return "That column cannot be changed.", "denied"
    if rule.scope_col in set_cols:
        v = _literal(dict(a["assigns"])[rule.scope_col])
        if not isinstance(v, int):
            return f"State {rule.scope_col} as a plain number.", "denied"
        reason = _scope_denial(cur, cache, actor_id, is_admin, rule, {rule.scope_col: v})
        if reason:
            return reason, "denied"
    alias = f" {a['alias']}" if a["alias"] else ""
    cur.execute(f"SELECT {rule.scope_col} FROM {table}{alias} WHERE {a['where']}")
    fetched = cur.fetchall()
    if len(fetched) > MAX_ROWS_CHECKED:
        return "That would affect too many records to verify at once.", "denied"
    for (value,) in fetched:
        reason = _scope_denial(cur, cache, actor_id, is_admin, rule, {rule.scope_col: value})
        if reason:
            return reason, "denied"
    return None, None


def _can_assign_to(cur, actor_id, is_admin, new_owner):
    row = _user_row(cur, new_owner)
    if row is None or not row[0]:
        return "The new assignee must be an active employee."
    if new_owner == actor_id:
        return None
    if is_admin:
        if _same_org_users(cur, actor_id, new_owner):
            return None
        return "That person belongs to another organization (or has none)."
    if actor_id in _ancestors(cur, new_owner):
        return None
    return "You can only assign work to yourself or to people who report to you."


def _ref_denial(cur, actor_id, is_admin, rule, vals, cache):
    """Department / project columns being set must point inside the actor's own company."""
    has_dept = bool(rule.dept_col) and rule.dept_col in vals
    has_proj = bool(rule.project_col) and rule.project_col in vals
    if not (has_dept or has_proj):
        return None
    actor_org = _org_of_user(cur, actor_id, cache)
    if actor_org is None:
        return "Your organization could not be determined."
    if has_dept:
        v = vals[rule.dept_col]
        if v is _EXPR or (v is not None and not isinstance(v, int)):
            return f"State {rule.dept_col} as a plain number."
        if v is None:
            if rule.admin_if_null == rule.dept_col and not is_admin:
                return "Only the HR/admin can make company-wide entries."
        else:
            if _org_of_dept(cur, v) != actor_org:
                return "That department belongs to another organization (or does not exist)."
            if rule.dept_own_only and not is_admin and v != _dept_of_user(cur, actor_id):
                return "You can only use your own department here."
    if has_proj:
        v = vals[rule.project_col]
        if v is _EXPR or (v is not None and not isinstance(v, int)):
            return f"State {rule.project_col} as a plain number."
        if v is not None:
            cur.execute("SELECT department_id FROM projects WHERE id = %s", (v,))
            row = cur.fetchone()
            if row is None or _org_of_dept(cur, row[0]) != actor_org:
                return "That project belongs to another organization (or does not exist)."
    return None


def _approver_limit(rule, set_cols, is_delete):
    """Approvers decide; they do not rewrite or erase someone else's request."""
    if not rule.request:
        return None
    if is_delete:
        return "Only the person who made a request can withdraw it. Reject it instead."
    if set_cols - {"status"}:
        return "An approver can only change the decision (status) of a request, not its details."
    return None


def _row_denial(cur, actor_id, is_admin, rule, row, status_change, cache, new_status=None,
                set_cols=frozenset(), is_delete=False):
    """Reason this actor may not touch this existing row, or None if allowed."""
    if is_delete and rule.admin_delete_only and not is_admin:
        return "Only the HR/admin can delete these records."
    if rule.transitions:
        if row.get("status") not in rule.transitions:
            return (f"A request that is '{row.get('status')}' is final and cannot be "
                    "changed or deleted by anyone.")
        if status_change and new_status is not None:
            if new_status not in rule.transitions.get(row.get("status"), set()):
                return (f"A request that is '{row.get('status')}' cannot be changed to "
                        f"'{new_status}'.")
    if rule.admin_if_null and row.get(rule.admin_if_null) is None and not is_admin:
        return "Only the HR/admin can change company-wide entries."
    owner = row.get(rule.owner)
    if owner is None:
        return None if is_admin else "This record has no owner, so only the HR/admin can change it."
    owner = int(owner)
    if owner == actor_id:
        if not rule.self_edit:
            return "You cannot change your own records of this kind. Someone above you must."
        if status_change and not rule.self_status:
            return "You cannot approve or reject your own request. Someone above you must."
        if rule.self_pending_only and row.get("status") != "pending":
            return "A request that is no longer pending cannot be edited by its owner."
        return None
    if is_admin:
        if _same_org_users(cur, actor_id, owner, cache):
            return _approver_limit(rule, set_cols, is_delete)
        return "That person belongs to another organization (or has none)."
    if owner not in cache:
        cache[owner] = _ancestors(cur, owner)
    if actor_id in cache[owner]:
        return _approver_limit(rule, set_cols, is_delete)
    return "You can only change records of people who report to you (directly or indirectly)."


def _check_insert(cur, actor_id, is_admin, rule, a):
    cache = {}
    if rule.needs_reports and not is_admin and not _has_reports(cur, actor_id):
        return "Only managers (people with reports) or the HR/admin can post these."
    for raw in a["rows"]:
        vals = dict(zip(a["cols"], [_literal(t) for t in raw]))
        reason = _ref_denial(cur, actor_id, is_admin, rule, vals, cache)
        if reason:
            return reason
        if rule.author and vals.get(rule.author) != actor_id:
            return f"You can only add these under your own name ({rule.author} must be your employee id)."
        if rule.admin_if_null and vals.get(rule.admin_if_null) is None and not is_admin:
            return "Only the HR/admin can add company-wide entries."
        owner = vals.get(rule.owner)
        if owner is _EXPR:
            return "State whose record this is with a plain employee id."
        if rule.request and owner != actor_id:
            return "You can only submit these for yourself."
        if owner is None:
            if is_admin:
                continue
            return "State whose record this is. Records with no owner are admin only."
        if not isinstance(owner, int):
            return "State whose record this is with a plain employee id."
        if owner == actor_id:
            if not rule.self_insert:
                return "You cannot add records of this kind for yourself."
            if rule.today_col:
                tok = dict(zip(a["cols"], raw)).get(rule.today_col)
                today = _dt.date.today().isoformat()
                if tok is None or (_literal(tok) != today and tok.strip().upper() != "CURRENT_DATE"):
                    return "You can only record your own attendance for today."
            if not rule.self_status and "status" in vals and vals["status"] != "pending":
                return "A new request must start as pending."
        elif is_admin:
            if not _same_org_users(cur, actor_id, owner, cache):
                return "That person belongs to another organization (or has none)."
        else:
            if owner not in cache:
                cache[owner] = _ancestors(cur, owner)
            if actor_id not in cache[owner]:
                return "You can only add records for people who report to you."
    return None


def _row_write_reason(cur, actor_id, sql):
    """(reason, kind) if refused, else (None, None). kind: 'denied' or 'rewrite'."""
    try:
        a = _analyze_write(sql)
    except ValueError:
        return REWRITE_HINT, "rewrite"
    table = a["table"]
    if table != write_target_table(sql):
        return REWRITE_HINT, "rewrite"
    rule = ROW_RULES.get(table)
    if rule is None:
        return "Writes to this table are not permitted.", "denied"

    me = _user_row(cur, actor_id)
    if me is None or not me[0]:
        return "Your account could not be verified as active.", "denied"
    is_admin = me[1]

    if rule.scope_col:
        return _scoped_write(cur, actor_id, is_admin, rule, a)

    if a["kind"] == "INSERT":
        reason = _check_insert(cur, actor_id, is_admin, rule, a)
        return (reason, "denied") if reason else (None, None)

    set_cols = {name for name, _ in a["assigns"]}
    if "id" in set_cols or set_cols & set(rule.locked):
        return "That column cannot be changed.", "denied"
    if rule.owner in set_cols:
        if not rule.owner_change:
            return "You cannot change whose record this is.", "denied"
        expr = dict(a["assigns"])[rule.owner]
        new_owner = _literal(expr)
        if not isinstance(new_owner, int):
            return "State the new assignee with a plain employee id.", "denied"
        reason = _can_assign_to(cur, actor_id, is_admin, new_owner)
        if reason:
            return reason, "denied"
    reason = _ref_denial(cur, actor_id, is_admin, rule,
                         {n: _literal(e) for n, e in a["assigns"]}, {})
    if reason:
        return reason, "denied"
    status_change = "status" in set_cols
    new_status = None
    if rule.transitions and status_change:
        new_status = _literal(dict(a["assigns"])["status"])
        if not isinstance(new_status, str):
            return "State the new status as a plain value.", "denied"

    cols = [rule.owner]
    if rule.self_pending_only or rule.transitions:
        cols.append("status")
    if rule.admin_if_null and rule.admin_if_null not in cols:
        cols.append(rule.admin_if_null)
    alias = f" {a['alias']}" if a["alias"] else ""
    cur.execute(f"SELECT {', '.join(cols)} FROM {table}{alias} WHERE {a['where']}")
    fetched = cur.fetchall()
    if len(fetched) > MAX_ROWS_CHECKED:
        return "That would affect too many records to verify at once.", "denied"

    cache = {}
    for values in fetched:
        row = dict(zip(cols, values))
        reason = _row_denial(cur, actor_id, is_admin, rule, row, status_change, cache, new_status,
                             frozenset(set_cols), a["kind"] == "DELETE")
        if reason:
            return reason, "denied"
    return None, None


# ======================================================================
# Reading: rewrite SELECTs so people only see rows they are allowed to
# ======================================================================
def _descendants(cur, root_id):
    """root_id plus everyone below them (all levels)."""
    seen, frontier = {root_id}, [root_id]
    while frontier and len(seen) <= MAX_VISIBLE:
        cur.execute("SELECT id FROM users WHERE manager_id = ANY(%s)", (frontier,))
        new = [r[0] for r in cur.fetchall() if r[0] not in seen]
        seen.update(new)
        frontier = new
    return seen


_ALIAS_STOP = (r"WHERE|JOIN|LEFT|RIGHT|INNER|FULL|CROSS|ON|GROUP|ORDER|LIMIT|HAVING|"
               r"UNION|OFFSET|FETCH|USING|NATURAL|EXCEPT|INTERSECT|FOR|SET")


def _rewrite_table(sql, table, owner_col, ids, injected):
    pat = re.compile(
        r"'(?:[^']|'')*'"
        r"|\b(FROM|JOIN)\s+(?:public\s*\.\s*)?" + table + r"\b"
        r"(?:\s+(?:AS\s+)?(?!(?:" + _ALIAS_STOP + r")\b)([A-Za-z_]\w*))?",
        re.IGNORECASE)

    def sub(m):
        if m.group(0).startswith("'"):
            return m.group(0)
        alias = m.group(2) or table
        inj = f"(SELECT * FROM {table} WHERE {owner_col} IN ({ids})) AS {alias}"
        injected.append(inj)
        return f"{m.group(1)} {inj}"

    return pat.sub(sub, sql)


def _restrict_select(cur, actor_id, sql):
    """(sql_to_run, reason). reason is None when the query may run."""
    me = _user_row(cur, actor_id)
    if me is None or not me[0]:
        return sql, "Your account could not be verified as active."
    if me[1]:
        return sql, None                      # the admin reads everything

    norm = normalize_sql(sql)
    for t in ADMIN_ONLY_READ:
        if re.search(rf"\b{t}\b", norm, re.IGNORECASE):
            return sql, "Only the HR/admin can read the audit log."

    visible = _descendants(cur, actor_id)
    if len(visible) > MAX_VISIBLE:
        return sql, "Your team is too large to restrict this query safely."
    ids = ",".join(str(int(i)) for i in sorted(visible))

    out, injected = sql, []
    for table, owner_col in READ_RULES.items():
        if re.search(rf"\b{table}\b", norm, re.IGNORECASE):
            out = _rewrite_table(out, table, owner_col, ids, injected)

    leftover = out
    for inj in set(injected):
        leftover = leftover.replace(inj, " ")
    ln = normalize_sql(leftover)
    for table in READ_RULES:
        for m in re.finditer(rf"\b{table}\b", ln, re.IGNORECASE):
            if not ln[m.end():].lstrip().startswith("."):
                return sql, ("That query reads protected data in a form I cannot restrict safely. "
                             "Use a simple SELECT ... FROM <table> (with an alias if needed).")
    return out, None


# ======================================================================
# Reverts of changes to these tables
# ======================================================================
def _revert_reason(cur, actor_id, table, operation, before_rows, inserted_pks):
    rule = ROW_RULES.get(table)
    if rule is None:
        return "Undoing changes to this table is not permitted."
    me = _user_row(cur, actor_id)
    if me is None or not me[0]:
        return "Your account could not be verified as active."
    is_admin = me[1]
    if rule.scope_col:
        if operation in ("UPDATE", "DELETE"):
            rows = list(before_rows or [])
        elif operation == "INSERT":
            rows = []
            if inserted_pks:
                cur.execute(f"SELECT {rule.scope_col} FROM {table} WHERE id = ANY(%s)",
                            (list(inserted_pks),))
                rows = [{rule.scope_col: r[0]} for r in cur.fetchall()]
        else:
            return "That kind of change cannot be undone."
        cache = {}
        for row in rows:
            reason = _scope_denial(cur, cache, actor_id, is_admin, rule, row)
            if reason:
                return reason
        return None

    if operation in ("UPDATE", "DELETE"):
        rows, status_change = list(before_rows or []), True
    elif operation == "INSERT":
        rows, status_change = [], False
        if inserted_pks:
            cols = [rule.owner]
            if rule.self_pending_only or rule.transitions:
                cols.append("status")
            if rule.admin_if_null and rule.admin_if_null not in cols:
                cols.append(rule.admin_if_null)
            cur.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE id = ANY(%s)",
                        (list(inserted_pks),))
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    else:
        return "That kind of change cannot be undone."

    cache = {}
    for row in rows:
        reason = _row_denial(cur, actor_id, is_admin, rule, row, status_change, cache)
        if reason:
            return reason
    return None


# ======================================================================
# Tool-facing wrappers
# ======================================================================
def _actor_id(actor):
    try:
        return _to_int(actor[0])
    except (TypeError, IndexError):
        return None


def _run_with_cursor(fn):
    """Runs fn(cursor) on a pooled connection. Any error raises to the caller."""
    from mcp_tools import get_connection, release_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{CHECK_TIMEOUT}'")
            return fn(cur)
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        release_connection(conn)


def _audit_denied(actor, thread_id, table, sql, reason, attempted):
    try:
        from mcp_tools import write_audit
        write_audit(actor if actor else (None, "unknown"), "DENIED", table or None,
                    new={"attempted": attempted, "reason": reason},
                    sql_text=sql, thread_id=thread_id, status="blocked")
    except Exception:
        logger.exception("Could not audit a permission denial.")


def _message(reason, kind):
    if kind == "rewrite":
        return f"ERROR: {reason} Nothing was changed."
    return (f"ERROR: Permission denied. {reason} Nothing was changed. "
            "Tell the user this plainly. Do not retry or try another tool or SQL to get around it.")


def check_row_write(actor, thread_id, sql) -> Optional[str]:
    """None if the INSERT/UPDATE/DELETE may run, else an error string for the tool to return."""
    actor_id = _actor_id(actor)
    reason, kind = None, "denied"
    if actor_id is None:
        reason = "Your identity could not be verified."
    elif not is_single_statement(sql):
        reason, kind = "Only one SQL statement is allowed.", "rewrite"
    else:
        try:
            reason, kind = _run_with_cursor(lambda cur: _row_write_reason(cur, actor_id, sql))
        except Exception:
            logger.exception("Row permission check failed; denying.")
            reason, kind = "The permission check could not be completed, so the action was refused.", "denied"
    if reason is None:
        return None
    _audit_denied(actor, thread_id, write_target_table(sql), sql, reason, "sql_write")
    return _message(reason, kind)


def restrict_select(actor, thread_id, sql):
    """(sql_to_run, error_or_None). Rewrites SELECTs on protected tables to the allowed rows."""
    norm = normalize_sql(sql)
    sensitive = [t for t in (ADMIN_ONLY_READ | set(READ_RULES))
                 if re.search(rf"\b{t}\b", norm, re.IGNORECASE)]
    if not sensitive:
        return sql, None

    actor_id = _actor_id(actor)
    if actor_id is None:
        return sql, _message("Your identity could not be verified.", "denied")
    try:
        new_sql, reason = _run_with_cursor(lambda cur: _restrict_select(cur, actor_id, sql))
    except Exception:
        logger.exception("Read permission check failed; denying.")
        new_sql, reason = sql, "The permission check could not be completed, so the query was refused."
    if reason is None:
        return new_sql, None
    _audit_denied(actor, thread_id, sensitive[0], sql, reason, "sql_read")
    return sql, _message(reason, "rewrite" if "cannot restrict" in reason else "denied")


def check_revert(actor, thread_id, table, operation, before_rows, inserted_pks) -> Optional[str]:
    """Checks an undo of a change made to one of the tables above (users is handled elsewhere)."""
    if table == "users":
        return None
    actor_id = _actor_id(actor)
    if actor_id is None:
        reason = "Your identity could not be verified."
    else:
        try:
            reason = _run_with_cursor(
                lambda cur: _revert_reason(cur, actor_id, table, operation, before_rows, inserted_pks))
        except Exception:
            logger.exception("Revert permission check failed; denying.")
            reason = "The permission check could not be completed, so the undo was refused."
    if reason is None:
        return None
    _audit_denied(actor, thread_id, table, None, reason, "revert")
    return _message(reason, "denied")