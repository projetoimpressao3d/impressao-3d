import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { ModelCard } from "@/components/models/model-card";

export const metadata = { title: "Meus Modelos" };

// Revalidar a página a cada 10s para refletir mudanças de status de análise
export const revalidate = 10;

export default async function ModelsPage() {
  const supabase = await createClient();

  const { data: models, error } = await supabase
    .from("models")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Erro ao carregar modelos. Tente recarregar a página.
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meus modelos</h1>
          <p className="mt-1 text-sm text-gray-500">
            {models?.length ?? 0} modelo{(models?.length ?? 0) !== 1 ? "s" : ""} enviado{(models?.length ?? 0) !== 1 ? "s" : ""}
          </p>
        </div>
        <Link
          href="/models/upload"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          + Enviar modelo
        </Link>
      </div>

      {!models || models.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-12 text-center">
          <p className="text-4xl">📦</p>
          <p className="mt-3 font-medium text-gray-700">Nenhum modelo ainda</p>
          <p className="mt-1 text-sm text-gray-500">
            Envie seu primeiro arquivo STL ou 3MF para começar.
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
            <ModelCard key={model.id} model={model} />
          ))}
        </div>
      )}
    </div>
  );
}
