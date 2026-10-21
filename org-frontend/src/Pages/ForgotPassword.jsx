import { useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import { Link } from 'react-router-dom'
import { BiArrowBack } from "react-icons/bi"
import { getPasswordResetToken } from "../services/operations/authAPI"

const ForgotPassword = () => {
  const [emailSent, setEmailSent] = useState(false)
  const [email, setEmail] = useState("")
  const dispatch = useDispatch()
  const { loading } = useSelector((state) => state.auth)

  const submitHandler = (e) => {
    e.preventDefault()
    dispatch(getPasswordResetToken(email, setEmailSent))
  }

  return (
    <div className="grid min-h-screen place-items-center bg-richblack-900">
      {loading ? (
        <div className="spinner"></div>
      ) : (
        <div className="max-w-125 p-4 lg:p-8">
          <h1 className="text-[1.875rem] font-semibold leading-9.5 text-richblack-5">
            {!emailSent ? "Reset Your Password" : "Check Your Email"}
          </h1>
          <p className="my-4 text-[1.125rem] leading-6.5 text-richblack-100">
            {!emailSent
              ? "Enter your company email address and we'll send you instructions to reset your password."
              : <>
                  We have sent a password reset link to{" "}
                  <span className="font-medium text-yellow-50">{email}</span>.
                  {" "}Please check your inbox.
                </>
            }
          </p>

          <form onSubmit={submitHandler}>
            {!emailSent && (
              <label className="w-full">
                <p className="mb-1 text-[0.875rem] leading-5.5 text-richblack-5">
                  Company Email <sup className="text-pink-200">*</sup>
                </p>
                <input
                  required
                  type="email"
                  name="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  className="form-style w-full"
                />
              </label>
            )}
            <button
              type="submit"
              className="mt-6 w-full rounded-lg bg-yellow-50 py-3 px-3 font-medium text-richblack-900"
            >
              {!emailSent ? "Submit" : "Resend Email"}
            </button>
          </form>

          <div className="mt-6">
            <Link to="/login">
              <p className="flex items-center gap-x-2 text-richblack-5">
                <BiArrowBack /> Back to Login
              </p>
            </Link>
          </div>
        </div>
      )}
    </div>
  )
}

export default ForgotPassword