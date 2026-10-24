"use client";

import React, { useState, useEffect } from "react";
import type { BuildPlate } from "@/types/database";

interface BuildPlateModalProps {
  existing?: BuildPlate | null;
  onClose: () => void;
  onSaved: () => void;
}

interface FormState {
  name: string;
  x: string;
  y: string;
  z: string;
  nozzle: string;
  isDefault: boolean;
}

export function BuildPlateModal({
  existing,
  onClose,
  onSaved,
}: BuildPlateModalProps) {
  const isEdit = !!existing;

  const [form, setForm] = useState<FormState>({
    name: existing?.name ?? "",
    x: existing?.build_volume_x_mm?.toString() ?? "",
    y: existing?.build_volume_y_mm?.toString() ?? "",
    z: existing?.build_volume_z_mm?.toString() ?? "",
    nozzle: existing?.nozzle_diameter_mm?.toString() ?? "",
    isDefault: existing?.is_default ?? false,
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setForm({
      name: existing?.name ?? "",
      x: existing?.build_volume_x_mm?.toString() ?? "",
      y: existing?.build_volume_y_mm?.toString() ?? "",
      z: existing?.build_volume_z_mm?.toString() ?? "",
      nozzle: existing?.nozzle_diameter_mm?.toString() ?? "",
      isDefault: existing?.is_default ?? false,
    });
    setError(null);
  }, [existing]);

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function validateDimension(value: string, label: string): string | null {
    const num = parseFloat(value);
    if (isNaN(num) || num <= 0) return `${label} precisa ser maior que 0`;
    if (num > 10000) return `${label} não pode ultrapassar 10.000 mm`;
    return null;
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const erros = [
      !form.name.trim() ? "O apelido é obrigatório." : null,
      validateDimension(form.x, "Largura (X)"),
      validateDimension(form.y, "Profundidade (Y)"),
      validateDimension(form.z, "Altura (Z)"),
    ].filter(Boolean);

    if (erros.length > 0) {
      setError(erros[0]!);
      return;
    }

    setLoading(true);

    const payload = {
      name: form.name.trim(),
      build_volume_x_mm: parseFloat(form.x),
      build_volume_y_mm: parseFloat(form.y),
      build_volume_z_mm: parseFloat(form.z),
      nozzle_diameter_mm: form.nozzle ? parseFloat(form.nozzle) : null,
      is_default: form.isDefault,
    };

    const url = isEdit
      ? `/api/build-plates/${existing!.id}`
      : "/api/build-plates";
    const method = isEdit ? "PUT" : "POST";

    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const data = (await res.json()) as { error?: string };
        setError(data.error ?? "Erro ao salvar mesa. Tente novamente.");
        setLoading(false);
        return;
      }

      setLoading(false);
      onSaved();
    } catch {
      setError("Erro de comunicação ao salvar mesa.");
      setLoading(false);
    }
  }

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-zinc-950/70 p-6 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-2xl border border-zinc-800 bg-zinc-900 p-6 shadow-2xl">
        {/* Cabeçalho do Popup */}
        <div className="mb-5 flex items-center justify-between border-b border-zinc-800 pb-4">
          <div>
            <h3 className="text-base font-semibold text-zinc-100">
              {isEdit
                ? "Editar mesa de trabalho"
                : "Cadastrar nova mesa de trabalho"}
            </h3>
            <p className="mt-0.5 text-xs text-zinc-400">
              Defina o apelido e as dimensões da área útil da sua impressora.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 transition-colors hover:bg-zinc-800 hover:text-zinc-200"
            title="Fechar"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {error && (
            <div className="rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-xs text-red-300">
              {error}
            </div>
          )}

          {/* Apelido da Mesa */}
          <div>
            <label
              htmlFor="plate-name"
              className="mb-1.5 block text-xs font-medium text-zinc-300"
            >
              Apelido da Mesa *
            </label>
            <input
              id="plate-name"
              type="text"
              required
              maxLength={80}
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
              className="w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3.5 py-2.5 text-sm text-zinc-100 placeholder-zinc-500 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
              placeholder="Ex: Minha Impressora / Bambu A1 Mini"
            />
          </div>

          {/* Volume de impressão */}
          <div>
            <label className="mb-1 block text-xs font-medium text-zinc-300">
              Volume de impressão *
            </label>
            <p className="mb-2.5 text-[11px] text-zinc-500">
              Use as dimensões exatas da área útil da sua impressora (em mm).
            </p>
            <div className="grid grid-cols-3 gap-3">
              {(
                [
                  { id: "plate-x", label: "Largura (X)", field: "x" as const },
                  {
                    id: "plate-y",
                    label: "Profundidade (Y)",
                    field: "y" as const,
                  },
                  { id: "plate-z", label: "Altura (Z)", field: "z" as const },
                ] as const
              ).map(({ id, label, field }) => (
                <div key={id}>
                  <label
                    htmlFor={id}
                    className="mb-1 block text-[11px] font-medium text-zinc-400"
                  >
                    {label}
                  </label>
                  <div className="relative">
                    <input
                      id={id}
                      type="number"
                      required
                      min={1}
                      max={10000}
                      step={0.1}
                      value={form[field]}
                      onChange={(e) => setField(field, e.target.value)}
                      className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2 pl-3 pr-9 text-sm text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                      placeholder="256"
                    />
                    <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-zinc-500">
                      mm
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Diâmetro do bico (Opcional) */}
          <div>
            <label
              htmlFor="plate-nozzle"
              className="mb-1.5 block text-xs font-medium text-zinc-300"
            >
              Diâmetro do bico{" "}
              <span className="font-normal text-zinc-500">(Opcional)</span>
            </label>
            <div className="relative max-w-[160px]">
              <input
                id="plate-nozzle"
                type="number"
                min={0.1}
                max={2}
                step={0.1}
                value={form.nozzle}
                onChange={(e) => setField("nozzle", e.target.value)}
                className="w-full rounded-lg border border-zinc-700 bg-zinc-950 py-2 pl-3 pr-9 text-sm text-zinc-100 placeholder-zinc-600 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/20"
                placeholder="0.4"
              />
              <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-[11px] text-zinc-500">
                mm
              </span>
            </div>
          </div>

          {/* Mesa padrão */}
          <label className="flex cursor-pointer items-center gap-2.5 pt-1">
            <input
              type="checkbox"
              checked={form.isDefault}
              onChange={(e) => setField("isDefault", e.target.checked)}
              className="h-4 w-4 rounded border-zinc-700 bg-zinc-950 text-emerald-500 focus:ring-emerald-500/30"
            />
            <span className="text-xs text-zinc-300">
              Usar como mesa padrão no visualizador
            </span>
          </label>

          {/* Ações */}
          <div className="flex items-center justify-center gap-3 border-t border-zinc-800 pt-5">
            <button
              type="submit"
              disabled={loading}
              className="min-w-[130px] rounded-xl border border-emerald-500/50 bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading
                ? "Salvando…"
                : isEdit
                  ? "Salvar alterações"
                  : "Criar mesa"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="min-w-[130px] rounded-xl border border-zinc-700 bg-zinc-800 px-5 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:bg-zinc-700 hover:text-zinc-100"
            >
              Cancelar
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
