import { NextResponse, type NextRequest } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

interface RouteParams {
  params: Promise<{ id: string }>;
}

/**
 * GET /api/build-plates/[id]
 */
export async function GET(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const { data: plate, error } = await supabase
    .from("build_plates")
    .select("*")
    .eq("id", id)
    .single();

  if (error ?? !plate) {
    return NextResponse.json({ error: "Mesa não encontrada" }, { status: 404 });
  }

  return NextResponse.json({ plate });
}

/**
 * PUT /api/build-plates/[id]
 * Atualiza nome, dimensões e is_default de uma mesa de trabalho.
 */
export async function PUT(request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const body = (await request.json()) as {
    name?: string;
    build_volume_x_mm?: number;
    build_volume_y_mm?: number;
    build_volume_z_mm?: number;
    nozzle_diameter_mm?: number | null;
    is_default?: boolean;
  };

  const admin = createAdminClient();

  // Se is_default=true, limpar flag das outras mesas deste usuário
  if (body.is_default) {
    await admin
      .from("build_plates")
      .update({ is_default: false })
      .eq("user_id", user.id)
      .neq("id", id);
  }

  const { data: plate, error } = await admin
    .from("build_plates")
    .update({
      ...(body.name && { name: body.name }),
      ...(body.build_volume_x_mm && { build_volume_x_mm: body.build_volume_x_mm }),
      ...(body.build_volume_y_mm && { build_volume_y_mm: body.build_volume_y_mm }),
      ...(body.build_volume_z_mm && { build_volume_z_mm: body.build_volume_z_mm }),
      ...(body.nozzle_diameter_mm !== undefined && {
        nozzle_diameter_mm: body.nozzle_diameter_mm,
      }),
      ...(body.is_default !== undefined && { is_default: body.is_default }),
    })
    .eq("id", id)
    .eq("user_id", user.id) // garante que só edita a própria mesa
    .select()
    .single();

  if (error ?? !plate) {
    return NextResponse.json({ error: "Erro ao atualizar mesa" }, { status: 500 });
  }

  return NextResponse.json({ plate });
}

/**
 * DELETE /api/build-plates/[id]
 */
export async function DELETE(_request: NextRequest, { params }: RouteParams) {
  const { id } = await params;
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Não autorizado" }, { status: 401 });

  const admin = createAdminClient();
  const { error } = await admin
    .from("build_plates")
    .delete()
    .eq("id", id)
    .eq("user_id", user.id);

  if (error) {
    return NextResponse.json({ error: "Erro ao excluir mesa" }, { status: 500 });
  }

  return NextResponse.json({ ok: true });
}
