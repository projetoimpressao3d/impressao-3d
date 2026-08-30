import Link from "next/link";
import { BuildPlateForm } from "@/components/build-plates/build-plate-form";

export const metadata = { title: "Nova Mesa de Trabalho" };

export default function NewBuildPlatePage() {
  return (
    <div className="mx-auto max-w-xl">
      <div className="mb-6">
        <Link
          href="/build-plates"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← Voltar para mesas
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">
          Nova mesa de trabalho
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Informe as dimensões da área útil de impressão da sua impressora.
        </p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <BuildPlateForm />
      </div>
    </div>
  );
}
