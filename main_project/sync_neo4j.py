"""
Full sync: Postgres (company_db) -> Neo4j

Graph model:
  (:User)-[:REPORTS_TO]->(:User)
  (:User)-[:IN_DEPARTMENT]->(:Department)
  (:User)-[:HAS_ROLE]->(:Role)-[:BELONGS_TO]->(:Department)

Install:  pip install psycopg2-binary neo4j python-dotenv
Run:      python sync_neo4j.py
Safe to re-run (MERGE + stale cleanup).
"""
import os
import datetime
import psycopg2
import psycopg2.extras
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

PG_DSN = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/company_db")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")


def clean(v):
    if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
        return v.isoformat()
    return v


def fetch(cur, sql):
    cur.execute(sql)
    return [{k: clean(v) for k, v in row.items()} for row in cur.fetchall()]


def load_postgres():
    with psycopg2.connect(PG_DSN) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            departments = fetch(cur, "SELECT id, name FROM department")
            roles = fetch(cur, "SELECT id, title, department_id FROM role")
            users = fetch(cur, """
                SELECT id, name, email, role_id, department_id, manager_id,
                       joined_at, is_active
                FROM users
            """)
    return departments, roles, users


def sync(departments, roles, users):
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    with driver.session() as s:
        for label in ("User", "Department", "Role"):
            s.run(f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                  f"FOR (n:{label}) REQUIRE n.id IS UNIQUE")

        s.run("UNWIND $rows AS r MERGE (d:Department {id: r.id}) SET d.name = r.name",
              rows=departments)
        s.run("UNWIND $rows AS r MERGE (x:Role {id: r.id}) SET x.title = r.title",
              rows=roles)
        s.run("UNWIND $rows AS r MERGE (e:User {id: r.id}) "
              "SET e.name = r.name, e.email = r.email, e.department_id = r.department_id, "
              "e.joined_at = r.joined_at, e.is_active = r.is_active",
              rows=users)

        # rebuild all relationships from scratch so the graph always mirrors Postgres
        s.run("MATCH ()-[r:REPORTS_TO|IN_DEPARTMENT|HAS_ROLE|BELONGS_TO]->() DELETE r")

        s.run("UNWIND $rows AS r MATCH (x:Role {id: r.id}) "
              "MATCH (d:Department {id: r.department_id}) MERGE (x)-[:BELONGS_TO]->(d)",
              rows=[r for r in roles if r["department_id"] is not None])
        s.run("UNWIND $rows AS r MATCH (e:User {id: r.id}) "
              "MATCH (d:Department {id: r.department_id}) MERGE (e)-[:IN_DEPARTMENT]->(d)",
              rows=[u for u in users if u["department_id"] is not None])
        s.run("UNWIND $rows AS r MATCH (e:User {id: r.id}) "
              "MATCH (x:Role {id: r.role_id}) MERGE (e)-[:HAS_ROLE]->(x)",
              rows=[u for u in users if u["role_id"] is not None])
        with_mgr = [u for u in users if u["manager_id"] is not None]
        s.run("UNWIND $rows AS r MATCH (e:User {id: r.id}) "
              "MATCH (m:User {id: r.manager_id}) WHERE e <> m "
              "MERGE (e)-[:REPORTS_TO]->(m)",
              rows=with_mgr)

        # remove anything deleted from Postgres
        for label, rows in (("User", users), ("Department", departments), ("Role", roles)):
            s.run(f"MATCH (n:{label}) WHERE NOT n.id IN $ids DETACH DELETE n",
                  ids=[r["id"] for r in rows])

        report(s, departments, roles, users, with_mgr)
    driver.close()


def count(s, q):
    return s.run(q).single()["c"]


def report(s, departments, roles, users, with_mgr):
    emp = count(s, "MATCH (e:User) RETURN count(e) AS c")
    dep = count(s, "MATCH (d:Department) RETURN count(d) AS c")
    rol = count(s, "MATCH (r:Role) RETURN count(r) AS c")
    rel = count(s, "MATCH ()-[r:REPORTS_TO]->() RETURN count(r) AS c")
    tops = s.run("MATCH (e:User) WHERE NOT (e)-[:REPORTS_TO]->() "
                 "RETURN e.id AS id, e.name AS name").data()
    cycles = count(s, "MATCH (e:User)-[:REPORTS_TO*1..]->(e) "
                      "RETURN count(DISTINCT e) AS c")

    print(f"\nDone: {emp} employees, {dep} departments, {rol} roles synced.")
    print("\n=== Sync report ===")
    print(f"Postgres users:           {len(users)}   Neo4j employees: {emp}")
    print(f"Users with a manager:     {len(with_mgr)}   REPORTS_TO links: {rel}")
    print(f"Top-level people:         {len(tops)}  -> {[t['name'] for t in tops]}")
    print(f"People in a cycle:        {cycles}  (must be 0)")

    # active employees whose manager is deactivated (nobody active above them)
    orphans = s.run(
        "MATCH (e:User {is_active: true})-[:REPORTS_TO]->(m:User {is_active: false}) "
        "RETURN e.name AS emp, m.name AS mgr"
    ).data()
    print(f"Active people whose manager is deactivated: {len(orphans)}")
    for o in orphans:
        print(f"  - {o['emp']} (manager: {o['mgr']})")

    if emp != len(users): print("WARNING: employee count differs from Postgres")
    if rel != len(with_mgr): print("WARNING: some manager_id values point to missing users")
    if cycles: print("WARNING: reporting cycles found")
    if orphans: print("WARNING: reassign these people to an active manager")


if __name__ == "__main__":
    d, r, u = load_postgres()
    print(f"Fetched {len(u)} users, {len(d)} departments, {len(r)} roles")
    sync(d, r, u)