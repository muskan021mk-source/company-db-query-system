import { useState, useEffect } from "react";
import axios from "axios";
import { toast } from "react-hot-toast";
import { AiOutlineEye, AiOutlineEyeInvisible } from "react-icons/ai";
import { useDispatch } from "react-redux";
import { useNavigate } from "react-router-dom";
import { sendOtp } from "../../../services/operations/authAPI";
import { setSignupData } from "../../../reducer/slices/authSlice";

// This matches main.py exactly: app.include_router(auth_router) has no
// prefix, and auth_router itself only carries prefix="/auth" — so every
// real endpoint lives at /auth/..., never /api/v1/auth/....
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:4000";

function SignupForm() {
  const navigate = useNavigate();
  const dispatch = useDispatch();

  const [passAlert, setPassAlert] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  // Departments now come live from company_db.department — no hardcoded list.
  const [departments, setDepartments] = useState([]);
  const [departmentsLoading, setDepartmentsLoading] = useState(true);

  useEffect(() => {
    const fetchDepartments = async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/auth/departments`);
        if (res.data?.success) {
          setDepartments(res.data.departments || []);
        } else {
          toast.error("Could not load departments");
        }
      } catch (err) {
        console.error("Failed to fetch departments:", err);
        toast.error("Could not load departments. Please refresh the page.");
      } finally {
        setDepartmentsLoading(false);
      }
    };

    fetchDepartments();
  }, []);

  const [formData, setFormData] = useState({
    firstName: "",
    lastName: "",
    email: "",
    employeeId: "",
    department: "",
    password: "",
    confirmPassword: "",
  });

  const {
    firstName,
    lastName,
    email,
    employeeId,
    department,
    password,
    confirmPassword,
  } = formData;

  const handleOnChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
    if (e.target.name === "password") setPassAlert("");
  };

  const handleOnSubmit = async (e) => {
    e.preventDefault();

    if (password.length < 8) {
      setPassAlert("Password must be at least 8 characters");
      return;
    }
    if (password !== confirmPassword) {
      toast.error("Passwords do not match");
      return;
    }

    const signupData = { ...formData };

    try {
      setLoading(true);
      dispatch(setSignupData(signupData));
      // Send the full identity fields (firstName, lastName, employeeId,
      // department), not just email — the backend now verifies all of
      // these against Postgres BEFORE it sends the OTP, so it needs them
      // up front rather than only at the final signup step.
      dispatch(
        sendOtp(
          { firstName, lastName, email, employeeId, department },
          navigate
        )
      );
    } finally {
      setLoading(false);
      setFormData({
        firstName: "",
        lastName: "",
        email: "",
        employeeId: "",
        department: "",
        password: "",
        confirmPassword: "",
      });
    }
  };

  return (
    <form onSubmit={handleOnSubmit} className="flex w-full flex-col gap-y-4">

      {/* Name Row */}
      <div className="flex gap-x-4">
        <label className="w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            First Name <sup className="text-pink-200">*</sup>
          </p>
          <input
            required
            type="text"
            name="firstName"
            value={firstName}
            onChange={handleOnChange}
            placeholder="First name"
            className="form-style w-full"
          />
        </label>
        <label className="w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            Last Name
          </p>
          <input
            type="text"
            name="lastName"
            value={lastName}
            onChange={handleOnChange}
            placeholder="Last name (optional)"
            className="form-style w-full"
          />
        </label>
      </div>

      {/* Company Email */}
      <label className="w-full">
        <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
          Company Email <sup className="text-pink-200">*</sup>
        </p>
        <input
          required
          type="email"
          name="email"
          value={email}
          onChange={handleOnChange}
          placeholder="you@company.com"
          className="form-style w-full"
        />
      </label>

      {/* Employee ID + Department Row */}
      <div className="flex gap-x-4">
        <label className="w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            Employee ID <sup className="text-pink-200">*</sup>
          </p>
          <input
            required
            type="text"
            name="employeeId"
            value={employeeId}
            onChange={handleOnChange}
            placeholder="e.g. EMP-1042"
            className="form-style w-full"
          />
        </label>
        <label className="w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            Department <sup className="text-pink-200">*</sup>
          </p>
          <select
            required
            name="department"
            value={department}
            onChange={handleOnChange}
            disabled={departmentsLoading}
            className="form-style w-full"
          >
            <option value="" disabled>
              {departmentsLoading ? "Loading departments..." : "Select department"}
            </option>
            {departments.map((dept) => (
              <option key={dept} value={dept}>
                {dept}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Password Row */}
      <div className="flex gap-x-4">
        <label className="relative w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            Password <sup className="text-pink-200">*</sup>
          </p>
          <input
            required
            type={showPassword ? "text" : "password"}
            name="password"
            value={password}
            onChange={handleOnChange}
            placeholder="Min. 8 characters"
            className="form-style w-full pr-10!"
          />
          <span
            onClick={() => setShowPassword((prev) => !prev)}
            className="absolute right-3 top-9.5 z-10 cursor-pointer"
          >
            {showPassword ? (
              <AiOutlineEyeInvisible fontSize={24} fill="#AFB2BF" />
            ) : (
              <AiOutlineEye fontSize={24} fill="#AFB2BF" />
            )}
          </span>
          {passAlert && (
            <p className="mt-1 text-xs text-pink-200">{passAlert}</p>
          )}
        </label>

        <label className="relative w-full">
          <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
            Confirm Password <sup className="text-pink-200">*</sup>
          </p>
          <input
            required
            type={showConfirmPassword ? "text" : "password"}
            name="confirmPassword"
            value={confirmPassword}
            onChange={handleOnChange}
            placeholder="Re-enter password"
            className="form-style w-full pr-10!"
          />
          <span
            onClick={() => setShowConfirmPassword((prev) => !prev)}
            className="absolute right-3 top-9.5 z-10 cursor-pointer"
          >
            {showConfirmPassword ? (
              <AiOutlineEyeInvisible fontSize={24} fill="#AFB2BF" />
            ) : (
              <AiOutlineEye fontSize={24} fill="#AFB2BF" />
            )}
          </span>
        </label>
      </div>

      {/* Submit */}
      <button
        type="submit"
        disabled={loading}
        className="mt-6 rounded-lg bg-yellow-50 py-2 px-3 font-medium text-richblack-900 disabled:opacity-60"
      >
        {loading ? "Creating Account..." : "Create Account"}
      </button>
    </form>
  );
}

export default SignupForm;