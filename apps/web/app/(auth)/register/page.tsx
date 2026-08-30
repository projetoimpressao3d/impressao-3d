import { RegisterForm } from "@/components/auth/register-form";

export const metadata = { title: "Cadastro" };

export default function RegisterPage() {
  return (
    <>
      <h2 className="mb-6 text-center text-xl font-semibold text-gray-900">
        Criar conta
      </h2>
      <RegisterForm />
    </>
  );
}
