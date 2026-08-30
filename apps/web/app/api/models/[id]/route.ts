import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/models/[id]
 * Busca um modelo por ID. RLS garante que só o dono acessa.
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

  const { data: model, error } = await supabase
    .from("models")
    .select("*")
    .eq("id", id)
    .single();

  if (error ?? !model) {
    return NextResponse.json({ error: "Modelo não encontrado" }, { status: 404 });
  }

  return NextResponse.json({ model });
}

/**
 * DELETE /api/models/[id]
 * Remove o modelo e o arquivo do Storage (requisito LGPD — seção 9 do AGENTS.md).
 */
export async function DELETE(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  // Buscar o modelo para obter o storage_path (RLS garante que é do usuário)
  const { data: model, error: fetchError } = await supabase
    .from("models")
    .select("id, storage_path, user_id")
    .eq("id", id)
    .single();

  if (fetchError ?? !model) {
    return NextResponse.json({ error: "Modelo não encontrado" }, { status: 404 });
  }

  const admin = createAdminClient();

  // 1. Remover arquivo do Storage
  const { error: storageError } = await admin.storage
    .from("models")
    .remove([model.storage_path as string]);

  if (storageError) {
    console.error("[DELETE /api/models] Erro ao remover do Storage:", storageError.message);
    // Continua mesmo com erro no storage — remove o registro do banco
  }

  // 2. Remover registro do banco (cascade remove split_sessions → pieces)
  const { error: deleteError } = await admin
    .from("models")
    .delete()
    .eq("id", id);

  if (deleteError) {
    return NextResponse.json({ error: "Erro ao excluir modelo" }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
