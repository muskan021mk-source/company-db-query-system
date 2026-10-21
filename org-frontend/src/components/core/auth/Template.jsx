import { Link } from "react-router-dom";
import LoginForm from "./LoginForm";
import SignupForm from "./SignupForm";

const Template = ({ title, description1, description2, formType }) => {
  return (
    <div className="min-h-screen flex items-center justify-center bg-richblack-900">
      <div className="w-full max-w-112.5 p-8 rounded-xl bg-richblack-800 shadow-lg">

        <p className="text-blue-100 text-xs font-medium uppercase tracking-widest mb-2">
          Company Database Query System
        </p>

        <h1 className="text-richblack-5 font-semibold text-[1.875rem] leading-9.5">
          {title}
        </h1>

        <p className="text-[1.125rem] mt-4 leading-6.5">
          <span className="text-richblack-100">{description1}</span>
          {description2 && (
            <span className="text-blue-100 italic"> {description2}</span>
          )}
        </p>

        {formType === "login" ? <LoginForm /> : <SignupForm />}

        <p className="mt-6 text-center text-xs text-richblack-400">
          {formType === "login"
            ? "Access is restricted to authorized company employees only."
            : "Your account will be verified against company records before activation."}
        </p>

        <p className="mt-4 text-center text-sm text-richblack-100">
          {formType === "login" ? (
            <>
              Don&apos;t have an account?{" "}
              <Link to="/signup" className="text-blue-100 font-medium">
                Sign up
              </Link>
            </>
          ) : (
            <>
              Already have an account?{" "}
              <Link to="/login" className="text-blue-100 font-medium">
                Login
              </Link>
            </>
          )}
        </p>
      </div>
    </div>
  );
};

export default Template;