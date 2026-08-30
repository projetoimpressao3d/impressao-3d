import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/models/[id]/signed-url
 * Gera uma URL assinada de download (validade: 1 hora) para o visualizador 3D.
 * Requer sessão autenticada — verifica que o modelo pertence ao usuário via RLS.
 */
export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  // Buscar o modelo (RLS garante que pertence ao usuário)
  const { data: model, error: modelError } = await supabase
    .from("models")
    .select("storage_path")
    .eq("id", id)
    .single();

  if (modelError ?? !model) {
    return NextResponse.json({ error: "Modelo não encontrado" }, { status: 404 });
  }

  // Gerar URL assinada de download via service_role (1 hora de validade)
  const admin = createAdminClient();
  const { data, error } = await admin.storage
    .from("models")
    .createSignedUrl(model.storage_path as string, 3600);

  if (error ?? !data) {
    console.error("[signed-url] Erro:", error?.message);
    return NextResponse.json(
      { error: "Erro ao gerar URL de visualização" },
      { status: 500 },
    );
  }

  return NextResponse.json({ url: data.signedUrl });
}
