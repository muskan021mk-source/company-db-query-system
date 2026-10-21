import { toast } from "react-hot-toast"
import { setLoading, setUser } from "../../reducer/slices/profileSlice"
import { setToken } from "../../reducer/slices/authSlice"
import { apiConnector } from "../apiconnector"
import { profileEndpoints } from "../apis"
import { logout } from "./authAPI"

const {
  GET_USER_DETAILS_API,
  SEND_DELETE_ACCOUNT_OTP_API,
  DELETE_PROFILE_API,
} = profileEndpoints

// ─── Get User Details ─────────────────────────────────────────────────────────
// Fetches full user profile from backend including employeeId and department.
// Called on app load or when user profile needs to be refreshed.
export function getUserDetails(token, navigate) {
  return async (dispatch) => {
    const toastId = toast.loading("Loading profile...")
    dispatch(setLoading(true))
    try {
      const response = await apiConnector("GET", GET_USER_DETAILS_API, null, {
        Authorization: `Bearer ${token}`,
      })

      if (!response.data.success) {
        throw new Error(response.data.message)
      }

      const { firstName, lastName, email, employeeId, department, image } =
        response.data.data

      const userImage =
        image ||
        `https://api.dicebear.com/5.x/initials/svg?seed=${firstName} ${lastName}`

      const finalUser = {
        name: `${firstName} ${lastName}`,
        firstName,
        lastName,
        email,
        employeeId,
        department,
        image: userImage,
      }

      dispatch(setUser(finalUser))
      localStorage.setItem("user", JSON.stringify(finalUser))
    } catch (error) {
      // Only force a logout when the backend actually says the token is
      // invalid/expired (401). Any other failure (network blip, 500, etc.)
      // should not silently log a user out of a still-valid session.
      if (error?.response?.status === 401) {
        dispatch(logout(navigate))
        toast.error("Session expired. Please log in again.")
      } else {
        toast.error(
          error?.response?.data?.message ||
            error?.message ||
            "Could Not Load Profile"
        )
      }
    } finally {
      dispatch(setLoading(false))
      toast.dismiss(toastId)
    }
  }
}

// ─── Helper to extract error message from axios error ─────────────────────────
function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((e) => e.msg).join(", ")
  }
  if (typeof detail === "string") {
    return detail
  }
  return error?.response?.data?.message || error?.message || fallback
}

// ─── Send Delete-Account OTP ───────────────────────────────────────────────────
// Step 1 of account deletion. Backend derives the email from the
// authenticated session itself (get_current_user), never from anything
// the client sends, so this can only ever trigger a deletion OTP for
// whichever account the current token belongs to.
//
// Returns true/false instead of dispatching a navigation, so the caller
// (a two-step confirm modal) knows whether to advance to the OTP-entry step.
export function sendDeleteAccountOtp(token) {
  return async () => {
    const toastId = toast.loading("Sending confirmation code...")
    try {
      const response = await apiConnector(
        "POST",
        SEND_DELETE_ACCOUNT_OTP_API,
        null,
        { Authorization: `Bearer ${token}` }
      )

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message)
      }

      toast.success("Confirmation code sent to your email")
      return true
    } catch (error) {
      toast.error(getErrorMessage(error, "Could not send confirmation code"))
      return false
    } finally {
      toast.dismiss(toastId)
    }
  }
}

// ─── Confirm Account Deletion ──────────────────────────────────────────────────
// Step 2. Requires the OTP that was just emailed to the logged-in user's
// own address. On success, clears the session exactly like logout does —
// there's nothing left to fetch once the account itself is gone.
export function deleteAccount(otp, token, navigate) {
  return async (dispatch) => {
    const toastId = toast.loading("Deleting account...")
    try {
      const response = await apiConnector(
        "POST",
        DELETE_PROFILE_API,
        { otp },
        { Authorization: `Bearer ${token}` }
      )

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message)
      }

      toast.success("Account deleted")

      dispatch(setToken(null))
      dispatch(setUser(null))
      localStorage.removeItem("token")
      localStorage.removeItem("user")

      navigate("/login")
      return true
    } catch (error) {
      toast.error(getErrorMessage(error, "Could not delete account"))
      return false
    } finally {
      toast.dismiss(toastId)
    }
  }
}