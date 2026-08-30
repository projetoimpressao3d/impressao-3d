import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import type { CreateModelRequest, AnalyzeRequest } from "@/types/database";

/**
 * GET /api/models
 * Lista os modelos do usuário autenticado (RLS garante isolamento).
 */
export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const { data: models, error } = await supabase
    .from("models")
    .select("*")
    .order("created_at", { ascending: false });

  if (error) {
    return NextResponse.json({ error: "Erro ao buscar modelos" }, { status: 500 });
  }

  return NextResponse.json({ models });
}

/**
 * POST /api/models
 * Cria um registro na tabela models e dispara análise assíncrona no mesh-service.
 */
export async function POST(request: NextRequest) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const body = (await request.json()) as CreateModelRequest;
  const { name, storage_path, format, original_filename } = body;

  if (!name || !storage_path || !format) {
    return NextResponse.json(
      { error: "name, storage_path e format são obrigatórios" },
      { status: 400 },
    );
  }

  // Criar registro com status 'pending' — a análise vai atualizar depois
  const admin = createAdminClient();
  const { data: model, error } = await admin
    .from("models")
    .insert({
      user_id: user.id,
      name,
      storage_path,
      format,
      original_filename: original_filename ?? name,
      source: "upload",
      printability_status: "pending",
    })
    .select()
    .single();

  if (error ?? !model) {
    console.error("[POST /api/models] Erro ao criar modelo:", error?.message);
    return NextResponse.json({ error: "Erro ao salvar modelo" }, { status: 500 });
  }

  // Disparar análise no mesh-service (fire-and-forget, não bloqueia a resposta)
  void triggerAnalysis({
    model_id: model.id as string,
    storage_path: model.storage_path as string,
    user_id: user.id,
  });

  return NextResponse.json({ model }, { status: 201 });
}

/**
 * Chama o mesh-service para analisar a malha 3D de forma assíncrona.
 * Timeout de 5s — se o backend não responder, o job fica como 'pending'
 * e pode ser reprocessado futuramente.
 */
async function triggerAnalysis(payload: AnalyzeRequest): Promise<void> {
  const backendUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN;

  if (!backendUrl || !token) {
    console.warn("[triggerAnalysis] PYTHON_BACKEND_URL ou TOKEN não configurados.");
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5_000);

  try {
    await fetch(`${backendUrl}/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch {
    // Silenciado intencionalmente: fire-and-forget
    // O modelo fica com status 'pending' e pode ser reanalisado
  } finally {
    clearTimeout(timeout);
  }
}
