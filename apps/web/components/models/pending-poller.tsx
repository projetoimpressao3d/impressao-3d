"use client";

/**
 * PendingPoller â€” componente invisÃ­vel que chama router.refresh() periodicamente
 * enquanto houver modelos com status "pending" (Analisando...).
 *
 * Quando todos os modelos saÃ­rem de "pending", o polling para automaticamente.
 * Isso evita requisiÃ§Ãµes desnecessÃ¡rias quando nÃ£o hÃ¡ nada sendo analisado.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";

const POLL_INTERVAL_MS = 4_000; // checar a cada 4 segundos

interface PendingPollerProps {
  hasPending: boolean;
}

export function PendingPoller({ hasPending }: PendingPollerProps) {
  const router = useRouter();

  useEffect(() => {
    if (!hasPending) return; // nenhum modelo pendente â†’ nÃ£o fazer nada

    const intervalId = setInterval(() => {
      router.refresh(); // re-executa os Server Components da rota atual
    }, POLL_INTERVAL_MS);

    return () => clearInterval(intervalId); // limpar ao desmontar ou quando hasPending mudar
  }, [hasPending, router]);

  return null; // componente invisÃ­vel, sÃ³ lÃ³gica
}
