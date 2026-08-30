import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

/**
 * GET /api/build-plates
 * Lista todas as mesas de trabalho do usuário autenticado.
 */
export async function GET() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ error: "Não autorizado" }, { status: 401 });
  }

  const { data: plates, error } = await supabase
    .from("build_plates")
    .select("*")
    .order("created_at", { ascending: true });

  if (error) {
    return NextResponse.json({ error: "Erro ao buscar mesas" }, { status: 500 });
  }

  return NextResponse.json({ plates });
}

/**
 * POST /api/build-plates
 * Cria uma nova mesa de trabalho.
 * Se is_default=true, remove is_default das outras mesas do usuário.
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
    name: string;
    build_volume_x_mm: number;
    build_volume_y_mm: number;
    build_volume_z_mm: number;
    nozzle_diameter_mm?: number | null;
    is_default?: boolean;
  };

  const { name, build_volume_x_mm, build_volume_y_mm, build_volume_z_mm } = body;

  if (!name || !build_volume_x_mm || !build_volume_y_mm || !build_volume_z_mm) {
    return NextResponse.json(
      { error: "name e as três dimensões são obrigatórios" },
      { status: 400 },
    );
  }

  const admin = createAdminClient();

  // Se is_default=true, limpar flag das outras mesas deste usuário
  if (body.is_default) {
    await admin
      .from("build_plates")
      .update({ is_default: false })
      .eq("user_id", user.id);
  }

  const { data: plate, error } = await admin
    .from("build_plates")
    .insert({
      user_id: user.id,
      name,
      build_volume_x_mm,
      build_volume_y_mm,
      build_volume_z_mm,
      nozzle_diameter_mm: body.nozzle_diameter_mm ?? null,
      is_default: body.is_default ?? false,
    })
    .select()
    .single();

  if (error ?? !plate) {
    return NextResponse.json({ error: "Erro ao criar mesa" }, { status: 500 });
  }

  return NextResponse.json({ plate }, { status: 201 });
}
