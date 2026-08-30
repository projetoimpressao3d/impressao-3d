"use client";

import { useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

type FormState = "idle" | "loading" | "success" | "error";

export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [state, setState] = useState<FormState>("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorMsg(null);

    if (password !== confirmPassword) {
      setErrorMsg("As senhas não coincidem.");
      return;
    }

    if (password.length < 8) {
      setErrorMsg("A senha precisa ter pelo menos 8 caracteres.");
      return;
    }

    setState("loading");

    const supabase = createClient();
    const { error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/api/auth/callback`,
      },
    });

    if (error) {
      setErrorMsg(
        error.message.includes("already registered")
          ? "Este email já está cadastrado. Tente fazer login."
          : "Erro ao criar conta. Tente novamente.",
      );
      setState("error");
      return;
    }

    setState("success");
  }

  if (state === "success") {
    return (
      <div className="text-center">
        <div className="mb-4 text-4xl">📧</div>
        <h3 className="mb-2 font-semibold text-gray-900">Verifique seu email</h3>
        <p className="text-sm text-gray-600">
          Enviamos um link de confirmação para{" "}
          <span className="font-medium">{email}</span>. Clique no link para
          ativar sua conta.
        </p>
        <p className="mt-4 text-sm text-gray-500">
          Já confirmou?{" "}
          <Link href="/login" className="text-brand-600 hover:underline">
            Entrar
          </Link>
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {errorMsg && (
        <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <div>
        <label
          htmlFor="email"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          placeholder="seu@email.com"
        />
      </div>

      <div>
        <label
          htmlFor="password"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Senha
        </label>
        <input
          id="password"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          placeholder="Mínimo 8 caracteres"
        />
      </div>

      <div>
        <label
          htmlFor="confirmPassword"
          className="mb-1 block text-sm font-medium text-gray-700"
        >
          Confirmar senha
        </label>
        <input
          id="confirmPassword"
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm placeholder-gray-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          placeholder="Repita a senha"
        />
      </div>

      <button
        type="submit"
        disabled={state === "loading"}
        className="w-full rounded-md bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-brand-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {state === "loading" ? "Criando conta…" : "Criar conta"}
      </button>

      <p className="text-center text-sm text-gray-600">
        Já tem conta?{" "}
        <Link href="/login" className="font-medium text-brand-600 hover:underline">
          Entrar
        </Link>
      </p>
    </form>
  );
}
