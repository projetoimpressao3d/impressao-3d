"use client";

import { useState, useRef } from "react";
import { useRouter } from "next/navigation";
import type { UploadUrlResponse } from "@/types/database";

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB
const ALLOWED_EXTENSIONS = ["stl", "3mf"] as const;

type UploadState =
  | { status: "idle" }
  | { status: "validating" }
  | { status: "uploading"; progress: number }
  | { status: "saving" }
  | { status: "success" }
  | { status: "error"; message: string };

function getExtension(filename: string): string {
  return filename.toLowerCase().split(".").pop() ?? "";
}

export function UploadForm() {
  const router = useRouter();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [state, setState] = useState<UploadState>({ status: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  function validateFile(file: File): string | null {
    const ext = getExtension(file.name);
    if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
      return `Formato não suportado: .${ext}. Use STL ou 3MF.`;
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `Arquivo muito grande (${(file.size / 1024 / 1024).toFixed(1)} MB). O limite é 50 MB.`;
    }
    return null;
  }

  function handleFileSelect(file: File) {
    const error = validateFile(file);
    if (error) {
      setState({ status: "error", message: error });
      return;
    }
    setSelectedFile(file);
    setState({ status: "idle" });
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFileSelect(file);
  }

  async function handleUpload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!selectedFile) return;

    setState({ status: "validating" });

    try {
      // 1. Obter URL assinada de upload
      const urlRes = await fetch(
        `/api/storage/upload-url?filename=${encodeURIComponent(selectedFile.name)}`,
      );
      if (!urlRes.ok) {
        const { error } = (await urlRes.json()) as { error: string };
        setState({ status: "error", message: error ?? "Erro ao preparar upload." });
        return;
      }
      const { signedUrl, storagePath, format } =
        (await urlRes.json()) as UploadUrlResponse;

      // 2. Upload direto para o Supabase Storage (não passa pelo Vercel)
      setState({ status: "uploading", progress: 0 });
      await uploadWithProgress(selectedFile, signedUrl, (progress) => {
        setState({ status: "uploading", progress });
      });

      // 3. Criar registro na tabela models e disparar análise
      setState({ status: "saving" });
      const name = selectedFile.name.replace(/\.[^.]+$/, ""); // sem extensão
      const saveRes = await fetch("/api/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          storage_path: storagePath,
          format,
          original_filename: selectedFile.name,
        }),
      });

      if (!saveRes.ok) {
        setState({ status: "error", message: "Erro ao salvar modelo." });
        return;
      }

      setState({ status: "success" });
      setTimeout(() => router.push("/models"), 1500);
    } catch {
      setState({
        status: "error",
        message: "Erro inesperado. Verifique sua conexão e tente novamente.",
      });
    }
  }

  const isLoading =
    state.status === "validating" ||
    state.status === "uploading" ||
    state.status === "saving";

  return (
    <form onSubmit={handleUpload} className="space-y-6">
      {/* Área de drop */}
      <div
        className={`relative rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-brand-500 bg-brand-50"
            : selectedFile
              ? "border-green-400 bg-green-50"
              : "border-gray-300 bg-gray-50 hover:border-gray-400"
        }`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".stl,.3mf"
          className="hidden"
          onChange={handleInputChange}
        />

        {selectedFile ? (
          <div>
            <p className="text-2xl">✅</p>
            <p className="mt-2 font-medium text-gray-900">{selectedFile.name}</p>
            <p className="text-sm text-gray-500">
              {(selectedFile.size / 1024 / 1024).toFixed(2)} MB
            </p>
            <button
              type="button"
              onClick={() => {
                setSelectedFile(null);
                setState({ status: "idle" });
                if (fileInputRef.current) fileInputRef.current.value = "";
              }}
              className="mt-2 text-sm text-gray-500 underline hover:text-gray-700"
            >
              Trocar arquivo
            </button>
          </div>
        ) : (
          <div>
            <p className="text-3xl">📁</p>
            <p className="mt-2 font-medium text-gray-700">
              Arraste um arquivo aqui
            </p>
            <p className="text-sm text-gray-500">ou</p>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="mt-2 rounded-md border border-gray-300 bg-white px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Selecionar arquivo
            </button>
            <p className="mt-3 text-xs text-gray-400">
              Formatos: STL, 3MF · Máximo: 50 MB
            </p>
          </div>
        )}
      </div>

      {/* Barra de progresso */}
      {state.status === "uploading" && (
        <div>
          <div className="mb-1 flex justify-between text-xs text-gray-600">
            <span>Enviando…</span>
            <span>{state.progress}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
            <div
              className="h-full rounded-full bg-brand-600 transition-all duration-300"
              style={{ width: `${state.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Mensagens de estado */}
      {state.status === "saving" && (
        <p className="text-center text-sm text-gray-600">
          Salvando modelo e iniciando análise…
        </p>
      )}
      {state.status === "success" && (
        <div className="rounded-md border border-green-200 bg-green-50 p-3 text-center text-sm text-green-700">
          Modelo enviado com sucesso! Redirecionando…
        </div>
      )}
      {state.status === "error" && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {state.message}
        </div>
      )}

      <button
        type="submit"
        disabled={!selectedFile || isLoading}
        className="w-full rounded-md bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? "Enviando…" : "Enviar modelo"}
      </button>
    </form>
  );
}

// Upload com rastreamento de progresso via XMLHttpRequest
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
