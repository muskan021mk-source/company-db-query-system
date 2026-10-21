"""
test_login_lockout.py

Tests the login lockout by calling auth.login() directly (no server needed).
Run from the project folder, venv active, AFTER patch_login_lockout.py.
MongoDB must be running (Postgres is only used if you pass a real account).

Test 1 (always): a made-up email gets 5 wrong tries, then is locked.
    python test_login_lockout.py

Test 2 (optional, uses a REAL account you own):
    python test_login_lockout.py <real_email> <real_password>
  5 wrong passwords, then the CORRECT password must still be refused (locked).
  The script then clears the counter and checks the correct password works again.
  No data is changed except the small login_attempts record, which it deletes.
"""
import asyncio
import sys

from fastapi import HTTPException

import auth

if not hasattr(auth, "MAX_LOGIN_ATTEMPTS"):
    print("auth.py has no lockout yet. Run patch_login_lockout.py first.")
    sys.exit(1)

MAX = auth.MAX_LOGIN_ATTEMPTS
results = []


def record(label, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail and not ok else ""))


async def attempt(email, password):
    """returns (status_code, detail) ; 200 on success"""
    try:
        await auth.login(email, password)
        return 200, "ok"
    except HTTPException as e:
        return e.status_code, str(e.detail)


async def clear(email):
    await auth._login_attempts().delete_one({"_id": auth._login_key(email)})


async def main():
    # ---------- Test 1: an email that does not exist ----------
    fake = "lockout.test@example.invalid"
    await clear(fake)
    codes = [(await attempt(fake, f"wrong{i}"))[0] for i in range(MAX)]
    record(f"{MAX} wrong tries on an unknown email all give 401", codes == [401] * MAX, str(codes))

    status, detail = await attempt(fake, "wrong-again")
    record("the next try is refused with 429 (locked)", status == 429, f"{status} {detail}")

    status, detail = await attempt(fake.upper(), "wrong-again")
    record("changing the letter case does not get around the lock", status == 429, f"{status} {detail}")

    if auth.LOGIN_HIDE_EMAIL_STATUS:
        other = "someone.else@example.invalid"
        await clear(other)
        s1, d1 = await attempt(other, "x")
        await clear(fake)
        s2, d2 = await attempt(fake, "x")
        record("unknown emails all get the same message", (s1, d1) == (s2, d2), f"{d1} / {d2}")
        await clear(other)

    await clear(fake)

    # ---------- Test 2: a real account (optional) ----------
    if len(sys.argv) == 3:
        email, good = sys.argv[1], sys.argv[2]
        await clear(email)
        codes = [(await attempt(email, f"definitely-wrong-{i}"))[0] for i in range(MAX)]
        record(f"{MAX} wrong passwords on your real account give 401", codes == [401] * MAX, str(codes))
        status, detail = await attempt(email, good)
        record("the CORRECT password is refused while locked (429)", status == 429, f"{status} {detail}")
        await clear(email)
        status, detail = await attempt(email, good)
        record("after the counter is cleared the correct password works", status == 200, f"{status} {detail}")
        await clear(email)
    else:
        print("(skipped real-account test: pass <email> <password> to run it)")

    print()
    print(f"{sum(results)} of {len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    code = asyncio.run(main())
    try:
        from db import close_client
        close_client()
    except Exception:
        pass
    sys.exit(code)