import Link from "next/link";
import { UploadForm } from "@/components/models/upload-form";

export const metadata = { title: "Enviar Modelo" };

export default function UploadPage() {
  return (
    <div className="mx-auto max-w-lg">
      <div className="mb-6">
        <Link
          href="/models"
          className="text-sm text-gray-500 hover:text-gray-700"
        >
          ← Voltar para meus modelos
        </Link>
        <h1 className="mt-2 text-2xl font-bold text-gray-900">
          Enviar modelo 3D
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Após o envio, analisaremos automaticamente a qualidade da malha.
        </p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <UploadForm />
      </div>
    </div>
  );
}
