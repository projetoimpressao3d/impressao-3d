import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

// Rotas que exigem autenticação
const PROTECTED_PREFIXES = ["/models", "/dashboard"];
// Rotas de autenticação (redirecionar se já logado)
const AUTH_PREFIXES = ["/login", "/register"];

export async function proxy(request: NextRequest) {
  let supabaseResponse = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(
          cookiesToSet: { name: string; value: string; options?: CookieOptions }[],
        ) {
          cookiesToSet.forEach(({ name, value }) =>
            request.cookies.set(name, value),
          );
          supabaseResponse = NextResponse.next({ request });
          cookiesToSet.forEach(({ name, value, options }) =>
            supabaseResponse.cookies.set(name, value, options as Parameters<typeof supabaseResponse.cookies.set>[2]),
          );
        },
      },
    },
  );

  // IMPORTANTE: usar getUser() (não getSession()) para verificar a sessão no servidor.
  // getSession() pode ser forjado; getUser() valida com o servidor Supabase.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some((p) => pathname.startsWith(p));
  const isAuthPage = AUTH_PREFIXES.some((p) => pathname.startsWith(p));

  // Rota protegida sem sessão → redireciona para login
  if (isProtected && !user) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Página de auth com sessão ativa → redireciona para models
  if (isAuthPage && user) {
    const modelsUrl = request.nextUrl.clone();
    modelsUrl.pathname = "/models";
    return NextResponse.redirect(modelsUrl);
  }

  return supabaseResponse;
}

export const config = {
  matcher: [
    /*
     * Aplica o proxy em todas as rotas exceto:
     * - _next/static (assets estáticos)
     * - _next/image (otimização de imagem)
     * - favicon.ico
     * - Arquivos com extensão (ex: .png, .svg)
     * - Rotas de API internas
     */
    "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};

