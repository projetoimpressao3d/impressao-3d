/**
 * POST /api/split-sessions/[id]/general-split
 * Proxy para o backend Python que executa o General Split (BSP) garantindo que 100% das peças caibam na mesa.
 */
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const runtime = "nodejs";

interface GeneralSplitPayload {
  granularity?: "auto" | "low" | "medium" | "high";
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
    return NextResponse.json({ detail: "Não autenticado." }, { status: 401 });
  }

  const body = (await req.json().catch(() => ({}))) as Partial<GeneralSplitPayload>;
  const granularity = body.granularity ?? "auto";

  const backendUrl = process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  const res = await fetch(`${backendUrl}/split-sessions/${sessionId}/general-split`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      user_id: user.id,
      granularity,
    }),
  });

  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
