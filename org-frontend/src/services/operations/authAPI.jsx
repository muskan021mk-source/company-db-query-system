import { toast } from "react-hot-toast";
import { setLoading, setToken, setSignupData } from "../../reducer/slices/authSlice";
import { setUser } from "../../reducer/slices/profileSlice";
import { apiConnector } from "../apiconnector";
import { endpoints } from "../apis";

const {
  SENDOTP_API,
  SIGNUP_API,
  LOGIN_API,
  RESETPASSTOKEN_API,
  RESETPASSWORD_API,
} = endpoints;

// ─── Helper to extract error message from axios error ─────────────────────────
function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;

  if (Array.isArray(detail)) {
    // FastAPI/Pydantic validation errors: [{ type, loc, msg, input }, ...]
    return detail.map((e) => e.msg).join(", ");
  }
  if (typeof detail === "string") {
    return detail;
  }

  return error?.response?.data?.message || error?.message || fallback;
}

// ─── Send OTP ─────────────────────────────────────────────────────────────────
// Accepts the full signup identity fields (not just email) because the
// backend now verifies firstName/employeeId/department against Postgres
// BEFORE sending the OTP — the same chained check used at signup, run
// earlier so a mismatched identity never even receives an OTP.
export function sendOtp(
  { firstName, lastName, email, employeeId, department },
  navigate
) {
  return async (dispatch) => {
    const toastId = toast.loading("Sending OTP...");
    dispatch(setLoading(true));
    try {
      const response = await apiConnector("POST", SENDOTP_API, {
        firstName,
        lastName,
        email,
        employeeId,
        department,
        checkUserPresent: true,
      });

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message);
      }

      toast.success("OTP Sent Successfully");
      navigate("/verify-email");
    } catch (error) {
      toast.error(getErrorMessage(error, "Could not send OTP"));
    } finally {
      dispatch(setLoading(false));
      toast.dismiss(toastId);
    }
  };
}

// ─── Sign Up ──────────────────────────────────────────────────────────────────
export function signUp(
  firstName,
  lastName,
  email,
  employeeId,
  department,
  password,
  confirmPassword,
  otp,
  navigate
) {
  return async (dispatch) => {
    const toastId = toast.loading("Creating account...");
    dispatch(setLoading(true));
    try {
      const response = await apiConnector("POST", SIGNUP_API, {
        firstName,
        lastName,
        email,
        employeeId,
        department,
        password,
        confirmPassword,
        otp,
      });

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message);
      }

      toast.success("Account Created Successfully");
      dispatch(setSignupData(null));
      navigate("/login");
    } catch (error) {
      toast.error(getErrorMessage(error, "Signup Failed"));
      navigate("/signup");
    } finally {
      dispatch(setLoading(false));
      toast.dismiss(toastId);
    }
  };
}

// ─── Login ────────────────────────────────────────────────────────────────────
export function login(email, password, navigate) {
  return async (dispatch) => {
    const toastId = toast.loading("Signing in...");
    dispatch(setLoading(true));
    try {
      const response = await apiConnector("POST", LOGIN_API, {
        email,
        password,
      });

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message);
      }

      toast.success("Login Successful");

      dispatch(setToken(response.data.token));
      localStorage.setItem("token", JSON.stringify(response.data.token));

      const { firstName, lastName, email: userEmail, employeeId, department, image } = response.data.user;
      const userImage = image
        || `https://api.dicebear.com/5.x/initials/svg?seed=${firstName} ${lastName}`;

      const finalUser = {
        name: `${firstName} ${lastName}`,
        firstName,
        lastName,
        email: userEmail,
        employeeId,
        department,
        image: userImage,
      };

      dispatch(setUser(finalUser));
      localStorage.setItem("user", JSON.stringify(finalUser));

      navigate("/");
   } catch (error) {
    //  window.alert("CATCH BLOCK REACHED");
  console.log("LOGIN ERROR DEBUG:", getErrorMessage(error, "Login Failed"));
   toast.error(getErrorMessage(error, "Login Failed"));
  // toast.error(getErrorMessage(error, ""));
} finally {
      dispatch(setLoading(false));
      toast.dismiss(toastId);
    }
  };
}

// ─── Forgot Password ──────────────────────────────────────────────────────────
export function getPasswordResetToken(email, setEmailSent) {
  return async (dispatch) => {
    const toastId = toast.loading("Sending reset email...");
    dispatch(setLoading(true));
    try {
      const response = await apiConnector("POST", RESETPASSTOKEN_API, {
        email,
      });

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message);
      }

      toast.success("Reset Email Sent");
      setEmailSent(true);
    } catch (error) {
      toast.error(getErrorMessage(error, "Failed to send reset email"));
    } finally {
      dispatch(setLoading(false));
      toast.dismiss(toastId);
    }
  };
}

// ─── Reset Password ───────────────────────────────────────────────────────────
export function resetPassword(password, confirmPassword, resetPasswordToken, navigate) {
  return async (dispatch) => {
    const toastId = toast.loading("Resetting password...");
    dispatch(setLoading(true));
    try {
      const response = await apiConnector("POST", RESETPASSWORD_API, {
        password,
        confirmPassword,
        resetPasswordToken,
      });

      if (!response.data.success) {
        throw new Error(response.data.detail || response.data.message);
      }

      toast.success("Password Reset Successfully");
      navigate("/login");
    } catch (error) {
      toast.error(getErrorMessage(error, "Failed to reset password"));
    } finally {
      dispatch(setLoading(false));
      toast.dismiss(toastId);
    }
  };
}

// ─── Logout ───────────────────────────────────────────────────────────────────
export function logout(navigate) {
  return (dispatch) => {
    dispatch(setToken(null));
    dispatch(setUser(null));
    localStorage.removeItem("token");
    localStorage.removeItem("user");
    toast.success("Logged Out");
    if (navigate) navigate("/login");
  };
}