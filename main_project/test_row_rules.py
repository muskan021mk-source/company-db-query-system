"""
Offline tests for row_permissions.py - no database needed.
Run:  python test_row_rules.py
"""
import re

import row_permissions as R

# id: (active, admin, manager_id)
USERS = {
    1:  (False, False, None),   # Chris, deactivated
    55: (True,  False, None),   # Ravi, Engineering head (has reports)
    2:  (True,  False, 55),     # Joshua
    3:  (True,  False, 55),     # Jordan
    56: (True,  True,  55),     # Muskan, admin
    10: (True,  False, None),   # Catherine, Sales head
    11: (True,  False, 10),
    30: (True,  False, None),   # another company
    31: (True,  False, None),   # no department
}

DEPT = {1: 1, 55: 1, 2: 1, 3: 1, 56: 1, 10: 2, 11: 2, 30: 9, 31: None}
DEPT_ORG = {1: 1, 2: 1, 9: 2}

TABLES = {
    "expenses": [
        {"id": 1, "submitted_by": 2,  "status": "pending"},
        {"id": 2, "submitted_by": 2,  "status": "approved"},
        {"id": 3, "submitted_by": 55, "status": "pending"},
        {"id": 4, "submitted_by": 10, "status": "pending"},
        {"id": 5, "submitted_by": 56, "status": "pending"},
        {"id": 6, "submitted_by": 2,  "status": "rejected"},
        {"id": 7, "submitted_by": 30, "status": "pending"},
        {"id": 8, "submitted_by": 2,  "status": None},
    ],
    "orders": [
        {"id": 1, "requested_by": 2, "status": "pending"},
        {"id": 2, "requested_by": 2, "status": "approved"},
        {"id": 3, "requested_by": 2, "status": "delivered"},
    ],
    "leave_requests": [
        {"id": 1, "user_id": 2, "status": "pending"},
        {"id": 2, "user_id": 2, "status": "approved"},
    ],
    "tasks": [
        {"id": 1, "assigned_to": 2},
        {"id": 2, "assigned_to": 55},
        {"id": 3, "assigned_to": None},
    ],
    "performance_reviews": [{"id": 1, "user_id": 2, "reviewer_id": 55}],
    "announcements": [
        {"id": 1, "posted_by": 2,  "department_id": 1},
        {"id": 2, "posted_by": 56, "department_id": None},
    ],
    "attendance": [{"id": 1, "user_id": 2}, {"id": 2, "user_id": 56}],
    "assets": [{"id": 1, "assigned_to": 2}],
    "projects": [
        {"id": 1, "department_id": 1},
        {"id": 2, "department_id": 2},
        {"id": 3, "department_id": 9},
    ],
    "department": [{"id": 1, "org_id": 1}, {"id": 9, "org_id": 2}],
    "role": [{"id": 1, "department_id": 1}, {"id": 9, "department_id": 9}],
    "organization": [{"id": 1}, {"id": 2}],
}


