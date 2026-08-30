import { notFound, redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { ModelViewer } from "@/components/viewer/model-viewer";
import type { Model, BuildPlate } from "@/types/database";

export const metadata = { title: "Visualizador 3D" };

interface PageProps {
  params: Promise<{ id: string }>;
}

const STATUS_CONFIG = {
  pending: { label: "Analisando…", className: "bg-yellow-100 text-yellow-800" },
  ok: { label: "Pronto para impressão", className: "bg-green-100 text-green-800" },
  warning: { label: "Atenção", className: "bg-orange-100 text-orange-800" },
  error: { label: "Erro na malha", className: "bg-red-100 text-red-800" },
} as const;

export default async function ModelDetailPage({ params }: PageProps) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  // Buscar modelo (RLS garante que pertence ao usuário)
  const { data: model } = await supabase
    .from("models")
    .select("*")
    .eq("id", id)
    .single();

  if (!model) notFound();

  // Buscar mesas de trabalho do usuário
  const { data: buildPlates } = await supabase
    .from("build_plates")
    .select("*")
    .order("is_default", { ascending: false })
    .order("created_at", { ascending: true });

  // Verificar se o usuário tem assinatura ativa
  const { data: subscription } = await supabase
    .from("subscriptions")
    .select("id")
    .eq("user_id", user.id)
    .eq("status", "active")
    .limit(1)
    .single();

  const hasSubscription = !!subscription;
  const typedModel = model as Model;
  const typedPlates = (buildPlates ?? []) as BuildPlate[];
  const status = STATUS_CONFIG[typedModel.printability_status];

  function formatDimensions(m: Model): string | null {
    if (m.bounding_box_x_mm == null) return null;
    return `${m.bounding_box_x_mm.toFixed(1)} × ${m.bounding_box_y_mm?.toFixed(1)} × ${m.bounding_box_z_mm?.toFixed(1)} mm`;
  }

  return (
    <div>
      {/* Breadcrumb + cabeçalho */}
      <div className="mb-4">
        <Link href="/models" className="text-sm text-gray-500 hover:text-gray-700">
          ← Meus modelos
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">{typedModel.name}</h1>

        <div className="mt-2 flex flex-wrap items-center gap-3 text-sm text-gray-600">
          {/* Formato */}
          <span className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs">
            {typedModel.format.toUpperCase()}
          </span>

          {/* Status de printability */}
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}
          >
            {status.label}
          </span>

          {/* Dimensões (se disponível) */}
          {formatDimensions(typedModel) && (
            <span className="text-xs text-gray-500">
              📐 {formatDimensions(typedModel)}
            </span>
          )}

          {/* Nome do arquivo original */}
          {typedModel.original_filename && typedModel.original_filename !== typedModel.name && (
            <span className="text-xs text-gray-400">
              📁 {typedModel.original_filename}
            </span>
          )}
        </div>

        {/* Relatório de printability */}
        {typedModel.printability_report && typedModel.printability_status !== "pending" && (
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-gray-500 hover:text-gray-700">
              Ver relatório de análise
            </summary>
            <div className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3 sm:grid-cols-3">
              {[
                {
                  label: "Malha fechada",
                  value: typedModel.printability_report.is_watertight ? "✅ Sim" : "❌ Não",
                },
                {
                  label: "Volume válido",
                  value: typedModel.printability_report.is_volume ? "✅ Sim" : "❌ Não",
                },
                {
                  label: "Arestas não-manifold",
                  value:
                    typedModel.printability_report.non_manifold_edge_count === 0
                      ? "✅ Nenhuma"
                      : `❌ ${typedModel.printability_report.non_manifold_edge_count}`,
                },
                {
                  label: "Faces",
                  value: typedModel.printability_report.face_count.toLocaleString("pt-BR"),
                },
                {
                  label: "Vértices",
                  value: typedModel.printability_report.vertex_count.toLocaleString("pt-BR"),
                },
              ].map(({ label, value }) => (
                <div key={label}>
                  <p className="text-xs text-gray-500">{label}</p>
                  <p className="text-sm font-medium text-gray-800">{value}</p>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>

      {/* Visualizador 3D + editor de cortes */}
      <ModelViewer
        model={typedModel}
        buildPlates={typedPlates}
        hasSubscription={hasSubscription}
      />

      {/* Link para mesas se não tiver nenhuma */}
      {typedPlates.length === 0 && (
        <div className="mt-4 rounded-lg border border-dashed border-gray-200 p-4 text-center text-sm text-gray-500">
          Ainda não há mesas de trabalho cadastradas.{" "}
          <Link href="/build-plates/new" className="text-brand-600 hover:underline">
            Cadastrar minha primeira mesa
          </Link>
        </div>
      )}
    </div>
  );
}
