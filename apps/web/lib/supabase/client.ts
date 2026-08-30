import { createBrowserClient } from "@supabase/ssr";

/**
 * Cria um cliente Supabase para uso em Client Components.
 * Gerencia a sessão via cookies automaticamente.
 */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
