import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

const RENDER_API_BASE = "https://api.render.com/v1/services";
const FALSE_VALUES = new Set(["false", "0", "no", "off"]);

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function POST(_request: NextRequest) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json({ detail: "Não autorizado" }, { status: 401 });
  }

  const meshUrl = process.env.PYTHON_BACKEND_URL?.trim();
  if (!meshUrl) {
    return NextResponse.json(
      {
        detail:
          "Serviço de processamento 3D não configurado. Configure PYTHON_BACKEND_URL no ambiente.",
      },
      { status: 503 },
    );
  }

  const baseUrl = meshUrl.replace(/\/+$/, "");

  try {
    const healthRes = await fetchWithTimeout(
      `${baseUrl}/health`,
      { method: "GET" },
      2500,
    );
    if (healthRes.ok) {
      const healthData = (await healthRes.json().catch(() => null)) as {
        status?: string;
      } | null;
      if (healthData?.status === "ok") {
        return NextResponse.json({ status: "ready" });
      }
    }
  } catch {
    // Serviço suspenso ou inicializando; segue para retomar via API do Render.
  }

  const renderApiKey = process.env.RENDER_API_KEY?.trim();
  const renderServiceId = process.env.RENDER_SERVICE_ID?.trim();
  const autoSuspendRaw = (process.env.RENDER_AUTO_SUSPEND_ENABLED ?? "true")
    .trim()
    .toLowerCase();
  const autoWakeEnabled = !FALSE_VALUES.has(autoSuspendRaw);

  if (renderApiKey && renderServiceId && autoWakeEnabled) {
    const renderHeaders: HeadersInit = {
      Authorization: `Bearer ${renderApiKey}`,
      Accept: "application/json",
    };

    try {
      const serviceRes = await fetchWithTimeout(
        `${RENDER_API_BASE}/${renderServiceId}`,
        { method: "GET", headers: renderHeaders },
        4000,
      );
      if (serviceRes.ok) {
        const serviceData = (await serviceRes.json().catch(() => null)) as {
          suspended?: string;
        } | null;

        if (serviceData?.suspended === "suspended") {
          await fetchWithTimeout(
            `${RENDER_API_BASE}/${renderServiceId}/resume`,
            { method: "POST", headers: renderHeaders },
            4000,
          );
          return NextResponse.json({ status: "starting", action: "resumed" });
        }
      }
      return NextResponse.json({ status: "starting", action: "booting" });
    } catch {
      return NextResponse.json({ status: "starting", action: "booting" });
    }
  }

  return NextResponse.json({ status: "starting", action: "waiting_health" });
}
