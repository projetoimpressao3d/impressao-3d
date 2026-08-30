# Plataforma de Impressão 3D

Plataforma web para divisão de modelos 3D em peças que cabem na mesa de impressão, com encaixes automáticos entre peças (plano pago).

> **Status:** Fase 1 — Fundação técnica. Nenhuma funcionalidade de produto implementada ainda.

---

## Pré-requisitos

| Ferramenta | Versão mínima | Download |
|---|---|---|
| Node.js | 20 LTS | https://nodejs.org |
| Python | 3.11+ | https://python.org |
| Git | qualquer | https://git-scm.com |
| Supabase CLI (opcional) | latest | https://supabase.com/docs/guides/cli |

---

## Estrutura do projeto

```
/
├── apps/
│   ├── web/              → Next.js 15 (frontend + API Routes leves)
│   └── mesh-service/     → FastAPI (corte, reparo e análise de malhas 3D)
├── packages/
│   └── shared-types/     → Tipos TypeScript/Pydantic compartilhados (Fase 2+)
├── .env.example          → Template de variáveis de ambiente
├── AGENTS.md             → Regras do projeto (lido automaticamente pelo Antigravity)
└── README.md             → Este arquivo
```

---

## Configuração inicial

### 1. Clone o repositório

```bash
git clone <url-do-repositorio>
cd projeto-impressao-3d
```

### 2. Configure as variáveis de ambiente

```bash
# Para o Next.js
cp .env.example apps/web/.env.local

# Para o mesh-service
cp .env.example apps/mesh-service/.env
```

Abra cada arquivo `.env` e preencha os valores. Veja os comentários no `.env.example` para saber onde obter cada chave.

---

## Rodando localmente

### Frontend — `/apps/web`

```bash
cd apps/web

# Instalar dependências
npm install

# Iniciar o servidor de desenvolvimento (http://localhost:3000)
npm run dev
```

**Outros comandos úteis:**

```bash
npm run lint          # ESLint
npm run lint:fix      # ESLint com correção automática
npm run format        # Prettier
npm run format:check  # Verificar formatação sem alterar arquivos
npm run typecheck     # Verificação de tipos TypeScript (sem emitir arquivos)
npm run build         # Build de produção
```

---

### Backend Python — `/apps/mesh-service`

```bash
cd apps/mesh-service

# Criar e ativar o ambiente virtual
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

# Instalar dependências
pip install -r requirements.txt

# Iniciar o servidor (http://localhost:8000)
uvicorn app.main:app --reload
```

**Verificar se está funcionando:**

```bash
curl http://localhost:8000/health
# Resposta esperada: {"status":"ok","version":"0.1.0","uptime_seconds":...}
```

**Documentação interativa da API:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

**Outros comandos úteis:**

```bash
ruff check .          # Lint
ruff check . --fix    # Lint com correção automática
ruff format .         # Formatação
```

---

## Banco de dados (Supabase)

### Opção A — Supabase em nuvem (recomendado para desenvolvimento)

1. Crie um projeto em https://app.supabase.com
2. Copie as chaves para `apps/web/.env.local`
3. Execute a migration inicial no SQL Editor do Supabase:
   ```
   apps/web/supabase/migrations/0001_init.sql
   ```

### Opção B — Supabase local (Docker)

```bash
# Instalar a Supabase CLI (se ainda não instalou)
npm install -g supabase

# Iniciar o Supabase local
cd apps/web
supabase start

# Aplicar migrations
supabase db push
```

> **Atenção:** O Supabase Free pausa o projeto após 7 dias de inatividade. Se a API parecer "fora do ar" após um período sem uso, acesse o dashboard e reative o projeto.

---

## Avisos importantes de infraestrutura

> ⚠️ **Vercel Functions têm timeout de 10s (Hobby) / 60s (Pro).** Processamento de malha 3D (corte, reparo, análise) DEVE rodar no `mesh-service` (Render), nunca em uma Vercel Function.

> ⚠️ **Vercel Hobby é restrito a uso não-comercial.** Ao ativar o Stripe, migre para o plano Vercel Pro.

> ⚠️ **Nunca commite arquivos `.env`, `.env.local` ou qualquer arquivo com chaves reais.** Use sempre o `.env.example` como referência.

---

## Convenções de commit

Usar [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: adiciona upload de arquivos STL
fix: corrige cálculo de bounding box
chore: atualiza dependências
refactor: extrai lógica de corte para módulo separado
test: adiciona testes para o endpoint de health
docs: atualiza README com instruções de deploy
```

---

## Roteiro de desenvolvimento

Veja o arquivo [ROTEIRO_DE_DESENVOLVIMENTO.md](./ROTEIRO_DE_DESENVOLVIMENTO.md) para o planejamento completo por fases.
