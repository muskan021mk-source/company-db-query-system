import React from "react";
import LoginForm from "./LoginForm";
import SignupForm from "./SignupForm";
import frame from "../../../assets/images/frame.png";

const Template = ({ title, description1, description2, image, formType }) => {
  return (
    <div className="flex w-11/12 max-w-290 py-12 mx-auto gap-x-12 justify-between text-richblack-100">
      
      {/* Left Section — Form */}
      <div className="w-11/12 max-w-112.5 flex flex-col">

        {/* Company Branding */}
        <div className="mb-6">
          <p className="text-blue-100 text-sm font-medium uppercase tracking-widest mb-1">
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
        </div>

        {/* Form */}
        {formType === "login" ? <LoginForm /> : <SignupForm />}

        {/* Note for internal users */}
        <p className="mt-6 text-center text-xs text-richblack-400">
          {formType === "login"
            ? "Access is restricted to authorized company employees only."
            : "Your account will be verified against company records before activation."}
        </p>
      </div>

      {/* Right Section — Illustration */}
      <div className="relative w-11/12 max-w-112.5 hidden md:block">
        <img
          src={frame}
          alt="background pattern"
          width={558}
          height={504}
          loading="lazy"
        />
        <img
          src={image}
          alt="illustration"
          width={558}
          height={504}
          loading="lazy"
          className="absolute -top-4 right-4"
        />
      </div>
    </div>
  );
};

export default Template;