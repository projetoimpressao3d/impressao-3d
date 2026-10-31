import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: modelId } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const body = (await request.json()) as {
    build_plate_id: string;
    generate_connectors?: boolean;
    material?: string;
    connector_pin_shape?: string;
    cap_method?: string;
  };
  const meshUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  if (!meshUrl) {
    return NextResponse.json(
      {
        detail:
          "Serviço de análise não configurado. Configure o PYTHON_BACKEND_URL no ambiente.",
      },
      { status: 503 },
    );
  }

  try {
    const upstream = await fetch(`${meshUrl}/color-split/${modelId}/auto-split`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        ...body,
        user_id: user.id,
      }),
    });

    const contentType = upstream.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const data = await upstream.json();
      return NextResponse.json(data, { status: upstream.status });
    }
    const text = await upstream.text();
    return NextResponse.json(
      { detail: text || `Erro HTTP ${upstream.status}` },
      { status: upstream.status },
    );
  } catch (err) {
    return NextResponse.json({ detail: String(err) }, { status: 503 });
  }
}
