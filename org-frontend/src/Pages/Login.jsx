import Template from "../components/core/auth/Template";

function Login() {
  return (
    <Template
      title="Welcome Back"
      description1="Sign in to access your company database."
      formType="login"
    />
  );
}

export default Login;