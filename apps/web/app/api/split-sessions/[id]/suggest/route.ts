import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";
interface RouteParams { params: Promise<{ id: string }>; }
export interface SuggestApiResponse {
  split_session_id: string;
  cut_planes: Array<{ normal: number[]; origin: number[]; label: string; source: string; }>;
  natural_count: number; grid_count: number;
}
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id: sessionId } = await params;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Nao autorizado" }, { status: 401 });
  const meshUrl = process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";
  try {
    const url = `${meshUrl}/split-sessions/${sessionId}/suggest`;
    const upstream = await fetch(url, { method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ user_id: user.id }),
      signal: AbortSignal.timeout(120_000), });
    if (!upstream.ok) { const e: unknown = await upstream.json(); return NextResponse.json(e, { status: upstream.status }); }
    return NextResponse.json((await upstream.json()) as SuggestApiResponse, { status: 200 });
  } catch (err) {
    const msg = err instanceof Error && err.message.includes("ECONNREFUSED")
      ? "O servico de analise nao esta rodando. Inicie o mesh-service."
      : `Erro ao conectar ao servico de analise: ${String(err)}`;
    return NextResponse.json({ detail: msg }, { status: 503 });
  }
}
