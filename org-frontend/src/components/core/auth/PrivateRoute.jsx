import React, { useEffect, useState } from "react";
import { useSelector } from "react-redux";
import { Navigate } from "react-router-dom";
import { apiConnector } from "../../../services/apiconnector";

const PrivateRoute = ({ children }) => {
  const { token } = useSelector((state) => state.auth);
  const [checking, setChecking] = useState(true);
  const [valid, setValid] = useState(false);

  useEffect(() => {
    if (!token) {
      setChecking(false);
      return;
    }

    // Actively verify with the backend that this token still resolves to
    // a real, existing user — instead of just trusting that a token
    // string is sitting in localStorage. This is what catches a deleted
    // account immediately, on route mount, without waiting for the user
    // to click something else first.
    apiConnector("GET", "/auth/me", null, {
      Authorization: `Bearer ${token}`,
    })
      .then(() => setValid(true))
      .catch(() => setValid(false)) // apiconnector's 401 interceptor also handles cleanup + redirect
      .finally(() => setChecking(false));
  }, [token]);

  if (checking) {
    return null; // swap for a spinner/loader component if you have one
  }

  if (token != null && valid) {
    return children;
  }

  return <Navigate to="/login" />;
};

export default PrivateRoute;