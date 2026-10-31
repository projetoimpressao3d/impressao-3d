import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> },
) {
  const { taskId } = await params;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const meshUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  if (!meshUrl) {
    return NextResponse.json(
      { detail: "Serviço não configurado" },
      { status: 503 },
    );
  }

  try {
    const url = new URL(`${meshUrl}/color-split/tasks/${taskId}`);
    if (user?.id) {
      url.searchParams.set("user_id", user.id);
    }

    const upstream = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${token}` },
    });

    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    return NextResponse.json(
      { detail: "Erro de conexão" },
      { status: 503 },
    );
  }
}
