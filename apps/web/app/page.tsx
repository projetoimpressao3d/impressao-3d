import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

/**
 * Página inicial: redireciona para /models se autenticado, ou /login se não.
 */
export default async function HomePage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/models");
  } else {
    redirect("/login");
  }
}
