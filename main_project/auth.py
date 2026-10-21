import os
import secrets
import string
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET or len(JWT_SECRET) < 32 or JWT_SECRET == "change-me-in-production":
    raise RuntimeError("JWT_SECRET must be set in .env to a long random value (32+ characters).")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24
RESET_TOKEN_EXPIRE_HOURS = 1
OTP_EXPIRE_MINUTES = 10
MAX_OTP_ATTEMPTS = 5

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

PG_HOST = os.getenv("POSTGRES_HOST", "localhost")
PG_DB = os.getenv("POSTGRES_DB", "company_db")
PG_USER = os.getenv("POSTGRES_USER", "postgres")
PG_PASS = os.getenv("POSTGRES_PASSWORD", "")
PG_PORT = int(os.getenv("POSTGRES_PORT", "5432"))

print(f"[STARTUP] PG Config: host={PG_HOST} db={PG_DB} user={PG_USER} port={PG_PORT}")
print(f"[STARTUP] FRONTEND_URL={FRONTEND_URL}")

security = HTTPBearer()

# ─── DB imports ───────────────────────────────────────────────────────────────

def _users():
    from db import users_collection
    return users_collection()


def _otps():
    from db import otps_collection
    return otps_collection()

# ─── Datetime helper ──────────────────────────────────────────────────────────

def _as_utc(dt: datetime) -> datetime:
    """Mongo returns naive datetimes by default; treat them as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

# ─── PostgreSQL helpers ───────────────────────────────────────────────────────

def _get_pg_connection():
    try:
        return psycopg2.connect(
            host=PG_HOST,
            dbname=PG_DB,
            user=PG_USER,
            password=PG_PASS,
            port=PG_PORT,
        )
    except Exception as e:
        print(f"[PG CONNECTION ERROR] {e}")
        raise


def _check_employee_in_pg(email: str) -> dict | None:
    """
    Looks up the active employee record for `email` in Postgres.
    The numeric `id` primary key IS the employee ID (no separate column).
    """
    conn = None
    try:
        print(f"[PG] Checking email: {email}")
        conn = _get_pg_connection()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.name, u.email, u.is_active,
                   d.name AS department_name,
                   r.title AS role_name
            FROM users u
            LEFT JOIN department d ON u.department_id = d.id
            LEFT JOIN role r ON u.role_id = r.id
            WHERE u.email = %s AND u.is_active = true
            """,
            (email,),
        )
        row = cur.fetchone()
        cur.close()

        if not row:
            print(f"[PG] No active employee found for: {email}")
            return None

        full_name = (row[1] or "").strip()
        name_parts = full_name.split(" ", 1)
        pg_first_name = name_parts[0] if name_parts else ""
        pg_last_name = name_parts[1] if len(name_parts) > 1 else ""

        return {
            "id": row[0],
            "name": row[1],
            "first_name": pg_first_name,
            "last_name": pg_last_name,
            "email": row[2],
            "is_active": row[3],
            "employee_id": row[0],
            "department": row[4] or "Unknown",
            "role": row[5] or "Employee",
        }
    except Exception as e:
        print(f"[PG ERROR] {e}")
        return None
    finally:
        if conn:
            conn.close()

# ─── Departments (dynamic, live from Postgres) ────────────────────────────────

def _fetch_departments_from_pg() -> list[str]:
    conn = None
    try:
        conn = _get_pg_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM department ORDER BY name")
        rows = cur.fetchall()
        cur.close()
        return [r[0] for r in rows]
    except Exception as e:
        print(f"[PG ERROR] {e}")
        return []
    finally:
        if conn:
            conn.close()


async def get_departments():
    """
    Wire to a GET route, e.g.:

        @router.get("/departments")
        async def departments_route():
            return await get_departments()
    """
    departments = await asyncio.to_thread(_fetch_departments_from_pg)
    return {"success": True, "departments": departments}

# ─── Field verification helpers ───────────────────────────────────────────────

def _normalize(value) -> str:
    return str(value or "").strip().casefold()


