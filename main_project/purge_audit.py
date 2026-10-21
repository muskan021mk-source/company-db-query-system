"""
Deletes audit_log rows older than N days. Run by a scheduler, NOT by the agent.

Uses its OWN database login (audit_cleaner), which can only SELECT and DELETE
on audit_log. app_agent must never get DELETE on audit_log.

Usage:
    python purge_audit.py --dry-run     # only count what WOULD be deleted
    python purge_audit.py               # actually delete

.env variables used:
    POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT   (already in your .env)
    AUDIT_CLEANER_USER, AUDIT_CLEANER_PASSWORD  (new)
    AUDIT_RETENTION_DAYS                        (optional, default 180)
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "180"))
BATCH = 5000
DRY_RUN = "--dry-run" in sys.argv

if DAYS < 30:
    sys.exit("Refusing to run: retention under 30 days looks like a mistake.")

conn = psycopg2.connect(
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("AUDIT_CLEANER_USER"),
    password=os.getenv("AUDIT_CLEANER_PASSWORD"),
    host=os.getenv("POSTGRES_HOST"),
    port=os.getenv("POSTGRES_PORT"),
)
cur = conn.cursor()

cur.execute("SELECT current_user")
print("Connected as:", cur.fetchone()[0])

cur.execute(
    "SELECT count(*), min(occurred_at), max(occurred_at) FROM audit_log "
    "WHERE occurred_at < now() - make_interval(days => %s)", (DAYS,))
count, oldest, newest = cur.fetchone()
print(f"Rows older than {DAYS} days: {count} (oldest {oldest}, newest {newest})")

if DRY_RUN or count == 0:
    print("Dry run or nothing to delete. No changes made.")
    conn.close()
    sys.exit(0)

total = 0
while True:
    cur.execute(
        """
        DELETE FROM audit_log WHERE id IN (
            SELECT id FROM audit_log
            WHERE occurred_at < now() - make_interval(days => %s)
            ORDER BY id LIMIT %s
        )
        """, (DAYS, BATCH))
    deleted = cur.rowcount
    conn.commit()
    total += deleted
    if deleted < BATCH:
        break

print(f"Deleted {total} audit rows older than {DAYS} days.")
conn.close()