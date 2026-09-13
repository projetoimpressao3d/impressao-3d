import Link from "next/link";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { ModelCard } from "@/components/models/model-card";
import { PendingPoller } from "@/components/models/pending-poller";

export const metadata = { title: "Meus Modelos" };

// Revalidar a pagina a cada 10s para refletir mudancas de status de analise
export const revalidate = 10;

export default async function ModelsPage() {
  const supabase = await createClient();

  // Obter usuario autenticado primeiro (necessario para filtro explicito de perfil)
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Buscar modelos e plano do usuario em paralelo
  // Usamos createAdminClient() para o perfil para garantir que a query funcione
  // independente das RLS policies configuradas na tabela profiles.
  const admin = createAdminClient();
  const [modelsResult, profileResult] = await Promise.all([
    supabase.from("models").select("*").order("created_at", { ascending: false }),
    user
      ? admin.from("profiles").select("plan").eq("id", user.id).single()
      : Promise.resolve({ data: null, error: null }),
  ]);

  if (modelsResult.error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Erro ao carregar modelos. Tente recarregar a pagina.
      </div>
    );
  }

  const models = modelsResult.data ?? [];
  const plan = (profileResult.data?.plan ?? "free") as "free" | "pro";
  const isFree = plan === "free";
  const atFreeLimit = isFree && models.length >= 1;
  const canUpload = !atFreeLimit;
  const hasPending = models.some((m) => m.printability_status === "pending");

  return (
    <div>
      {/* Polling automático enquanto houver modelos sendo analisados */}
      <PendingPoller hasPending={hasPending} />

      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meus modelos</h1>
          <p className="mt-1 text-sm text-gray-500">
            {models.length} modelo{models.length !== 1 ? "s" : ""} enviado{models.length !== 1 ? "s" : ""}
            {isFree && (
              <span className="ml-2 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500">
                Plano Free &middot; 1 modelo
              </span>
            )}
          </p>
        </div>

        {canUpload ? (
          <Link
            href="/models/upload"
            className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            + Enviar modelo
          </Link>
        ) : (
          <div
            title="O plano gratuito permite apenas 1 modelo."
            className="cursor-not-allowed rounded-md bg-gray-200 px-4 py-2 text-sm font-medium text-gray-400 select-none"
          >
            Enviar modelo
          </div>
        )}
      </div>

      {/* Banner informativo para usuarios free no limite */}
      {atFreeLimit && (
        <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <span className="font-medium">Limite do plano gratuito atingido.</span>{" "}
          Voce pode ter apenas 1 modelo no plano Free. Para adicionar mais modelos, faca upgrade para o plano Pro.
        </div>
      )}

      {models.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-12 text-center">
          <p className="text-4xl">&#128230;</p>
          <p className="mt-3 font-medium text-gray-700">Nenhum modelo ainda</p>
          <p className="mt-1 text-sm text-gray-500">
            Envie seu primeiro arquivo STL ou 3MF para comecar.
          </p>
          <Link
            href="/models/upload"
            className="mt-4 inline-flex rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Enviar modelo
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {models.map((model) => (
            <ModelCard key={model.id} model={model} plan={plan} />
          ))}
        </div>
      )}
    </div>
  );
}