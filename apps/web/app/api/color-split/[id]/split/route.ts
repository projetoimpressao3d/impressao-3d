import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: modelId } = await params;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Nao autorizado" }, { status: 401 });

  const body = (await request.json()) as {
    build_plate_id: string;
    cap_method?: string;
    snap_to_floor?: boolean;
  };
  const meshUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  if (!meshUrl) {
    return NextResponse.json(
      { detail: "Serviço de análise não configurado. Configure o PYTHON_BACKEND_URL no ambiente." },
      { status: 503 },
    );
  }

  try {
    const upstream = await fetch(`${meshUrl}/color-split/${modelId}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ...body, user_id: user.id }),
    });
    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    return NextResponse.json({ detail: String(err) }, { status: 503 });
  }
}