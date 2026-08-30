"use client";

import type { ExecutedPiece } from "@/types/database";

interface PieceDownloadProps {
  pieces: ExecutedPiece[];
  onClose: () => void;
}

/** Formata dimensões em mm. */
function fmm(v: number | null): string {
  return v != null ? v.toFixed(1) : "—";
}

/**
 * Painel de download exibido após a execução bem-sucedida do corte.
 * Mostra cada peça com suas dimensões, status de encaixe na mesa e link de download.
 */
export function PieceDownload({ pieces, onClose }: PieceDownloadProps) {
  const allFit = pieces.every((p) => p.fits_build_plate);

  return (
    <div className="mt-4 rounded-xl border border-green-200 bg-green-50">
      {/* Cabeçalho */}
      <div className="flex items-center justify-between border-b border-green-200 px-4 py-3">
        <div>
          <p className="text-sm font-semibold text-green-800">
            ✅ Corte concluído — {pieces.length} peça
            {pieces.length !== 1 ? "s" : ""} gerada
            {pieces.length !== 1 ? "s" : ""}
          </p>
          {allFit ? (
            <p className="mt-0.5 text-xs text-green-600">
              Todas as peças cabem na mesa de trabalho selecionada.
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-orange-600">
              Atenção: algumas peças podem não caber na mesa selecionada.
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-xs text-green-600 hover:text-green-800"
        >
          Fechar
        </button>
      </div>

      {/* Lista de peças */}
      <ul className="divide-y divide-green-100">
        {pieces
          .sort((a, b) => a.piece_index - b.piece_index)
          .map((piece) => (
            <li
              key={piece.id}
              className="flex items-center gap-3 px-4 py-3"
            >
              {/* Índice */}
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-green-200 text-sm font-semibold text-green-800">
                {piece.piece_index + 1}
              </div>

              {/* Informações */}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-gray-800">
                  Peça {piece.piece_index + 1}
                </p>
                <p className="text-xs text-gray-500">
                  {fmm(piece.bounding_box_x_mm)} ×{" "}
                  {fmm(piece.bounding_box_y_mm)} ×{" "}
                  {fmm(piece.bounding_box_z_mm)} mm
                  {" · "}
                  {piece.fits_build_plate ? (
                    <span className="text-green-600">✅ Cabe na mesa</span>
                  ) : (
                    <span className="text-red-500">❌ Não cabe na mesa</span>
                  )}
                </p>
              </div>

              {/* Botão de download */}
              {piece.download_url ? (
                <a
                  href={piece.download_url}
                  download={`peca_${piece.piece_index + 1}.stl`}
                  className="shrink-0 rounded-lg bg-green-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm transition hover:bg-green-700"
                >
                  ⬇ Baixar STL
                </a>
              ) : (
                <span className="shrink-0 text-xs text-gray-400">
                  URL expirada
                </span>
              )}
            </li>
          ))}
      </ul>

      {/* Rodapé */}
      <div className="border-t border-green-200 px-4 py-3">
        <p className="text-xs text-green-700">
          💡 As URLs de download expiram em <strong>1 hora</strong>. Se precisar
          baixar novamente depois, acesse as sessões de corte do modelo.
        </p>
      </div>
    </div>
  );
}
