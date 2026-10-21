from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from typing import Optional

from auth import (
    login,
    sign_up,
    send_otp,
    change_password,
    reset_password_token,
    reset_password,
    get_current_user,
    get_user_details,
    get_departments,
    send_account_deletion_otp,
    delete_account,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ─── Request Models ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class SignupRequest(BaseModel):
    firstName: str
    lastName: Optional[str] = ""
    email: EmailStr
    employeeId: str
    department: str
    password: str
    confirmPassword: str
    otp: str

class SendOTPRequest(BaseModel):
    # firstName/employeeId/department are required here (not just at
    # signup) because send_otp() now runs the same chained identity
    # check against Postgres BEFORE issuing an OTP, so a stranger can't
    # get an OTP for an email/identity that doesn't match. lastName stays
    # optional since auth.py only enforces it when non-empty.
    firstName: str
    lastName: Optional[str] = ""
    email: EmailStr
    employeeId: str
    department: str
    checkUserPresent: Optional[bool] = True

class ChangePasswordRequest(BaseModel):
    oldPassword: str
    newPassword: str
    confirmNewPassword: str

class ResetPasswordTokenRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    password: str
    confirmPassword: str
    resetPasswordToken: str

class DeleteAccountRequest(BaseModel):
    otp: str

# ─── Routes ───────────────────────────────────────────────────────────────────

@router.post("/login")
async def login_route(body: LoginRequest):
    return await login(body.email, body.password)

@router.post("/signup")
async def signup_route(body: SignupRequest):
    return await sign_up(
        body.firstName,
        body.lastName,
        body.email,
        body.employeeId,
        body.department,
        body.password,
        body.confirmPassword,
        body.otp,
    )

@router.post("/sendotp")
async def send_otp_route(body: SendOTPRequest):
    return await send_otp(
        email=body.email,
        firstName=body.firstName,
        lastName=body.lastName,
        employeeId=body.employeeId,
        department=body.department,
        check_user_present=body.checkUserPresent,
    )

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return await get_user_details(current_user)

@router.get("/departments")
async def departments_route():
    return await get_departments()

@router.post("/changepassword")
async def change_password_route(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    return await change_password(
        current_user,
        body.oldPassword,
        body.newPassword,
        body.confirmNewPassword,
    )

@router.post("/reset-password-token")
async def reset_password_token_route(body: ResetPasswordTokenRequest):
    return await reset_password_token(body.email)

@router.post("/reset-password")
async def reset_password_route(body: ResetPasswordRequest):
    return await reset_password(
        body.password,
        body.confirmPassword,
        body.resetPasswordToken,
    )

# Both routes require a valid session (get_current_user) — the email used
# for the OTP and the deletion itself always comes from the authenticated
# user's own record, never from the request body, so there's no way to
# trigger this for any account other than the one currently logged in.

@router.post("/delete-account/send-otp")
async def send_delete_account_otp_route(
    current_user: dict = Depends(get_current_user),
):
    return await send_account_deletion_otp(current_user)

@router.post("/delete-account")
async def delete_account_route(
    body: DeleteAccountRequest,
    current_user: dict = Depends(get_current_user),
):
    return await delete_account(current_user, body.otp)