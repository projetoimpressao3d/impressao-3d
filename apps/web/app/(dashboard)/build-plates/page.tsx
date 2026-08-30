import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { BuildPlateCard } from "@/components/build-plates/build-plate-card";
import type { BuildPlate } from "@/types/database";

export const metadata = { title: "Mesas de Trabalho" };

export default async function BuildPlatesPage() {
  const supabase = await createClient();

  const { data: plates, error } = await supabase
    .from("build_plates")
    .select("*")
    .order("is_default", { ascending: false })
    .order("created_at", { ascending: true });

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        Erro ao carregar mesas. Tente recarregar a página.
      </div>
    );
  }

  const typedPlates = (plates ?? []) as BuildPlate[];

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Mesas de trabalho</h1>
          <p className="mt-1 text-sm text-gray-500">
            Defina as dimensões das suas mesas de impressão para comparar com os modelos.
          </p>
        </div>
        <Link
          href="/build-plates/new"
          className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          + Nova mesa
        </Link>
      </div>

      {typedPlates.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed border-gray-200 p-12 text-center">
          <p className="text-4xl">🖨️</p>
          <p className="mt-3 font-medium text-gray-700">Nenhuma mesa cadastrada</p>
          <p className="mt-1 text-sm text-gray-500">
            Cadastre as dimensões da área de impressão da sua impressora 3D.
          </p>
          <Link
            href="/build-plates/new"
            className="mt-4 inline-flex rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
          >
            Cadastrar primeira mesa
          </Link>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {typedPlates.map((plate) => (
            <BuildPlateCard key={plate.id} plate={plate} />
          ))}
        </div>
      )}

      {typedPlates.length > 0 && (
        <p className="mt-6 text-xs text-gray-400">
          💡 A mesa marcada como ⭐ Padrão será pré-selecionada automaticamente no visualizador 3D.
        </p>
      )}
    </div>
  );
}
