export default function HomePage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8">
      <div className="max-w-2xl text-center">
        <h1 className="mb-4 text-4xl font-bold tracking-tight text-gray-900 dark:text-white">
          Plataforma de Impressão 3D
        </h1>
        <p className="mb-8 text-lg text-gray-600 dark:text-gray-300">
          Divida seus modelos 3D em peças que cabem na sua mesa de impressão.
        </p>
        <div className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 dark:border-gray-700 dark:bg-gray-900">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            🚧 Em desenvolvimento — Fase 1 (Fundação)
          </p>
        </div>
      </div>
    </main>
  );
}
