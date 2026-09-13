import Link from "next/link";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { UploadForm } from "@/components/models/upload-form";

export const metadata = { title: "Enviar Modelo" };

export default async function UploadPage() {
  const supabase = await createClient();

  // Obter usuario autenticado para filtro explicito (contorna RLS em producao)
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const admin = createAdminClient();

  // Verificar plano e contagem de modelos para bloquear free no limite
  const [profileResult, countResult] = await Promise.all([
    user
      ? admin.from("profiles").select("plan").eq("id", user.id).single()
      : Promise.resolve({ data: null, error: null }),
    supabase.from("models").select("*", { count: "exact", head: true }),
  ]);

  const plan = (profileResult.data?.plan ?? "free") as "free" | "pro";
  const modelCount = countResult.count ?? 0;
  const blocked = plan === "free" && modelCount >= 1;

  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6">
        <Link href="/models" className="text-sm text-gray-500 hover:text-gray-700">
          Voltar para meus modelos
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">Enviar modelo 3D</h1>
        <p className="mt-1 text-sm text-gray-500">
          Apos o envio, analisaremos automaticamente a qualidade da malha.
        </p>
      </div>

      {blocked ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center shadow-sm">
          <p className="text-3xl mb-3">&#128274;</p>
          <h2 className="text-base font-semibold text-amber-900">
            Limite do plano gratuito atingido
          </h2>
          <p className="mt-2 text-sm text-amber-800">
            O plano gratuito permite apenas <strong>1 modelo</strong>.
            Para enviar mais modelos, faca upgrade para o plano Pro.
          </p>
          <Link
            href="/models"
            className="mt-4 inline-flex rounded-md bg-amber-700 px-4 py-2 text-sm font-medium text-white hover:bg-amber-800"
          >
            Ver meus modelos
          </Link>
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <UploadForm />
        </div>
      )}
    </div>
  );
}