class FakeCur:
    def __init__(self):
        self._rows = []

    def execute(self, sql, params=()):
        s = " ".join(sql.split())
        if s.startswith("SELECT is_active, is_hr_admin FROM users WHERE id"):
            u = USERS.get(params[0])
            self._rows = [] if u is None else [(u[0], u[1])]
        elif s.startswith("SELECT manager_id FROM users WHERE id"):
            u = USERS.get(params[0])
            self._rows = [] if u is None else [(u[2],)]
        elif s.startswith("SELECT COUNT(*) FROM users WHERE manager_id"):
            self._rows = [(sum(1 for u in USERS.values() if u[2] == params[0] and u[0]),)]
        elif s.startswith("SELECT department_id FROM users WHERE id") and params:
            self._rows = [(DEPT.get(params[0]),)] if params[0] in USERS else []
        elif s.startswith("SELECT org_id FROM department WHERE id") and params:
            self._rows = [(DEPT_ORG[params[0]],)] if params[0] in DEPT_ORG else []
        elif s.startswith("SELECT department_id FROM projects WHERE id") and params:
            self._rows = [(r["department_id"],) for r in TABLES["projects"] if r["id"] == params[0]]
        elif s.startswith("SELECT id FROM users WHERE manager_id = ANY"):
            self._rows = [(i,) for i, u in USERS.items() if u[2] in params[0]]
        else:
            m = re.match(r"^SELECT (.+?) FROM (\w+)(?: (\w+))? WHERE (.+)$", s)
            assert m, f"unexpected query: {s}"
            cols = [c.strip() for c in m.group(1).split(",")]
            table, alias, where = m.group(2), m.group(3), m.group(4)
            if alias:
                where = where.replace(alias + ".", "")
            where = re.sub(r"\s*=\s*", " = ", where)
            rows = TABLES[table]
            if where == "id = ANY(%s)":
                hit = [r for r in rows if r["id"] in params[0]]
            elif re.fullmatch(r"(\w+) = (\d+)", where):
                c, v = re.fullmatch(r"(\w+) = (\d+)", where).groups()
                hit = [r for r in rows if r.get(c) == int(v)]
            elif re.fullmatch(r"(\w+) IN \(([\d, ]+)\)", where):
                c, v = re.fullmatch(r"(\w+) IN \(([\d, ]+)\)", where).groups()
                ids = [int(x) for x in v.split(",")]
                hit = [r for r in rows if r.get(c) in ids]
            else:
                raise AssertionError(f"fake can't evaluate: {where}")
            self._rows = [tuple(r.get(c) for c in cols) for r in hit]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


passed = failed = 0


