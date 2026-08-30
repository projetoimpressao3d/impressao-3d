import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import type { ExecutedPiece } from "@/types/database";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/split-sessions/[id]/pieces
 * Retorna as peças de uma split_session com URLs assinadas (1h) para download.
 */
export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { id: sessionId } = await params;

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  // Verificar que a sessão pertence ao usuário (RLS + verificação explícita)
  const { data: session } = await supabase
    .from("split_sessions")
    .select("id")
    .eq("id", sessionId)
    .eq("user_id", user.id)
    .single();

  if (!session) {
    return NextResponse.json(
      { error: "Sessão não encontrada" },
      { status: 404 },
    );
  }

  const { data: pieces } = await supabase
    .from("pieces")
    .select("*")
    .eq("split_session_id", sessionId)
    .order("piece_index", { ascending: true });

  if (!pieces || pieces.length === 0) {
    return NextResponse.json({ pieces: [] });
  }

  // Gerar URLs assinadas com service_role (admin)
  const admin = createAdminClient();
  const piecesWithUrls: ExecutedPiece[] = await Promise.all(
    pieces.map(async (piece) => {
      const { data: urlData } = await admin.storage
        .from("models")
        .createSignedUrl(piece.storage_path as string, 3600);
      return {
        ...(piece as ExecutedPiece),
        download_url: urlData?.signedUrl ?? null,
      };
    }),
  );

  return NextResponse.json({ pieces: piecesWithUrls });
}
