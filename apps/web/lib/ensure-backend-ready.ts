export interface EnsureReadyResponse {
  status?: "ready" | "starting";
  action?: string;
  detail?: string;
  error?: string;
}

/**
 * Garante que o backend Python no Render esteja ativo antes de iniciar um fluxo
 * de divisão. Caso esteja suspenso, dispara a retomada e aguarda até `/health`
 * responder OK (até ~3 minutos).
 */
export async function ensureBackendReady(
  onStatusChange?: (stage: string, progress?: number) => void,
): Promise<void> {
  const maxAttempts = 45;
  const pollIntervalMs = 4000;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const res = await fetch("/api/backend/ensure-ready", {
      method: "POST",
      cache: "no-store",
    });

    const data = (await res.json().catch(() => null)) as EnsureReadyResponse | null;

    if (!res.ok) {
      throw new Error(
        data?.detail ??
          data?.error ??
          `Falha ao verificar disponibilidade do servidor (${res.status}).`,
      );
    }

    if (data?.status === "ready") {
      return;
    }

    onStatusChange?.(
      "⚡ Inicializando servidor 3D no Render (aguarde ~1–2 min)...",
      Math.min(12, 3 + attempt),
    );

    if (attempt < maxAttempts) {
      await new Promise<void>((resolve) => setTimeout(resolve, pollIntervalMs));
    }
  }

  throw new Error(
    "O servidor de processamento 3D demorou demais para responder. Tente novamente em alguns instantes.",
  );
}
