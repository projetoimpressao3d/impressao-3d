"use client";

import React, { useState, useRef } from "react";
import type { Model, UploadUrlResponse } from "@/types/database";
import { Badge } from "@/components/ui/badge";

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB
const ALLOWED_EXTENSIONS = ["stl", "3mf"] as const;
const ZIP_ALIASES: Record<string, string> = { zip: "3mf" };

type UploadState =
  | { status: "idle" }
  | { status: "validating" }
  | { status: "uploading"; progress: number; filename: string }
  | { status: "saving"; filename: string }
  | { status: "success"; filename: string }
  | { status: "error"; message: string };

function getExtension(filename: string): string {
  return filename.toLowerCase().split(".").pop() ?? "";
}

function normalizeFile(file: File): File {
  const ext = getExtension(file.name);
  const targetExt = ZIP_ALIASES[ext];
  if (!targetExt) return file;
  const newName = file.name.slice(0, -ext.length) + targetExt;
  return new File([file], newName, { type: file.type });
}

function formatDimensions(model: Model): string | null {
  const {
    bounding_box_x_mm: x,
    bounding_box_y_mm: y,
    bounding_box_z_mm: z,
  } = model;
  if (x == null || y == null || z == null) return null;
  return `${x.toFixed(1)} × ${y.toFixed(1)} × ${z.toFixed(1)} mm`;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

const STATUS_BADGE: Record<
  Model["printability_status"],
  { label: string; className: string }
> = {
  pending: {
    label: "Analisando…",
    className: "border-amber-500/40 bg-amber-500/15 text-amber-400",
  },
  ok: {
    label: "Pronto",
    className: "border-emerald-500/40 bg-emerald-500/15 text-emerald-400",
  },
  warning: {
    label: "Atenção",
    className: "border-orange-500/40 bg-orange-500/15 text-orange-400",
  },
  error: {
    label: "Erro",
    className: "border-red-500/40 bg-red-500/15 text-red-400",
  },
};

interface ModelsPropertiesPanelProps {
  models: Model[];
  selectedModelId?: string | null;
  userPlan: "free" | "pro";
  onSelectModel: (model: Model) => void;
  onModelsChanged: () => void;
}

export function ModelsPropertiesPanel({
  models,
  selectedModelId,
  userPlan,
  onSelectModel,
  onModelsChanged,
}: ModelsPropertiesPanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>({
    status: "idle",
  });
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const isFree = userPlan === "free";
  const atFreeLimit = isFree && models.length >= 1;
  const canDelete = userPlan === "pro";

  const isUploading =
    uploadState.status === "validating" ||
    uploadState.status === "uploading" ||
    uploadState.status === "saving";

  function validateFile(file: File): string | null {
    if (atFreeLimit) {
      return "O plano gratuito permite apenas 1 modelo. Faça upgrade para o plano Pro para enviar mais modelos.";
    }
    const ext = getExtension(file.name);
    const resolvedExt = ZIP_ALIASES[ext] ?? ext;
    if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(resolvedExt)) {
      return `Formato não suportado: .${ext}. Use STL ou 3MF.`;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `Arquivo muito grande (${(file.size / 1024 / 1024).toFixed(1)} MB). O limite é 50 MB.`;
    }
    return null;
  }

  async function processAndUploadFile(rawFile: File) {
    const validationError = validateFile(rawFile);
    if (validationError) {
      setUploadState({ status: "error", message: validationError });
      return;
    }

    const file = normalizeFile(rawFile);
    setUploadState({ status: "validating" });

    try {
      // 1. Obter URL assinada de upload
      const urlRes = await fetch(
        `/api/storage/upload-url?filename=${encodeURIComponent(file.name)}`,
      );
      if (!urlRes.ok) {
        const data = (await urlRes.json().catch(() => ({}))) as {
          error?: string;
        };
        setUploadState({
          status: "error",
          message: data.error ?? "Erro ao preparar upload.",
        });
        return;
      }

      const { signedUrl, storagePath, format } =
        (await urlRes.json()) as UploadUrlResponse;

      // 2. Upload direto para o Supabase Storage
      setUploadState({
        status: "uploading",
        progress: 0,
        filename: file.name,
      });

      await uploadWithProgress(file, signedUrl, (progress) => {
        setUploadState({
          status: "uploading",
          progress,
          filename: file.name,
        });
      });

      // 3. Criar registro na tabela models e disparar análise
      setUploadState({ status: "saving", filename: file.name });
      const name = file.name.replace(/\.[^.]+$/, "");
      const saveRes = await fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          storage_path: storagePath,
          format,
          original_filename: file.name,
        }),
      });

      if (!saveRes.ok) {
        const errData = (await saveRes.json().catch(() => ({}))) as {
          message?: string;
          error?: string;
        };
        setUploadState({
          status: "error",
          message:
            errData.message ?? errData.error ?? "Erro ao salvar modelo.",
        });
        return;
      }

      const savedData = (await saveRes.json().catch(() => ({}))) as {
        model?: Model;
      };

      setUploadState({ status: "success", filename: file.name });
      if (fileInputRef.current) fileInputRef.current.value = "";
      onModelsChanged();

      if (savedData.model) {
        onSelectModel(savedData.model);
      }

      setTimeout(() => {
        setUploadState((prev) =>
          prev.status === "success" ? { status: "idle" } : prev,
        );
      }, 2500);
    } catch {
      setUploadState({
        status: "error",
        message: "Erro inesperado. Verifique sua conexão e tente novamente.",
      });
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) void processAndUploadFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    if (isUploading) return;
    const file = e.dataTransfer.files[0];
    if (file) void processAndUploadFile(file);
  }

  async function handleDelete(e: React.MouseEvent, model: Model) {
    e.stopPropagation();
    if (!canDelete) return;
    if (
      !confirm(`Excluir "${model.name}"? Esta ação não pode ser desfeita.`)
    ) {
      return;
    }

    setDeletingId(model.id);
    try {
      const res = await fetch(`/api/models/${model.id}`, { method: "DELETE" });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as {
          message?: string;
        };
        alert(data.message ?? "Erro ao excluir modelo.");
        setDeletingId(null);
        return;
      }
      setDeletingId(null);
      onModelsChanged();
    } catch {
      alert("Erro de comunicação ao excluir modelo.");
      setDeletingId(null);
    }
  }

  return (
    <div className="flex flex-1 flex-col overflow-y-auto p-4">
      <input
        ref={fileInputRef}
        type="file"
        accept=".stl,.3mf,.zip"
        className="hidden"
        onChange={handleInputChange}
      />

      {/* Dropzone / Botão Grande: Enviar Modelo */}
      <button
        type="button"
        disabled={isUploading}
        onClick={() => {
          if (atFreeLimit) {
            setUploadState({
              status: "error",
              message:
                "Limite do plano gratuito atingido (1 modelo). Faça upgrade para o plano Pro.",
            });
            return;
          }
          fileInputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!isUploading) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`group flex flex-col items-center justify-center rounded-2xl border-2 border-dashed p-6 text-center transition-all ${
          dragOver
            ? "border-emerald-500 bg-emerald-950/30"
            : atFreeLimit
              ? "cursor-not-allowed border-zinc-800 bg-zinc-950/30 opacity-60"
              : "border-zinc-700 bg-zinc-950/60 hover:border-emerald-500/70 hover:bg-emerald-950/20"
        }`}
      >
        <div
          className={`flex h-20 w-20 items-center justify-center rounded-2xl border shadow-inner transition-colors ${
            dragOver
              ? "border-emerald-500 bg-emerald-600/20 text-emerald-400"
              : "border-zinc-700 bg-zinc-900 text-zinc-300 group-hover:border-emerald-500/60 group-hover:bg-emerald-600/20 group-hover:text-emerald-400"
          }`}
        >
          <svg
            className="h-10 w-10"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M12 4v16m8-8H4"
            />
          </svg>
        </div>

        <span className="mt-3 text-xs font-medium leading-snug text-zinc-200 group-hover:text-emerald-400">
          Enviar Modelo
        </span>
        <span className="mt-1 text-[10px] text-zinc-500">
          Arraste ou clique · STL, 3MF (máx. 50 MB)
        </span>
      </button>

      {/* Feedback de Progresso / Estado do Upload */}
      {uploadState.status === "uploading" && (
        <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950 p-3">
          <div className="mb-1.5 flex items-center justify-between text-[11px] text-zinc-300">
            <span className="truncate pr-2">
              Enviando {uploadState.filename}…
            </span>
            <span className="font-mono text-emerald-400">
              {uploadState.progress}%
            </span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all duration-200"
              style={{ width: `${uploadState.progress}%` }}
            />
          </div>
        </div>
      )}

      {uploadState.status === "saving" && (
        <div className="mt-3 rounded-xl border border-zinc-800 bg-zinc-950 p-3 text-center text-xs text-zinc-300">
          Salvando modelo e iniciando análise…
        </div>
      )}

      {uploadState.status === "success" && (
        <div className="mt-3 rounded-xl border border-emerald-500/40 bg-emerald-950/30 p-3 text-center text-xs text-emerald-400">
          Modelo enviado com sucesso!
        </div>
      )}

      {uploadState.status === "error" && (
        <div className="mt-3 rounded-xl border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-300">
          {uploadState.message}
        </div>
      )}

      {/* Divisor */}
      <div className="my-5 border-t border-zinc-800" />

      {/* Cabeçalho da Lista */}
      <div className="mb-2.5 flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-300">
          Modelos cadastrados:
        </span>
        <div className="flex items-center gap-1.5">
          {isFree && <Badge variant="default">Free · máx 1</Badge>}
          <span className="text-[11px] text-zinc-500">{models.length}</span>
        </div>
      </div>

      {/* Lista de Modelos */}
      {models.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-950/30 p-5 text-center">
          <p className="text-xs font-medium text-zinc-400">
            Nenhum modelo enviado
          </p>
          <p className="mt-1 text-[11px] text-zinc-500">
            Arraste seu arquivo STL ou 3MF para o botão &ldquo;+&rdquo; acima.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2.5">
          {models.map((model) => {
            const isSelected = selectedModelId === model.id;
            const isDeleting = deletingId === model.id;
            const dimensions = formatDimensions(model);
            const statusCfg = STATUS_BADGE[model.printability_status];

            return (
              <div
                key={model.id}
                onClick={() => onSelectModel(model)}
                className={`group cursor-pointer rounded-xl border p-3.5 transition-all ${
                  isSelected
                    ? "border-emerald-500 bg-emerald-950/20"
                    : "border-zinc-800 bg-zinc-950/60 hover:border-zinc-700 hover:bg-zinc-800/50"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span
                        className="truncate text-xs font-semibold text-zinc-100"
                        title={model.name}
                      >
                        {model.name}
                      </span>
                      <span className="shrink-0 rounded border border-zinc-700 bg-zinc-900 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase text-zinc-300">
                        {model.format}
                      </span>
                    </div>

                    {dimensions ? (
                      <p className="mt-1 font-mono text-xs text-emerald-400">
                        {dimensions}
                      </p>
                    ) : (
                      <p className="mt-1 text-[11px] text-zinc-500">
                        Dimensões em análise…
                      </p>
                    )}

                    <div className="mt-1.5 flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${statusCfg.className}`}
                      >
                        {statusCfg.label}
                      </span>
                      <span
                        className="text-[10px] text-zinc-500"
                        suppressHydrationWarning
                      >
                        {formatDate(model.created_at)}
                      </span>
                    </div>
                  </div>

                  {/* Ação de Excluir */}
                  <div className="flex shrink-0 items-center">
                    {canDelete ? (
                      <button
                        type="button"
                        disabled={isDeleting}
                        onClick={(e) => handleDelete(e, model)}
                        title="Excluir modelo"
                        className="rounded-lg border border-zinc-800 bg-zinc-900 p-1.5 text-zinc-400 transition-colors hover:border-red-500/40 hover:bg-red-950/40 hover:text-red-400 disabled:opacity-50"
                      >
                        <svg
                          className="h-3.5 w-3.5"
                          fill="none"
                          viewBox="0 0 24 24"
                          stroke="currentColor"
                          strokeWidth={1.8}
                        >
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                      </button>
                    ) : (
                      <span
                        title="A exclusão de modelos está disponível apenas no plano Pro."
                        className="cursor-not-allowed rounded-lg border border-zinc-800/60 bg-zinc-900/50 p-1.5 text-zinc-600 select-none"
                      >
                        🔒
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function uploadWithProgress(
  file: File,
  signedUrl: string,
  onProgress: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`Upload falhou com status ${xhr.status}`));
      }
    });

    xhr.addEventListener("error", () => reject(new Error("Falha de rede")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelado")));

    xhr.open("PUT", signedUrl);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.send(file);
  });
}
