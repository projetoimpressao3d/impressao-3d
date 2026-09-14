import { NextResponse, type NextRequest, after } from "next/server";
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

  // ── Verificar limite do plano ─────────────────────────────────────────────
  // Plano free: máximo de 1 modelo. Plano pro: ilimitado.
  const { data: profile } = await supabase
    .from("profiles")
    .select("plan")
    .eq("id", user.id)
    .single();

  if (profile?.plan === "free") {
    const { count } = await supabase
      .from("models")
      .select("*", { count: "exact", head: true });

    if ((count ?? 0) >= 1) {
      return NextResponse.json(
        {
          error: "PLAN_LIMIT",
          message:
            "O plano gratuito permite apenas 1 modelo. Faça upgrade para o plano Pro para enviar mais modelos.",
        },
        { status: 403 },
      );
    }
  }
  // ─────────────────────────────────────────────────────────────────────────

  // Se o backend não está configurado, não há como analisar — criar como "ok"
  // para não deixar o modelo preso em "Analisando..." para sempre.
  const backendConfigured = !!(
    process.env.PYTHON_BACKEND_URL && process.env.PYTHON_BACKEND_INTERNAL_TOKEN
  );
  const initialStatus = backendConfigured ? "pending" : "ok";

  // Criar registro com status inicial
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
      printability_status: initialStatus,
    })
    .select()
    .single();

  if (error ?? !model) {
    console.error("[POST /api/models] Erro ao criar modelo:", error?.message);
    return NextResponse.json({ error: "Erro ao salvar modelo" }, { status: 500 });
  }

  // after() garante que triggerAnalysis rode APÓS a resposta ser enviada
  // e mantém o contexto de execução do Vercel vivo até a chamada completar.
  // Isso resolve o problema do void (fire-and-forget) ser descartado quando
  // a função serverless encerra após enviar a resposta 201.
  after(async () => {
    await triggerAnalysis({
      model_id: model.id as string,
      storage_path: model.storage_path as string,
      user_id: user.id,
    });
  });

  return NextResponse.json({ model }, { status: 201 });
}

/**
 * Chama o mesh-service para analisar a malha 3D.
 * Timeout de 90s — suficiente para o cold start do Render free tier (30-60s).
 *
 * Se o backend não responder (serviço dormindo, erro de rede, timeout),
 * o modelo é automaticamente marcado como "ok" para não ficar preso
 * em "Analisando..." para sempre. O analyze endpoint atualiza o status
 * correto quando a análise completa com sucesso.
 */
async function triggerAnalysis(payload: AnalyzeRequest): Promise<void> {
  const backendUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN;

  if (!backendUrl || !token) {
    console.warn("[triggerAnalysis] PYTHON_BACKEND_URL ou TOKEN não configurados.");
    return;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 90_000);

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
  } catch (err) {
    // Se o backend não respondeu (cold start expirou, rede, etc.)
    // marcar o modelo como "ok" para o usuário conseguir usá-lo
    console.warn(
      `[triggerAnalysis] Backend não respondeu (${err}). Marcando modelo ${payload.model_id} como ok.`,
    );
    try {
      const admin = createAdminClient();
      await admin
        .from("models")
        .update({ printability_status: "ok" })
        .eq("id", payload.model_id);
    } catch (updateErr) {
      console.error("[triggerAnalysis] Falha ao atualizar status fallback:", updateErr);
    }
  } finally {
    clearTimeout(timeout);
  }
}
