import { NextResponse, type NextRequest } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ taskId: string }> },
) {
  const { taskId } = await params;
  const meshUrl = process.env.PYTHON_BACKEND_URL;
  const token = process.env.PYTHON_BACKEND_INTERNAL_TOKEN ?? "";

  if (!meshUrl) {
    return NextResponse.json(
      { detail: "Serviço não configurado" },
      { status: 503 },
    );
  }

  try {
    const upstream = await fetch(`${meshUrl}/color-split/tasks/${taskId}`, {
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
