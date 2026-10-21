import { useState } from "react"
import { AiOutlineEye, AiOutlineEyeInvisible } from "react-icons/ai"
import { useDispatch } from "react-redux"
import { Link, useNavigate } from "react-router-dom"
import { login } from "../../../services/operations/authAPI"

function LoginForm() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const [formData, setFormData] = useState({
    email: "",
    password: "",
  })
  const [showPassword, setShowPassword] = useState(false)
  const [loading, setLoading] = useState(false)

  const { email, password } = formData

  const handleOnChange = (e) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }))
  }

  // Renamed from handleOnSubmit and no longer tied to a <form onSubmit>.
  // This removes ANY possibility of a native browser form submission
  // (which reloads the page) ever firing, regardless of event timing,
  // browser autofill behavior, or password-manager interference — the
  // button below is type="button" and calls this directly on click.
  const handleLoginClick = async () => {
    if (loading) return
    try {
      setLoading(true)
      await dispatch(login(email, password, navigate))
    } finally {
      setLoading(false)
    }
  }

  // Still supports pressing Enter in either field, without relying on
  // native form submission — we handle the keydown ourselves.
  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault()
      handleLoginClick()
    }
  }

  return (
    <div className="mt-6 flex w-full flex-col gap-y-4">
      {/* Employee / Company Email */}
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
          onKeyDown={handleKeyDown}
          placeholder="you@company.com"
          className="form-style w-full"
        />
      </label>

      {/* Password */}
      <label className="relative">
        <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
          Password <sup className="text-pink-200">*</sup>
        </p>
        <input
          required
          type={showPassword ? "text" : "password"}
          name="password"
          value={password}
          onChange={handleOnChange}
          onKeyDown={handleKeyDown}
          placeholder="Enter Password"
          className="form-style w-full pr-10!"
          minLength={6}
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
        <Link to="/forgot-password">
          <p className="mt-1 ml-auto max-w-max text-xs text-blue-100">
            Forgot Password?
          </p>
        </Link>
      </label>

      <button
        type="button"
        onClick={handleLoginClick}
        disabled={loading}
        className="mt-6 rounded-lg bg-yellow-50 py-2 px-3 font-medium text-richblack-900 disabled:opacity-60"
      >
        {loading ? "Signing In..." : "Sign In"}
      </button>
    </div>
  )
}

export default LoginForm