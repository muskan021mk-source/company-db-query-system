import React from 'react'
import { useSelector } from 'react-redux'
import { Navigate, useLocation } from 'react-router-dom';

const PrivateRoute = ({ children }) => {
  const { token } = useSelector((state) => state.auth);
  const location = useLocation();

  if (token) {
    return children;
  }

  // Saves the page they tried to visit, redirects back after login
  return <Navigate to="/login" state={{ from: location }} replace />;
}

export default PrivateRoute;