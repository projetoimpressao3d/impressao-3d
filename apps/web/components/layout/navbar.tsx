import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { LogoutButton } from "@/components/layout/logout-button";

export async function Navbar() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return (
    <header className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
        <Link
          href="/models"
          className="text-sm font-semibold text-gray-900 hover:text-brand-600"
        >
          🖨️ Impressão 3D
        </Link>

        <nav className="flex items-center gap-4">
          <Link
            href="/models"
            className="text-sm text-gray-600 hover:text-gray-900"
          >
            Meus modelos
          </Link>
          <Link
            href="/models/upload"
            className="rounded-md bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700"
          >
            + Enviar modelo
          </Link>
          <span className="text-xs text-gray-400">{user?.email}</span>
          <LogoutButton />
        </nav>
      </div>
    </header>
  );
}
