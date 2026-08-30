import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

const ALLOWED_FORMATS = ["stl", "3mf"] as const;
type AllowedFormat = (typeof ALLOWED_FORMATS)[number];

/**
 * GET /api/storage/upload-url?filename=modelo.stl
 *
 * Gera uma URL assinada de upload para o Supabase Storage.
 * O cliente faz o PUT diretamente no Storage — sem passar pelo Vercel Function.
 */
export async function GET(request: NextRequest) {
  // 1. Verificar autenticação
  const supabase = await createClient();
  const {
    data: { user },
    error: userError,
  } = await supabase.auth.getUser();

  if (userError ?? !user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  // 2. Validar parâmetros
  const { searchParams } = new URL(request.url);
  const filename = searchParams.get("filename");

  if (!filename) {
    return NextResponse.json(
      { error: "Parâmetro filename é obrigatório" },
      { status: 400 },
    );
  }

  const ext = filename.toLowerCase().split(".").pop();
  if (!ext || !(ALLOWED_FORMATS as readonly string[]).includes(ext)) {
    return NextResponse.json(
      { error: "Formato não suportado. Use STL ou 3MF." },
      { status: 400 },
    );
  }

  // 3. Gerar caminho único: {user_id}/{uuid}.{ext}
  const fileId = crypto.randomUUID();
  const storagePath = `${user.id}/${fileId}.${ext}`;

  // 4. Criar URL assinada de upload via service_role (contorna RLS do Storage)
  const admin = createAdminClient();
  const { data, error } = await admin.storage
    .from("models")
    .createSignedUploadUrl(storagePath);

  if (error ?? !data) {
    console.error("[upload-url] Erro ao criar signed URL:", error?.message);
    return NextResponse.json(
      { error: "Erro interno ao gerar URL de upload" },
      { status: 500 },
    );
  }

  return NextResponse.json({
    signedUrl: data.signedUrl,
    storagePath,
    format: ext as AllowedFormat,
  });
}
