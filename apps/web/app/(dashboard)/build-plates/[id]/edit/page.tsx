import { notFound, redirect } from "next/navigation";
import Link from "next/link";
import { createClient } from "@/lib/supabase/server";
import { BuildPlateForm } from "@/components/build-plates/build-plate-form";
import type { BuildPlate } from "@/types/database";

export const metadata = { title: "Editar Mesa de Trabalho" };

interface PageProps {
  params: Promise<{ id: string }>;
}

export default async function EditBuildPlatePage({ params }: PageProps) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login");

  const { data: plate } = await supabase
    .from("build_plates")
    .select("*")
    .eq("id", id)
    .single();

  if (!plate) notFound();

  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-6">
        <Link
          href="/build-plates"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← Voltar para mesas
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">
          Editar mesa de trabalho
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Atualize as dimensões e o apelido da mesa.
        </p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <BuildPlateForm existing={plate as BuildPlate} />
      </div>
    </div>
  );
}
