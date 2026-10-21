console.log("ALL ENV VARS:", import.meta.env);
const BASE_URL = import.meta.env.VITE_BASE_URL;

// AUTH ENDPOINTS
export const endpoints = {
  SENDOTP_API:      BASE_URL + "/auth/sendotp",
  SIGNUP_API:       BASE_URL + "/auth/signup",
  LOGIN_API:        BASE_URL + "/auth/login",
  RESETPASSTOKEN_API: BASE_URL + "/auth/reset-password-token",
  RESETPASSWORD_API:  BASE_URL + "/auth/reset-password",
}

// PROFILE ENDPOINTS
export const profileEndpoints = {
  GET_USER_DETAILS_API:   BASE_URL + "/profile/getUserDetails",
  UPDATE_PROFILE_API:     BASE_URL + "/profile/updateProfile",
  UPDATE_PICTURE_API:     BASE_URL + "/profile/updateDisplayPicture",
  CHANGE_PASSWORD_API:    BASE_URL + "/auth/changepassword",
  // Fixed: previously pointed at /profile/deleteProfile, which has no
  // matching backend route anywhere. Account deletion actually lives
  // under the /auth router (auth_routes.py), alongside signup/login/OTP,
  // so these now point at the routes that really exist.
  SEND_DELETE_ACCOUNT_OTP_API: BASE_URL + "/auth/delete-account/send-otp",
  DELETE_PROFILE_API:          BASE_URL + "/auth/delete-account",
}