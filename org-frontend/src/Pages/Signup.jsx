import Template from "../components/core/auth/Template";

function Signup() {
  return (
    <Template
      title="Create Your Company Account"
      description1="Request access to your company's AI-powered database system."
      description2="Verify your identity to get started."
      formType="signup"
    />
  );
}

export default Signup;