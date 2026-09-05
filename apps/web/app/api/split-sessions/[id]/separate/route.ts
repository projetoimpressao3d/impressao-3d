/**
 * POST /api/split-sessions/[id]/separate
 * Proxy para o backend Python que inicia o job assíncrono de separação estrutural.
 * Retorna 202 imediatamente — o frontend faz polling em /status.
 */
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const runtime = "nodejs";

interface SeparatePayload {
  structural_sensitivity: number;
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: sessionId } = await params;

  // Autenticar via Supabase
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ detail: "Nao autenticado." }, { status: 401 });
  }

  const body = (await req.json()) as Partial<SeparatePayload>;
  const sensitivity = typeof body.structural_sensitivity === "number"
    ? body.structural_sensitivity
    : 0.07;

  const backendUrl = process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  const res = await fetch(`${backendUrl}/split-sessions/${sessionId}/separate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      user_id: user.id,
      structural_sensitivity: sensitivity,
    }),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
