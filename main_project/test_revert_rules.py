"""
test_revert_rules.py

Checks the new undo rule for the users table against your real data.
It only READS the database. It never changes anything, because it calls the permission
check directly and never runs an undo. (Denied cases write a 'DENIED' line to audit_log.)

Run from the project folder, venv active, AFTER patch_revert_rules.py:
    python test_revert_rules.py
or with your own ids:
    python test_revert_rules.py <admin_id> <manager_id> <report_id> <outsider_id>

Defaults: admin=56 (HR/admin), manager=10 (Catherine Perkins), report=11 (one of her
reports), outsider=64 (not above the report).
"""
import sys

import permissions
from mcp_tools import get_connection, release_connection

ADMIN, MANAGER, REPORT, OUTSIDER = 56, 10, 11, 64
if len(sys.argv) == 5:
    ADMIN, MANAGER, REPORT, OUTSIDER = (int(x) for x in sys.argv[1:5])

COLS = ["id", "name", "email", "role_id", "department_id", "manager_id", "joined_at",
        "is_active", "deactivated_at", "deactivated_by", "is_hr_admin"]


def current_row(uid):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT " + ", ".join(COLS) + " FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        other_dept = None
        cur.execute("SELECT id FROM department WHERE id <> %s ORDER BY id LIMIT 1", (row[COLS.index("department_id")],))
        r = cur.fetchone()
        if r:
            other_dept = r[0]
        cur.close()
        return dict(zip(COLS, row)), other_dept
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        release_connection(conn)


base, other_dept = current_row(REPORT)
# a manager id that is DIFFERENT from the report's current one, so the undo really changes it
other_manager = ADMIN if base["manager_id"] != ADMIN else OUTSIDER
results = []


def case(label, actor_id, snap_changes, operation, expect_allowed):
    snap = dict(base)
    snap.update(snap_changes)          # what the row looked like BEFORE the change
    out = permissions.check_revert_users((actor_id, "test"), "test-thread", operation, [snap])
    allowed = out is None
    ok = allowed == expect_allowed
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"      expected {'allowed' if expect_allowed else 'refused'}, got "
              f"{'allowed' if allowed else 'refused'}: {out}")


case("admin undoes a name change",                          ADMIN,   {"name": "OLD NAME"},            "UPDATE", True)
case("admin undoes a department change",                    ADMIN,   {"department_id": other_dept},   "UPDATE", True)
case("manager undoes a name change to their report",        MANAGER, {"name": "OLD NAME"},            "UPDATE", True)
case("manager cannot undo a department change",             MANAGER, {"department_id": other_dept},   "UPDATE", False)
case("manager cannot undo a manager change",                MANAGER, {"manager_id": other_manager},         "UPDATE", False)
case("manager cannot undo an email change",                 MANAGER, {"email": "old@example.com"},    "UPDATE", False)
case("manager cannot undo a name AND department change",    MANAGER, {"name": "OLD NAME", "department_id": other_dept}, "UPDATE", False)
case("manager cannot undo the creation of an employee",     MANAGER, {},                              "INSERT", False)
case("someone not above the person cannot undo a name change", OUTSIDER, {"name": "OLD NAME"},        "UPDATE", False)
case("a person cannot undo a change to their own record",   REPORT,  {"name": "OLD NAME"},            "UPDATE", False)

print()
print(f"{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)