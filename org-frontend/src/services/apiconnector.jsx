import axios from "axios";

export const axiosInstance = axios.create({});

// Global response interceptor — this is what makes a deleted account or
// expired token actually kick the user out, instead of failing silently
// on a per-request basis (which was the root cause of the "still logged
// in after account deleted in another browser" bug).
// Endpoints where a 401 is an EXPECTED possible outcome (bad credentials,
// bad OTP, etc.) and should be handled by the calling component's own
// try/catch + toast — NOT force-redirected by this global interceptor.
const AUTH_ENDPOINTS_TO_SKIP = [
  "/auth/login",
  "/auth/signup",
  "/auth/sendotp",
  "/auth/reset-password",
  "/auth/reset-password-token",
];

axiosInstance.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || "";
    const isAuthEndpoint = AUTH_ENDPOINTS_TO_SKIP.some((path) => url.includes(path));

    if (error.response?.status === 401 && !isAuthEndpoint) {
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      // Full page reload (not client-side navigate) so Redux state
      // resets cleanly too — avoids stale state lingering in the store.
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export const apiConnector = (method, url, bodyData, headers, params) => {
  return axiosInstance({
    method,
    url,
    data: bodyData || null,
    headers: headers || null,
    params: params || null,
  });
};