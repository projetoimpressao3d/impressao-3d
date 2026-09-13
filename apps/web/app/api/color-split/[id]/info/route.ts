import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id: modelId } = await params;
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return NextResponse.json({ error: "Nao autorizado" }, { status: 401 });

  const meshUrl = process.env.PYTHON_BACKEND_URL ?? "http://localhost:8000";
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  try {
    const upstream = await fetch(
      `${meshUrl}/color-split/${modelId}/info?user_id=${user.id}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const data = await upstream.json();
    return NextResponse.json(data, { status: upstream.status });
  } catch (err) {
    return NextResponse.json({ detail: String(err) }, { status: 503 });
  }
}