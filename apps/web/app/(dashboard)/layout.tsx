import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

/**
 * Layout protegido para o dashboard.
 * Verifica autenticação no servidor — redireciona para /login se não autenticado.
 * (O middleware já faz isso, mas esta verificação é uma camada extra de segurança.)
 */
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  return (
    <div className="h-screen w-full overflow-hidden bg-zinc-950 text-zinc-200">
      {children}
    </div>
  );
}
