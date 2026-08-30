"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { BuildPlate } from "@/types/database";

interface BuildPlateFormProps {
  /** Se passado, é edição; caso contrário, é criação */
  existing?: BuildPlate;
}

interface FormState {
  name: string;
  x: string;
  y: string;
  z: string;
  nozzle: string;
  isDefault: boolean;
}

export function BuildPlateForm({ existing }: BuildPlateFormProps) {
  const router = useRouter();
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

    // Validação
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

    router.push("/build-plates");
    router.refresh();
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Apelido */}
      <div>
        <label
          htmlFor="name"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Apelido da mesa *
        </label>
        <input
          id="name"
          type="text"
          required
          maxLength={80}
          value={form.name}
          onChange={(e) => setField("name", e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          placeholder="Ex: Minha Ender 3"
        />
      </div>

      {/* Dimensões */}
      <fieldset className="rounded-lg border border-gray-200 p-4">
        <legend className="px-1 text-sm font-medium text-gray-700">
          Volume de impressão *
        </legend>
        <p className="mb-3 text-xs text-gray-500">
          Use as dimensões exatas da área útil de impressão da sua impressora (em milímetros).
        </p>
        <div className="grid grid-cols-3 gap-3">
          {(
            [
              { id: "x", label: "Largura (X)", field: "x" as const },
              { id: "y", label: "Profundidade (Y)", field: "y" as const },
              { id: "z", label: "Altura (Z)", field: "z" as const },
            ] as const
          ).map(({ id, label, field }) => (
            <div key={id}>
              <label
                htmlFor={id}
                className="mb-1 block text-xs font-medium text-gray-600"
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
                  className="w-full rounded-md border border-gray-300 py-2 pl-3 pr-10 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
                  placeholder="256"
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                  mm
                </span>
              </div>
            </div>
          ))}
        </div>
      </fieldset>

      {/* Diâmetro do bico (opcional) */}
      <div>
        <label
          htmlFor="nozzle"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Diâmetro do bico{" "}
          <span className="font-normal text-gray-400">(opcional)</span>
        </label>
        <div className="relative max-w-[160px]">
          <input
            id="nozzle"
            type="number"
            min={0.1}
            max={2}
            step={0.1}
            value={form.nozzle}
            onChange={(e) => setField("nozzle", e.target.value)}
            className="w-full rounded-md border border-gray-300 py-2 pl-3 pr-10 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            placeholder="0.4"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
            mm
          </span>
        </div>
      </div>

      {/* Mesa padrão */}
      <label className="flex cursor-pointer items-center gap-2">
        <input
          type="checkbox"
          checked={form.isDefault}
          onChange={(e) => setField("isDefault", e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
        />
        <span className="text-sm text-gray-700">
          Usar como mesa padrão no visualizador
        </span>
      </label>

      <div className="flex gap-3 pt-2">
        <button
          type="submit"
          disabled={loading}
          className="rounded-md bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "Salvando…" : isEdit ? "Salvar alterações" : "Criar mesa"}
        </button>
        <a
          href="/build-plates"
          className="rounded-md border border-gray-300 px-5 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          Cancelar
        </a>
      </div>
    </form>
  );
}
