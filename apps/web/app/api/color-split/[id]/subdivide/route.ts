import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: modelId } = await params;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const body = (await request.json()) as {
    build_plate_id: string;
    extruder_number: number;
    mode?: string;
    character_template?: string;
    general_granularity?: string;
    structural_sensitivity?: number;
    generate_connectors?: boolean;
    connector_pin_shape?: string;
    connector_tolerance_mm?: number;
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
    const upstream = await fetch(`${meshUrl}/color-split/${modelId}/subdivide-piece`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ ...body, user_id: user.id }),
    });

    // Lê o body de forma segura — pode ser JSON ou texto puro em caso de erro
    const contentType = upstream.headers.get("content-type") ?? "";
    if (contentType.includes("application/json")) {
      const data = await upstream.json();
      return NextResponse.json(data, { status: upstream.status });
    } else {
      const text = await upstream.text();
      return NextResponse.json(
        { detail: text || `Erro HTTP ${upstream.status} do serviço de análise` },
        { status: upstream.status },
      );
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      {
        detail: `Não foi possível conectar ao serviço de análise de malha. Verifique se o backend Python está rodando.\n\nDetalhes: ${msg}`,
      },
      { status: 503 },
    );
  }
}