def expect(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {name} (got {got!r}, wanted {want!r})")


def allowed(actor, sql):
    try:
        reason, _kind = R._row_write_reason(FakeCur(), actor, sql)
    except Exception:
        return False
    return reason is None


def kind_of(actor, sql):
    return R._row_write_reason(FakeCur(), actor, sql)[1]


def revert(actor, table, op, before=None, pks=None):
    return R._revert_reason(FakeCur(), actor, table, op, before, pks)


# ---------------------------------------------------------------- approvals
expect("own expense approval",            allowed(2,  "UPDATE expenses SET status='approved' WHERE id=1"), False)
expect("manager approves report",         allowed(55, "UPDATE expenses SET status='approved' WHERE id=1"), True)
expect("peer approves",                   allowed(3,  "UPDATE expenses SET status='approved' WHERE id=1"), False)
expect("other branch approves",           allowed(10, "UPDATE expenses SET status='approved' WHERE id=1"), False)
expect("admin approves report",           allowed(56, "UPDATE expenses SET status='approved' WHERE id=1"), True)
expect("admin approves OWN expense",      allowed(56, "UPDATE expenses SET status='approved' WHERE id=5"), False)
expect("report approves manager",         allowed(2,  "UPDATE expenses SET status='approved' WHERE id=3"), False)
expect("manager approves with alias",     allowed(55, "UPDATE expenses e SET status='approved' WHERE e.id=1"), True)

# ------------------------------------------------ decided requests are final
expect("approved cannot go back to pending",  allowed(55, "UPDATE expenses SET status='pending' WHERE id=2"), False)
expect("rejected cannot become approved",     allowed(55, "UPDATE expenses SET status='approved' WHERE id=6"), False)
expect("pending cannot jump to delivered",    allowed(55, "UPDATE expenses SET status='delivered' WHERE id=1"), False)
expect("reject a pending request",            allowed(55, "UPDATE expenses SET status='rejected' WHERE id=1"), True)
expect("status given as an expression",       allowed(55, "UPDATE expenses SET status=lower('APPROVED') WHERE id=1"), False)

# --------- NEW: a decided request cannot be edited or deleted by ANYONE
expect("manager changes amount of approved expense",  allowed(55, "UPDATE expenses SET amount=1 WHERE id=2"), False)
expect("admin changes amount of approved expense",    allowed(56, "UPDATE expenses SET amount=1 WHERE id=2"), False)
expect("manager deletes approved expense",            allowed(55, "DELETE FROM expenses WHERE id=2"), False)
expect("admin deletes approved expense",              allowed(56, "DELETE FROM expenses WHERE id=2"), False)
expect("admin edits rejected expense",                allowed(56, "UPDATE expenses SET amount=1 WHERE id=6"), False)
expect("manager deletes a PENDING report expense",    allowed(55, "DELETE FROM expenses WHERE id=1"), False)
expect("admin deletes a PENDING report expense",      allowed(56, "DELETE FROM expenses WHERE id=1"), False)
expect("expense with no status is locked (fail closed)", allowed(56, "UPDATE expenses SET amount=1 WHERE id=8"), False)
expect("mixed pending + approved rows",               allowed(55, "UPDATE expenses SET amount=1 WHERE id IN (1, 2)"), False)
expect("approved leave cannot be edited",             allowed(55, "UPDATE leave_requests SET reason='x' WHERE id=2"), False)
expect("pending leave can be approved by manager",    allowed(55, "UPDATE leave_requests SET status='approved' WHERE id=1"), True)
expect("own leave approval",                          allowed(2,  "UPDATE leave_requests SET status='approved' WHERE id=1"), False)
expect("order pending to approved",                   allowed(55, "UPDATE orders SET status='approved' WHERE id=1"), True)
expect("order approved to delivered",                 allowed(55, "UPDATE orders SET status='delivered' WHERE id=2"), True)
expect("delivered order cannot be changed",           allowed(56, "UPDATE orders SET status='pending' WHERE id=3"), False)
expect("delivered order cannot be deleted",           allowed(56, "DELETE FROM orders WHERE id=3"), False)

# ------------------------------------------------------- own requests
expect("edit own pending expense",        allowed(2, "UPDATE expenses SET amount=50 WHERE id=1"), True)
expect("edit own approved expense",       allowed(2, "UPDATE expenses SET amount=50 WHERE id=2"), False)
expect("delete own pending expense",      allowed(2, "DELETE FROM expenses WHERE id=1"), True)
expect("delete own approved expense",     allowed(2, "DELETE FROM expenses WHERE id=2"), False)
expect("change who owns an expense",      allowed(2, "UPDATE expenses SET submitted_by=55 WHERE id=1"), False)
expect("submit own pending expense",      allowed(2, "INSERT INTO expenses (submitted_by, amount, status) VALUES (2, 40, 'pending')"), True)
expect("submit own expense, no status",   allowed(2, "INSERT INTO expenses (submitted_by, amount) VALUES (2, 40)"), True)
expect("submit own expense as approved",  allowed(2, "INSERT INTO expenses (submitted_by, amount, status) VALUES (2, 40, 'approved')"), False)
expect("submit expense for manager",      allowed(2, "INSERT INTO expenses (submitted_by, amount) VALUES (55, 40)"), False)
expect("manager submits for report",      allowed(55, "INSERT INTO expenses (submitted_by, amount) VALUES (2, 40)"), False)
expect("admin submits for someone else",  allowed(56, "INSERT INTO expenses (submitted_by, amount) VALUES (2, 40)"), False)
expect("admin submits own expense",       allowed(56, "INSERT INTO expenses (submitted_by, amount) VALUES (56, 40)"), True)
expect("expense with no owner (admin)",   allowed(56, "INSERT INTO expenses (amount) VALUES (40)"), False)
expect("leave for someone else",          allowed(55, "INSERT INTO leave_requests (user_id, reason) VALUES (2, 'x')"), False)
expect("own leave request",               allowed(2, "INSERT INTO leave_requests (user_id, reason) VALUES (2, 'x')"), True)
expect("order for someone else",          allowed(55, "INSERT INTO orders (requested_by, item_name) VALUES (2, 'x')"), False)
expect("own order",                       allowed(2, "INSERT INTO orders (requested_by, item_name) VALUES (2, 'x')"), True)

# --------- NEW: approvers decide, they do not rewrite or erase a request
expect("manager changes amount of a pending request",   allowed(55, "UPDATE expenses SET amount=1 WHERE id=1"), False)
expect("manager approves AND changes the amount",       allowed(55, "UPDATE expenses SET status='approved', amount=1 WHERE id=1"), False)
expect("admin changes reason on a pending leave",       allowed(56, "UPDATE leave_requests SET reason='x' WHERE id=1"), False)
expect("manager changes expense category",              allowed(55, "UPDATE expenses SET category='x' WHERE id=1"), False)
expect("owner edits own pending leave",                 allowed(2, "UPDATE leave_requests SET reason='x' WHERE id=1"), True)
expect("owner withdraws own pending leave",             allowed(2, "DELETE FROM leave_requests WHERE id=1"), True)
expect("manager deletes pending leave of a report",     allowed(55, "DELETE FROM leave_requests WHERE id=1"), False)
expect("manager rejects pending leave of a report",     allowed(55, "UPDATE leave_requests SET status='rejected' WHERE id=1"), True)

# --------- NEW: department / project columns must stay inside your own company
expect("expense charged to own company's department",   allowed(2, "INSERT INTO expenses (submitted_by, amount, department_id) VALUES (2, 5, 1)"), True)
expect("expense charged to ANOTHER company's department", allowed(2, "INSERT INTO expenses (submitted_by, amount, department_id) VALUES (2, 5, 9)"), False)
expect("expense with a department that doesn't exist",  allowed(2, "INSERT INTO expenses (submitted_by, amount, department_id) VALUES (2, 5, 77)"), False)
expect("expense department given as an expression",     allowed(2, "INSERT INTO expenses (submitted_by, amount, department_id) VALUES (2, 5, 1+8)"), False)
expect("move own pending expense to another company",   allowed(2, "UPDATE expenses SET department_id=9 WHERE id=1"), False)
expect("order charged to another company's department", allowed(2, "INSERT INTO orders (requested_by, item_name, department_id) VALUES (2, 'x', 9)"), False)
expect("task in own company's project",                 allowed(2, "INSERT INTO tasks (title, assigned_to, project_id) VALUES ('x', 2, 1)"), True)
expect("task in ANOTHER company's project",             allowed(2, "INSERT INTO tasks (title, assigned_to, project_id) VALUES ('x', 2, 3)"), False)
expect("task in a project that doesn't exist",          allowed(2, "INSERT INTO tasks (title, assigned_to, project_id) VALUES ('x', 2, 99)"), False)
expect("task with no project",                          allowed(2, "INSERT INTO tasks (title, assigned_to, project_id) VALUES ('x', 2, NULL)"), True)
expect("move own task into another company's project",  allowed(2, "UPDATE tasks SET project_id=3 WHERE id=1"), False)
expect("move own task into own company's project",      allowed(2, "UPDATE tasks SET project_id=2 WHERE id=1"), True)

# ------------------------------------------------------------- tasks
expect("own task done",                   allowed(2, "UPDATE tasks SET status='done' WHERE id=1"), True)
expect("manager's task done by report",   allowed(2, "UPDATE tasks SET status='done' WHERE id=2"), False)
expect("manager reassigns to a report",   allowed(55, "UPDATE tasks SET assigned_to=3 WHERE id=1"), True)
expect("manager reassigns to other branch", allowed(55, "UPDATE tasks SET assigned_to=10 WHERE id=1"), False)
expect("report hands task to a peer",     allowed(2, "UPDATE tasks SET assigned_to=3 WHERE id=1"), False)
expect("admin reassigns anywhere",        allowed(56, "UPDATE tasks SET assigned_to=10 WHERE id=1"), True)
expect("reassign to deactivated person",  allowed(56, "UPDATE tasks SET assigned_to=1 WHERE id=1"), False)
expect("reassign with an expression",     allowed(56, "UPDATE tasks SET assigned_to=(SELECT 3) WHERE id=1"), False)
expect("unassigned task, non-admin",      allowed(2, "UPDATE tasks SET status='done' WHERE id=3"), False)
expect("unassigned task, admin",          allowed(56, "UPDATE tasks SET status='done' WHERE id=3"), True)
expect("create own task",                 allowed(2, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 2)"), True)
expect("create task for manager",         allowed(2, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 55)"), False)
expect("manager creates task for report", allowed(55, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 2)"), True)
expect("create task with no owner",       allowed(2, "INSERT INTO tasks (title) VALUES ('x')"), False)
expect("manager updates mixed rows",      allowed(55, "UPDATE tasks SET status='done' WHERE id IN (1, 2)"), True)
expect("report updates mixed rows",       allowed(2, "UPDATE tasks SET status='done' WHERE id IN (1, 2)"), False)

# --------- NEW: values must be plain values (no sub-SELECT copying protected data)
expect("copy another table into a value",   allowed(2, "UPDATE tasks SET title=(SELECT amount FROM expenses WHERE id=3) WHERE id=1"), False)
expect("sub-SELECT in a value is 'rewrite'", kind_of(2, "UPDATE tasks SET title=(SELECT amount FROM expenses WHERE id=3) WHERE id=1"), "rewrite")
expect("sub-SELECT in an INSERT value",     allowed(2, "INSERT INTO tasks (title, assigned_to) VALUES ((SELECT 'x'), 2)"), False)
expect("word 'select' inside a text value is fine", allowed(2, "INSERT INTO tasks (title, assigned_to) VALUES ('select a seat', 2)"), True)
expect("word 'select' in an UPDATE text value is fine", allowed(2, "UPDATE tasks SET title='select a seat' WHERE id=1"), True)

# ----------------------------------------------------- performance reviews
expect("manager reviews report",          allowed(55, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (2, 55, 4)"), True)
expect("review under someone else's name", allowed(55, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (2, 56, 4)"), False)
expect("review with no reviewer",         allowed(55, "INSERT INTO performance_reviews (user_id, rating) VALUES (2, 4)"), False)
expect("review yourself",                 allowed(2, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (2, 2, 5)"), False)
expect("review your manager",             allowed(2, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (55, 2, 5)"), False)
expect("edit own review",                 allowed(2, "UPDATE performance_reviews SET rating=5 WHERE id=1"), False)
expect("change reviewer of a review",     allowed(55, "UPDATE performance_reviews SET reviewer_id=56 WHERE id=1"), False)
expect("manager edits report's review",   allowed(55, "UPDATE performance_reviews SET rating=3 WHERE id=1"), True)
expect("admin reviews report",            allowed(56, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (2, 56, 4)"), True)
expect("admin reviews self",              allowed(56, "INSERT INTO performance_reviews (user_id, reviewer_id, rating) VALUES (56, 56, 5)"), False)

# --------------------------------------------------------- attendance, assets
expect("clock yourself in",               allowed(2, "INSERT INTO attendance (user_id, status, date) VALUES (2, 'present', CURRENT_DATE)"), True)
expect("edit own attendance",             allowed(2, "UPDATE attendance SET status='present' WHERE id=1"), False)
expect("manager corrects attendance",     allowed(55, "UPDATE attendance SET status='present' WHERE id=1"), True)
expect("edit admin's attendance",         allowed(2, "UPDATE attendance SET status='present' WHERE id=2"), False)
expect("change own asset",                allowed(2, "UPDATE assets SET status='maintenance' WHERE id=1"), False)
expect("manager hands asset to a report", allowed(55, "UPDATE assets SET assigned_to=3 WHERE id=1"), True)
expect("add asset for yourself",          allowed(2, "INSERT INTO assets (asset_name, assigned_to) VALUES ('x', 2)"), False)

# ----------------------------------------------------------- announcements
expect("employee posts to dept",          allowed(2, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 2, 1)"), False)
expect("post company-wide",               allowed(2, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 2, NULL)"), False)
expect("post company-wide, no dept",      allowed(2, "INSERT INTO announcements (title, posted_by) VALUES ('t', 2)"), False)
expect("post under someone else's name",  allowed(2, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 56, 1)"), False)
expect("manager posts to own dept",       allowed(55, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 55, 1)"), True)
expect("manager posts as someone else",   allowed(55, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 2, 1)"), False)
expect("admin posts company-wide",        allowed(56, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 56, NULL)"), True)
expect("clock in, backdated",             allowed(2, "INSERT INTO attendance (user_id, status, date) VALUES (2, 'present', '2020-01-01')"), False)
expect("clock in, no date given",         allowed(2, "INSERT INTO attendance (user_id, status) VALUES (2, 'present')"), False)
expect("manager adds past attendance",    allowed(55, "INSERT INTO attendance (user_id, status, date) VALUES (2, 'present', '2020-01-01')"), True)
expect("manager deletes a review",        allowed(55, "DELETE FROM performance_reviews WHERE id=1"), False)
expect("admin deletes a review",          allowed(56, "DELETE FROM performance_reviews WHERE id=1"), True)
expect("manager deletes an asset",        allowed(55, "DELETE FROM assets WHERE id=1"), False)
expect("admin deletes an asset",          allowed(56, "DELETE FROM assets WHERE id=1"), True)
expect("admin posts company-wide",        allowed(56, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 56, NULL)"), True)
expect("edit own announcement",           allowed(2, "UPDATE announcements SET title='n' WHERE id=1"), True)
expect("edit company-wide announcement",  allowed(2, "UPDATE announcements SET title='n' WHERE id=2"), False)
expect("post to ANOTHER department",      allowed(2, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 2, 2)"), False)
expect("post to another company's department", allowed(2, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 2, 9)"), False)
expect("make own announcement company-wide by editing", allowed(2, "UPDATE announcements SET department_id=NULL WHERE id=1"), False)
expect("move own announcement to another department",   allowed(2, "UPDATE announcements SET department_id=2 WHERE id=1"), False)
expect("admin posts to another department, same company", allowed(56, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 56, 2)"), True)
expect("admin posts to another company's department", allowed(56, "INSERT INTO announcements (title, posted_by, department_id) VALUES ('t', 56, 9)"), False)

# -------------------------------------------------------------- projects
expect("project change by non-manager",   allowed(2, "UPDATE projects SET status='on_hold' WHERE id=1"), False)
expect("project change by manager",       allowed(55, "UPDATE projects SET status='on_hold' WHERE id=1"), True)
expect("project change by admin",         allowed(56, "UPDATE projects SET status='on_hold' WHERE id=1"), True)

# --------------------------------------------- company boundary (admin too)
expect("admin approves another company's expense", allowed(56, "UPDATE expenses SET status='approved' WHERE id=7"), False)
expect("admin assigns task to another company",    allowed(56, "UPDATE tasks SET assigned_to=30 WHERE id=1"), False)
expect("admin adds task for another company",      allowed(56, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 30)"), False)
expect("admin adds task for same company",         allowed(56, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 2)"), True)
expect("admin edits person with no department",    allowed(56, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 31)"), False)

# --------------------------------------------- company structure tables
expect("admin renames department",                 allowed(56, "UPDATE department SET name='Product' WHERE id=1"), True)
expect("manager renames department",               allowed(55, "UPDATE department SET name='Product' WHERE id=1"), False)
expect("admin renames other company's department", allowed(56, "UPDATE department SET name='Product' WHERE id=9"), False)
expect("admin deletes department",                 allowed(56, "DELETE FROM department WHERE id=1"), False)
expect("admin adds department to own company",     allowed(56, "INSERT INTO department (name, org_id) VALUES ('Ops', 1)"), True)
expect("admin adds department to other company",   allowed(56, "INSERT INTO department (name, org_id) VALUES ('Ops', 2)"), False)
expect("admin moves department to other company",  allowed(56, "UPDATE department SET org_id=2 WHERE id=1"), False)
expect("admin updates role in own company",        allowed(56, "UPDATE role SET title='Lead' WHERE id=1"), True)
expect("admin updates role of other company",      allowed(56, "UPDATE role SET title='Lead' WHERE id=9"), False)
expect("admin adds role to other company's dept",  allowed(56, "INSERT INTO role (title, department_id) VALUES ('x', 9)"), False)
expect("admin deletes role",                       allowed(56, "DELETE FROM role WHERE id=1"), False)
expect("manager edits role",                       allowed(55, "UPDATE role SET title='Lead' WHERE id=1"), False)
expect("admin renames own organization",           allowed(56, "UPDATE organization SET name='Acme' WHERE id=1"), True)
expect("admin renames other organization",         allowed(56, "UPDATE organization SET name='Acme' WHERE id=2"), False)
expect("admin creates an organization",            allowed(56, "INSERT INTO organization (name) VALUES ('New')"), False)
expect("admin deletes an organization",            allowed(56, "DELETE FROM organization WHERE id=1"), False)
expect("non-admin renames organization",           allowed(55, "UPDATE organization SET name='Acme' WHERE id=1"), False)

# --------------------------------------------- projects: admin or that department's manager
expect("manager of the department edits project", allowed(55, "UPDATE projects SET status='on_hold' WHERE id=1"), True)
expect("manager edits another department's project", allowed(55, "UPDATE projects SET status='on_hold' WHERE id=2"), False)
expect("sales manager edits sales project",       allowed(10, "UPDATE projects SET status='on_hold' WHERE id=2"), True)
expect("admin edits project in own company",      allowed(56, "UPDATE projects SET status='on_hold' WHERE id=2"), True)
expect("admin edits other company's project",     allowed(56, "UPDATE projects SET status='on_hold' WHERE id=3"), False)
expect("manager creates project in own dept",     allowed(55, "INSERT INTO projects (name, department_id) VALUES ('p', 1)"), True)
expect("manager creates project in other dept",   allowed(55, "INSERT INTO projects (name, department_id) VALUES ('p', 2)"), False)
expect("project with no department given",        allowed(55, "INSERT INTO projects (name) VALUES ('p')"), False)
expect("manager moves project to another dept",   allowed(55, "UPDATE projects SET department_id=2 WHERE id=1"), False)
expect("undo project change, manager",            revert(55, "projects", "UPDATE", [{"id": 1, "department_id": 1}]), None)
expect("undo department change, admin",           revert(56, "department", "UPDATE", [{"id": 1, "org_id": 1}]), None)
expect("undo department change, non-admin",      revert(55, "department", "UPDATE", [{"id": 1, "org_id": 1}]) is not None, True)

# -------------------------------------------------- everything else is refused
expect("audit log is never writable",     allowed(56, "UPDATE audit_log SET status='x' WHERE id=1"), False)
expect("users go through the employee tools", allowed(56, "UPDATE users SET name='x' WHERE id=1"), False)
expect("deactivated actor",               allowed(1, "UPDATE tasks SET status='done' WHERE id=1"), False)
expect("unknown actor",                   allowed(999, "UPDATE tasks SET status='done' WHERE id=1"), False)
expect("change the id column",            allowed(56, "UPDATE tasks SET id=9 WHERE id=1"), False)
expect("no WHERE is not verifiable",      kind_of(56, "UPDATE tasks SET status='done'"), "rewrite")
expect("UPDATE ... FROM is not verifiable", kind_of(56, "UPDATE tasks SET status='done' FROM x WHERE tasks.id=1"), "rewrite")
expect("DELETE ... USING not verifiable", kind_of(56, "DELETE FROM tasks USING x WHERE tasks.id=1"), "rewrite")
expect("ON CONFLICT not verifiable",       kind_of(2, "INSERT INTO tasks (title, assigned_to) VALUES ('x', 2) ON CONFLICT DO NOTHING"), "rewrite")
expect("INSERT without column list",      kind_of(2, "INSERT INTO tasks VALUES (1, 'x', 2)"), "rewrite")
expect("INSERT ... SELECT not verifiable", kind_of(2, "INSERT INTO tasks (title, assigned_to) SELECT 'x', 2"), "rewrite")
expect("data-modifying WITH not verifiable", kind_of(56, "WITH x AS (DELETE FROM tasks WHERE id=1 RETURNING *) SELECT * FROM x"), "rewrite")

# ----------------------------------------------------------- parser details
a = R._analyze_write("UPDATE tasks SET title='a, b', status='done' WHERE id IN (SELECT id FROM tasks WHERE assigned_to = 2) RETURNING id;")
expect("parser: assignments", [n for n, _ in a["assigns"]], ["title", "status"])
expect("parser: where",       a["where"], "id IN (SELECT id FROM tasks WHERE assigned_to = 2)")
a = R._analyze_write("INSERT INTO tasks (title, assigned_to) VALUES ('a, (b', 2), ('c', 3) RETURNING id")
expect("parser: insert rows", len(a["rows"]), 2)
expect("parser: public prefix", R._analyze_write('UPDATE public.tasks SET status=\'done\' WHERE id=1')["table"], "tasks")

# ------------------------------------------------------------------- reads
def read(actor, sql):
    return R._restrict_select(FakeCur(), actor, sql)

out, err = read(55, "SELECT * FROM expenses")
expect("manager sees own team only", err is None and "IN (2,3,55,56)" in out, True)
out, err = read(2, "SELECT * FROM expenses")
expect("employee sees only own rows", err is None and "IN (2)" in out, True)
out, err = read(56, "SELECT * FROM expenses")
expect("admin sees everything", (out, err), ("SELECT * FROM expenses", None))
out, err = read(55, "SELECT e.amount FROM expenses e JOIN users u ON u.id = e.submitted_by WHERE e.status = 'pending'")
expect("alias and join survive", err is None and "AS e JOIN users u ON u.id = e.submitted_by" in out, True)
out, err = read(55, "SELECT expenses.amount FROM expenses WHERE expenses.status = 'pending' LIMIT 5")
expect("qualified columns and LIMIT", err is None and "AS expenses WHERE expenses.status" in out and out.endswith("LIMIT 5"), True)
out, err = read(55, "SELECT * FROM public.expenses e")
expect("schema prefix", err is None and "AS e" in out, True)
out, err = read(55, "SELECT * FROM users WHERE id IN (SELECT submitted_by FROM expenses)")
expect("subquery is restricted too", err is None and "IN (2,3,55,56)" in out, True)
out, err = read(55, "SELECT * FROM performance_reviews pr JOIN leave_requests lr ON lr.user_id = pr.user_id")
expect("two protected tables", err is None and out.count("(SELECT * FROM") == 2, True)
out, err = read(55, "SELECT * FROM tasks WHERE title = 'from expenses'")
expect("table name inside a string is ignored", (out, err), ("SELECT * FROM tasks WHERE title = 'from expenses'", None))
out, err = read(55, "SELECT * FROM users u, expenses e WHERE u.id = e.submitted_by")
expect("comma join is refused", err is not None, True)
out, err = read(55, 'SELECT * FROM "expenses"')
expect("quoted name is refused", err is not None, True)
out, err = read(55, "SELECT * FROM ONLY expenses")
expect("FROM ONLY is refused", err is not None, True)
out, err = read(2, "SELECT * FROM audit_log")
expect("audit log, non-admin", err is not None, True)
out, err = read(56, "SELECT * FROM audit_log")
expect("audit log, admin", (out, err), ("SELECT * FROM audit_log", None))
out, err = read(1, "SELECT * FROM expenses")
expect("deactivated reader", err is not None, True)

# ----------------------------------------------------------------- reverts

row1 = {"id": 1, "submitted_by": 2, "status": "pending", "amount": 10}
expect("undo own approval-table change", revert(2, "expenses", "UPDATE", [row1]) is not None, True)
expect("manager undoes it",              revert(55, "expenses", "UPDATE", [row1]), None)
expect("undo own task change",           revert(2, "tasks", "UPDATE", [{"id": 1, "assigned_to": 2, "status": "pending"}]), None)
expect("undo someone else's task",       revert(2, "tasks", "UPDATE", [{"id": 2, "assigned_to": 55}]) is not None, True)
expect("undo own pending insert",        revert(2, "expenses", "INSERT", None, [1]), None)
expect("undo own approved insert",       revert(2, "expenses", "INSERT", None, [2]) is not None, True)
expect("undo on unknown table",          revert(56, "audit_log", "UPDATE", [{"id": 1}]) is not None, True)
expect("undo, unknown operation",        revert(56, "tasks", "TRUNCATE", [{"id": 1}]) is not None, True)
expect("undo an approved delete (row was final)", revert(55, "expenses", "DELETE", [{"id": 2, "submitted_by": 2, "status": "approved"}]) is not None, True)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)