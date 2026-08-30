import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * POST /api/split-sessions
 * Proxy seguro para POST /split-sessions no mesh-service.
 * Injeta o user_id autenticado (não confia no payload do cliente).
 */
export async function POST(request: NextRequest) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const body = (await request.json()) as {
    model_id: string;
    build_plate_id: string;
  };

  const meshUrl =
    process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  try {
    const upstream = await fetch(`${meshUrl}/split-sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ ...body, user_id: user.id }),
    });

    const data: unknown = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    // Mesh-service não está rodando ou não acessível
    const msg =
      err instanceof Error && err.message.includes("ECONNREFUSED")
        ? "O serviço de análise não está rodando. Inicie o mesh-service e tente novamente."
        : `Erro ao conectar ao serviço de análise: ${String(err)}`;
    return NextResponse.json(
      { detail: msg },
      { status: 503 },
    );
  }
}
