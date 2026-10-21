import { useEffect, useState } from 'react'
import { useDispatch, useSelector } from 'react-redux'
import OtpInput from 'react-otp-input'
import { BiArrowBack } from "react-icons/bi"
import { RxCountdownTimer } from "react-icons/rx"
import { Link, useNavigate } from 'react-router-dom'
import { signUp, sendOtp } from '../services/operations/authAPI'

const VerifyEmail = () => {
  const { signupData, loading } = useSelector((state) => state.auth)
  const [otp, setOtp] = useState("")
  const navigate = useNavigate()
  const dispatch = useDispatch()

  // Bug fix: added dependency array — without it this runs on every render
  useEffect(() => {
    if (!signupData) {
      navigate("/signup")
    }
  }, [signupData, navigate])

  const handleVerifyAndSignup = (e) => {
    e.preventDefault()

    // Guard against the brief window before the redirect effect above fires —
    // without this, a fast submit while signupData is still null would throw
    // instead of failing gracefully.
    if (!signupData) return

    const {
      firstName,
      lastName,
      email,
      employeeId,
      department,
      password,
      confirmPassword,
    } = signupData

     console.log("signupData is:", signupData)
  console.log("navigate is:", typeof navigate, navigate)

    dispatch(
      signUp(
        firstName,
        lastName,
        email,
        employeeId,
        department,
        password,
        confirmPassword,
        otp,
        navigate
      )
    )
  }

  const handleResendOtp = () => {
    if (!signupData) return
    dispatch(sendOtp(signupData.email, navigate))
  }

  return (
    <div className="min-h-[calc(100vh-3.5rem)] grid place-items-center">
      {loading ? (
        <div className="spinner"></div>
      ) : (
        <div className="max-w-125 p-4 lg:p-8">
          <h1 className="text-richblack-5 font-semibold text-[1.875rem] leading-9.5">
            Verify Your Email
          </h1>
          <p className="text-[1.125rem] leading-6.5 my-4 text-richblack-100">
            A 6-digit verification code has been sent to{" "}
            <span className="text-yellow-50 font-medium">
              {signupData?.email}
            </span>
            . Enter it below to activate your account.
          </p>

          <form onSubmit={handleVerifyAndSignup}>
            <OtpInput
              value={otp}
              onChange={setOtp}
              numInputs={6}
              renderInput={(props) => (
                <input
                  {...props}
                  placeholder="-"
                  style={{
                    boxShadow: "inset 0px -1px 0px rgba(255, 255, 255, 0.18)",
                  }}
                  className="w-12 lg:w-15 border-0 bg-richblack-800 rounded-lg text-richblack-5 aspect-square text-center focus:border-0 focus:outline-2 focus:outline-yellow-50"
                />
              )}
              containerStyle={{
                justifyContent: "space-between",
                gap: "0 6px",
              }}
            />

            <button
              type="submit"
              disabled={otp.length !== 6}
              className="w-full bg-yellow-50 py-3 px-3 rounded-lg mt-6 font-medium text-richblack-900 disabled:opacity-60"
            >
              Verify & Create Account
            </button>
          </form>

          <div className="mt-6 flex items-center justify-between">
            <Link to="/signup">
              <p className="text-richblack-5 flex items-center gap-x-2">
                <BiArrowBack /> Back to Signup
              </p>
            </Link>
            <button
              className="flex items-center text-blue-100 gap-x-2"
              onClick={handleResendOtp}
            >
              <RxCountdownTimer />
              Resend Code
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default VerifyEmail