def _extract_digits(value) -> str:
    """'56', 'EMP-56', 'emp 56' all reduce to '56'."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _verify_employee_identity(
    email: str,
    firstName: str,
    lastName: str,
    employeeId: str,
    department: str,
) -> dict:
    """
    Chain: email -> first name -> employee ID -> department -> last name (optional),
    all checked against the SAME Postgres row fetched from the email.

    Returns {"employee": dict | None, "errors": list[str]}.
    """
    errors: list[str] = []

    employee = _check_employee_in_pg(email)
    if not employee:
        errors.append("Email is not registered in the company database.")
        return {"employee": None, "errors": errors}

    if _normalize(firstName) != _normalize(employee["first_name"]):
        errors.append("First name does not match our records.")

    if _extract_digits(employeeId) != _extract_digits(employee["employee_id"]):
        errors.append("Employee ID does not match our records.")

    if _normalize(department) != _normalize(employee["department"]):
        errors.append("Department does not match our records.")

    if lastName and _normalize(lastName) != _normalize(employee["last_name"]):
        errors.append("Last name does not match our records.")

    return {"employee": employee, "errors": errors}

# ─── Email sender ─────────────────────────────────────────────────────────────

def _send_email_sync(to: str, subject: str, body: str):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to, msg.as_string())


async def send_email(to: str, subject: str, body: str):
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL] To: {to} | Subject: {subject}\n{body}")
        return
    try:
        await asyncio.to_thread(_send_email_sync, to, subject, body)
        print(f"[EMAIL] Sent to {to}")
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")

# ─── Password helpers ─────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

# ─── JWT helpers ──────────────────────────────────────────────────────────────

def create_token(user_id: str, email: str, expires_delta: timedelta | None = None,
                 token_type: str = "access") -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))
    payload = {"sub": user_id, "email": email, "exp": expire, "typ": token_type}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str, expected_type: str = "access") -> dict:
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM],
            options={"require_exp": True, "require_sub": True},
        )
        if payload.get("typ") != expected_type or not payload.get("email"):
            raise JWTError("wrong token type")
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

# ─── Dependencies ─────────────────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    payload = decode_token(credentials.credentials)
    user = await _users().find_one({"email": payload["email"]})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    payload = decode_token(credentials.credentials)
    return payload["sub"]

# ─── OTP ──────────────────────────────────────────────────────────────────────

def _generate_otp(length: int = 6) -> str:
    # secrets (not random) because this is a security code
    return "".join(secrets.choice(string.digits) for _ in range(length))


async def _validate_otp(email: str, purpose: str, otp: str):
    """Checks existence, expiry, and value of the latest OTP for this purpose."""
    recent_otp = await _otps().find_one(
        {"email": email, "purpose": purpose}, sort=[("createdAt", -1)]
    )
    if not recent_otp:
        raise HTTPException(status_code=400, detail="OTP not found, please request a new one")

    created = _as_utc(recent_otp["createdAt"])
    if datetime.now(timezone.utc) > created + timedelta(minutes=OTP_EXPIRE_MINUTES):
        await _otps().delete_many({"email": email, "purpose": purpose})
        raise HTTPException(status_code=400, detail="OTP has expired, please request a new one")

    counted = await _otps().find_one_and_update(
        {"_id": recent_otp["_id"]}, {"$inc": {"attempts": 1}}, return_document=True
    )
    if counted is None or counted.get("attempts", 0) > MAX_OTP_ATTEMPTS:
        await _otps().delete_many({"email": email, "purpose": purpose})
        raise HTTPException(status_code=400, detail="Too many attempts. Please request a new OTP.")

    if not secrets.compare_digest(str(otp), str(recent_otp["otp"])):
        raise HTTPException(status_code=400, detail="Invalid OTP")

# ─── Auth operations ──────────────────────────────────────────────────────────

async def send_otp(
    email: str,
    firstName: str = "",
    lastName: str = "",
    employeeId: str = "",
    department: str = "",
    check_user_present: bool = True,
):
    if check_user_present:
        existing = await _users().find_one({"email": email})
        if existing:
            raise HTTPException(status_code=409, detail="User already registered")

    result = await asyncio.to_thread(
        _verify_employee_identity, email, firstName, lastName, employeeId, department
    )

    employee = result["employee"]
    if employee is None:
        raise HTTPException(
            status_code=403,
            detail="Your email is not registered in the company database. Contact your administrator.",
        )

    if result["errors"]:
        raise HTTPException(status_code=400, detail=" ".join(result["errors"]))

    last_otp = await _otps().find_one(
        {"email": email, "purpose": "signup"}, sort=[("createdAt", -1)]
    )
    if last_otp and datetime.now(timezone.utc) < _as_utc(last_otp["createdAt"]) + timedelta(seconds=60):
        raise HTTPException(status_code=429, detail="Please wait a minute before requesting another OTP.")

    otp = _generate_otp()
    await _otps().delete_many({"email": email, "purpose": "signup"})
    await _otps().insert_one({
        "email": email,
        "otp": otp,
        "purpose": "signup",
        "createdAt": datetime.now(timezone.utc),
    })

    await send_email(
        to=email,
        subject="Your Verification OTP",
        body=f"""
        <h2>Company Database Query System</h2>
        <p>Hello {employee['name']},</p>
        <p>Your OTP for email verification is:</p>
        <h1 style="letter-spacing:8px;color:#c9974d">{otp}</h1>
        <p>This OTP is valid for {OTP_EXPIRE_MINUTES} minutes.</p>
        <p>If you did not request this, please ignore this email.</p>
        """,
    )

    return {"success": True, "message": "OTP sent successfully"}


async def sign_up(
    firstName: str,
    lastName: str,
    email: str,
    employeeId: str,
    department: str,
    password: str,
    confirmPassword: str,
    otp: str,
):
    # lastName is optional; only enforced by _verify_employee_identity if provided.
    if not all([firstName, email, employeeId, department, password, confirmPassword, otp]):
        raise HTTPException(status_code=403, detail="All fields are required")

    if password != confirmPassword:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    if await _users().find_one({"email": email}):
        raise HTTPException(status_code=409, detail="Email already registered")

    result = await asyncio.to_thread(
        _verify_employee_identity, email, firstName, lastName, employeeId, department
    )

    if result["employee"] is None:
        raise HTTPException(
            status_code=403,
            detail="Your email is not registered in the company database. Contact your administrator.",
        )

    if result["errors"]:
        raise HTTPException(status_code=400, detail=" ".join(result["errors"]))

    employee = result["employee"]

    await _validate_otp(email, "signup", otp)

    now = datetime.now(timezone.utc)
    final_last_name = employee["last_name"] or lastName
    await _users().insert_one({
        "firstName": firstName,
        "lastName": final_last_name,
        "name": employee["name"],
        "email": email,
        "employeeId": str(employee["employee_id"]),
        "department": employee.get("department", department),
        "role": employee.get("role", "Employee"),
        "password": hash_password(password),
        "image": f"https://api.dicebear.com/5.x/initials/svg?seed={firstName} {final_last_name}",
        "createdAt": now,
    })

    await _otps().delete_many({"email": email, "purpose": "signup"})
    return {"success": True, "message": "Account created successfully"}


# --- Login lockout (added by patch_login_lockout.py) -------------------------
MAX_LOGIN_ATTEMPTS = 5            # wrong passwords allowed per email
LOGIN_LOCK_MINUTES = 15           # how long the email stays locked after that
LOGIN_HIDE_EMAIL_STATUS = True    # True: same message for unknown email and wrong password
LOGIN_FAILED_MESSAGE = "Incorrect email or password."
_LOGIN_ATTEMPT_TTL_SECONDS = 3600
_attempt_index_ready = False
_DUMMY_HASH = hash_password("not-a-real-password")   # keeps timing similar for unknown emails


def _login_attempts():
    from db import get_db
    return get_db()["login_attempts"]


def _login_key(email) -> str:
    return (email or "").strip().lower()


async def _ensure_attempt_index():
    global _attempt_index_ready
    if _attempt_index_ready:
        return
    try:
        await _login_attempts().create_index(
            "updatedAt", expireAfterSeconds=_LOGIN_ATTEMPT_TTL_SECONDS)
        _attempt_index_ready = True
    except Exception:
        pass   # cleanup index is a nice-to-have; never block a login because of it


async def _check_login_lock(key: str) -> None:
    await _ensure_attempt_index()
    doc = await _login_attempts().find_one({"_id": key})
    if not doc:
        return
    locked_until = doc.get("lockedUntil")
    if not locked_until:
        return
    until = _as_utc(locked_until)
    now = datetime.now(timezone.utc)
    if now < until:
        minutes = max(1, int((until - now).total_seconds() // 60) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed login attempts. Please try again in {minutes} minute(s).",
        )
    await _login_attempts().delete_one({"_id": key})   # lock has expired: start fresh


async def _record_failed_login(key: str) -> None:
    now = datetime.now(timezone.utc)
    doc = await _login_attempts().find_one_and_update(
        {"_id": key},
        {"$inc": {"count": 1}, "$set": {"updatedAt": now}},
        upsert=True,
        return_document=True,
    )
    if doc and doc.get("count", 0) >= MAX_LOGIN_ATTEMPTS:
        await _login_attempts().update_one(
            {"_id": key},
            {"$set": {"lockedUntil": now + timedelta(minutes=LOGIN_LOCK_MINUTES)}},
        )


async def _clear_failed_logins(key: str) -> None:
    await _login_attempts().delete_one({"_id": key})


async def login(email: str, password: str):
    if not email or not password:
        raise HTTPException(status_code=403, detail="All fields are required")

    key = _login_key(email)
    await _check_login_lock(key)

    user = await _users().find_one({"email": email})
    if not user:
        await _record_failed_login(key)
        if not LOGIN_HIDE_EMAIL_STATUS:
            employee = await asyncio.to_thread(_check_employee_in_pg, email)
            if employee:
                raise HTTPException(
                    status_code=404,
                    detail="You have not signed up yet. Please sign up first.",
                )
            raise HTTPException(
                status_code=404,
                detail="This email is not registered in the company database.",
            )
        verify_password(password, _DUMMY_HASH)   # same work as a real check
        raise HTTPException(status_code=401, detail=LOGIN_FAILED_MESSAGE)

    if not verify_password(password, user["password"]):
        await _record_failed_login(key)
        raise HTTPException(
            status_code=401,
            detail=LOGIN_FAILED_MESSAGE if LOGIN_HIDE_EMAIL_STATUS else "Incorrect password",
        )

    await _clear_failed_logins(key)

    employee = await asyncio.to_thread(_check_employee_in_pg, email)
    if not employee:
        raise HTTPException(
            status_code=403,
            detail="Your account has been deactivated. Contact your administrator.",
        )

    token = create_token(str(user["_id"]), user["email"])

    user_data = {
        "name": user.get("name", f"{user['firstName']} {user['lastName']}"),
        "firstName": user["firstName"],
        "lastName": user["lastName"],
        "email": user["email"],
        "employeeId": user.get("employeeId", ""),
        "department": user.get("department", employee.get("department", "")),
        "role": user.get("role", employee.get("role", "Employee")),
        "image": user.get("image", ""),
    }

    return {
        "success": True,
        "access_token": token,
        "token": token,
        "user": user_data,
        "message": "Login successful",
    }


async def get_user_details(current_user: dict):
    user_data = {
        "name": current_user.get("name", f"{current_user['firstName']} {current_user['lastName']}"),
        "firstName": current_user["firstName"],
        "lastName": current_user["lastName"],
        "email": current_user["email"],
        "employeeId": current_user.get("employeeId", ""),
        "department": current_user.get("department", ""),
        "role": current_user.get("role", ""),
        "image": current_user.get("image", ""),
    }
    return {"success": True, "data": {"user": user_data}}


async def change_password(
    current_user: dict,
    old_password: str,
    new_password: str,
    confirm_new_password: str,
):
    if not verify_password(old_password, current_user["password"]):
        raise HTTPException(status_code=401, detail="Old password is incorrect")

    if new_password != confirm_new_password:
        raise HTTPException(status_code=400, detail="New passwords do not match")

    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    await _users().update_one(
        {"_id": current_user["_id"]},
        {"$set": {"password": hash_password(new_password)}},
    )
    return {"success": True, "message": "Password updated successfully"}


async def reset_password_token(email: str):
    user = await _users().find_one({"email": email})
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email")

    token = create_token(
        str(user["_id"]), email,
        expires_delta=timedelta(hours=RESET_TOKEN_EXPIRE_HOURS),
        token_type="reset",
    )
    await _users().update_one(
        {"_id": user["_id"]},
        {"$set": {
            "resetToken": token,
            "resetTokenExpiry": datetime.now(timezone.utc) + timedelta(hours=RESET_TOKEN_EXPIRE_HOURS),
        }},
    )

    reset_link = f"{FRONTEND_URL}/update-password/{token}"
    await send_email(
        to=email,
        subject="Reset Your Password",
        body=f"""
        <h2>Company Database Query System</h2>
        <p>Click the link below to reset your password:</p>
        <a href="{reset_link}" style="color:#c9974d">{reset_link}</a>
        <p>This link expires in {RESET_TOKEN_EXPIRE_HOURS} hour.</p>
        <p>If you did not request this, please ignore this email.</p>
        """,
    )
    return {"success": True, "message": "Reset email sent"}


async def reset_password(
    password: str,
    confirmPassword: str,
    resetPasswordToken: str,
):
    if password != confirmPassword:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    payload = decode_token(resetPasswordToken, expected_type="reset")
    user = await _users().find_one({"email": payload["email"]})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.get("resetToken") != resetPasswordToken:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    expiry = user.get("resetTokenExpiry")
    if not expiry or datetime.now(timezone.utc) > _as_utc(expiry):
        raise HTTPException(status_code=400, detail="Reset token has expired")

    await _users().update_one(
        {"_id": user["_id"]},
        {"$set": {"password": hash_password(password)},
         "$unset": {"resetToken": "", "resetTokenExpiry": ""}},
    )
    return {"success": True, "message": "Password reset successfully"}

# ─── Account deletion ─────────────────────────────────────────────────────────

async def send_account_deletion_otp(current_user: dict):
    """
    Sends a confirmation code to the logged-in user's own email.
    Tagged purpose:"delete_account" so it can't be reused for signup.
    """
    email = current_user["email"]

    otp = _generate_otp()
    await _otps().delete_many({"email": email, "purpose": "delete_account"})
    await _otps().insert_one({
        "email": email,
        "otp": otp,
        "purpose": "delete_account",
        "createdAt": datetime.now(timezone.utc),
    })

    first_name = current_user.get("firstName", "")
    await send_email(
        to=email,
        subject="Confirm Account Deletion",
        body=f"""
        <h2>Company Database Query System</h2>
        <p>Hello {first_name},</p>
        <p>We received a request to permanently delete your account.</p>
        <p>Your confirmation code is:</p>
        <h1 style="letter-spacing:8px;color:#c9974d">{otp}</h1>
        <p>This code is valid for {OTP_EXPIRE_MINUTES} minutes. If you did not request this, please ignore this email — your account will not be affected.</p>
        """,
    )

    return {"success": True, "message": "Deletion confirmation OTP sent to your email"}


async def delete_account(current_user: dict, otp: str):
    """
    Permanently deletes the logged-in user's account.
    Requires a valid, unexpired OTP sent to that user's own email.
    """
    if not otp:
        raise HTTPException(status_code=400, detail="OTP is required")

    email = current_user["email"]

    await _validate_otp(email, "delete_account", otp)

    await _users().delete_one({"_id": current_user["_id"]})
    await _otps().delete_many({"email": email, "purpose": "delete_account"})

    return {"success": True, "message": "Account deleted successfully"}