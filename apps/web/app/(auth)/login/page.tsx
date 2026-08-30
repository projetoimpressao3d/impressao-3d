import { LoginForm } from "@/components/auth/login-form";

export const metadata = { title: "Entrar" };

export default function LoginPage() {
  return (
    <>
      <h2 className="mb-6 text-center text-xl font-semibold text-gray-900">
        Entrar na sua conta
      </h2>
      <LoginForm />
    </>
  );
}
