import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import type { ExecuteResponse, ExecutedPiece } from "@/types/database";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * POST /api/split-sessions/[id]/execute
 * Proxy seguro para POST /split-sessions/{id}/execute no mesh-service.
 * Após execução bem-sucedida, gera URLs assinadas (1h) para cada peça.
 */
export async function POST(request: NextRequest, { params }: RouteParams) {
  const { id: sessionId } = await params;

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const body = (await request.json()) as { cut_planes: unknown[] };

  const meshUrl =
    process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  try {
    const upstream = await fetch(
      `${meshUrl}/split-sessions/${sessionId}/execute`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ ...body, user_id: user.id }),
      },
    );

    if (!upstream.ok) {
      const errData: unknown = await upstream.json();
      return NextResponse.json(errData, { status: upstream.status });
    }

    const data = (await upstream.json()) as ExecuteResponse;

    // Gerar URLs assinadas (1 hora) para download de cada peça
    const admin = createAdminClient();
    const piecesWithUrls: ExecutedPiece[] = await Promise.all(
      data.pieces.map(async (piece) => {
        const { data: urlData } = await admin.storage
          .from("models")
          .createSignedUrl(piece.storage_path, 3600);
        return { ...piece, download_url: urlData?.signedUrl ?? null };
      }),
    );

    return NextResponse.json(
      { ...data, pieces: piecesWithUrls },
      { status: 200 },
    );
  } catch (err) {
    const msg =
      err instanceof Error && err.message.includes("ECONNREFUSED")
        ? "O serviço de análise não está rodando. Inicie o mesh-service e tente novamente."
        : `Erro ao conectar ao serviço de análise: ${String(err)}`;
    return NextResponse.json({ detail: msg }, { status: 503 });
  }
}
