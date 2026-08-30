# AGENTS.md — Regras do projeto

> Este arquivo é lido automaticamente pelo Google Antigravity em toda tarefa neste workspace.
> Ele descreve o que estamos construindo, como construir, e os limites que não podem ser
> ultrapassados. Sempre que uma instrução de tarefa conflitar com este arquivo, este arquivo
> tem prioridade — pergunte ao usuário antes de desviar.

## 1. Visão geral do projeto

Uma plataforma web de renderização e preparação de projetos para impressão 3D. O usuário
sobe (ou gera via IA) um modelo 3D, visualiza no navegador, e a funcionalidade central da
plataforma **divide o modelo em peças que cabem na mesa de trabalho definida por ele**,
gerando arquivos prontos para impressão e, opcionalmente, encaixes automáticos entre as peças.

Público-alvo inicial: hobbistas/makers e pequenos negócios de impressão 3D.
Modelo de negócio: freemium (funcionalidades básicas grátis, IA e encaixes automáticos pagos).

**Funcionalidade central (prioridade máxima):** divisor de modelos por mesa de trabalho,
com corte assistido pelo usuário (não automático) — ver seção 5.4.

## 2. Stack tecnológico obrigatório

Não substitua nenhuma peça desta stack sem confirmar com o usuário — ela foi escolhida
deliberadamente para caber nos free tiers do Vercel, Supabase e Render durante a fase de MVP.

| Camada | Tecnologia |
|---|---|
| Frontend | Next.js (App Router) + TypeScript (modo strict) + Tailwind CSS |
| Visualizador 3D | three.js via `@react-three/fiber` + `@react-three/drei` |
| Hospedagem frontend | Vercel |
| API leve / CRUD | Next.js Route Handlers (Vercel Functions) — **nunca** rodar processamento de malha 3D aqui |
| Backend pesado | Python 3.11+ com FastAPI, hospedado no Render |
| Corte e reparo de malha | `manifold3d` (operações booleanas robustas) + `trimesh` (I/O, reparo, análise) |
| Banco de dados / Auth / Storage | Supabase (Postgres + Supabase Auth + Supabase Storage) |
| Geração 3D via IA (fase 2, não MVP) | Meshy AI API |
| Assistente / sugestão de config. de impressão (fase 2, não MVP) | Claude API (Anthropic) |
| Pagamentos | Stripe |
| CI/CD | GitHub Actions + deploy automático da Vercel |

**Formatos de arquivo 3D suportados no MVP:** STL e 3MF (upload e download).
OBJ e GLTF/GLB entram depois, apenas para visualização — não são prioridade agora.
STEP/IGES (CAD paramétrico) está **fora de escopo** — não implementar.

## 3. Restrição crítica de infraestrutura

⚠️ **Vercel Functions têm timeout de 10s no plano Hobby (60s no Pro).** Qualquer operação que
envolva leitura/escrita de malha 3D, corte booleano, capping, geração de peças ou chamadas à
Meshy/Claude **deve rodar no backend Python (Render)**, nunca em uma Vercel Function. O Next.js
só deve orquestrar: autenticar a requisição, validar input, chamar o backend Python, e retornar
o resultado.

⚠️ **Vercel Hobby é restrito a uso não-comercial.** Assim que o Stripe for ativado (fase de
monetização), o projeto Vercel precisa estar no plano Pro. Não é bloqueante para o
desenvolvimento, mas o agente deve avisar o usuário quando a fase de monetização começar.

⚠️ **Supabase Free pausa o projeto após 7 dias de inatividade.** Isso não afeta o código, mas
pode afetar testes/demos — não é um bug se a API do Supabase parecer "fora do ar" após um
período sem uso.

## 4. Estrutura de repositórios

Usar dois pacotes dentro do mesmo repositório (monorepo simples, sem necessidade de
ferramentas como Turborepo no MVP):

```
/apps
  /web              → Next.js (frontend + API routes leves)
  /mesh-service      → FastAPI (corte, reparo, análise geométrica)
/packages
  /shared-types      → tipos TypeScript/Pydantic compartilhados (contratos de API)
AGENTS.md
ROTEIRO_DE_DESENVOLVIMENTO.md
README.md
```

## 5. Modelo de dados (Supabase / Postgres)

Usar Row Level Security (RLS) em todas as tabelas abaixo — cada usuário só pode ler/escrever
seus próprios registros, exceto onde indicado.

```sql
-- Perfil público do usuário (auth.users já existe via Supabase Auth)
create table profiles (
  id uuid primary key references auth.users(id),
  display_name text,
  plan text not null default 'free', -- 'free' | 'pro'
  created_at timestamptz not null default now()
);

-- Mesas de trabalho cadastradas pelo usuário (dimensões definidas manualmente,
-- sem vínculo com nenhum catálogo de modelos de impressora)
create table build_plates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  name text not null, -- apelido dado pelo próprio usuário, ex: "Minha impressora"
  build_volume_x_mm numeric not null,
  build_volume_y_mm numeric not null,
  build_volume_z_mm numeric not null,
  nozzle_diameter_mm numeric,
  is_default boolean not null default false,
  created_at timestamptz not null default now()
);

-- Modelos 3D (enviados ou gerados por IA)
create table models (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  name text not null,
  original_filename text,
  storage_path text not null,      -- caminho no Supabase Storage
  format text not null,            -- 'stl' | '3mf' | 'obj' | 'gltf'
  source text not null default 'upload', -- 'upload' | 'ai_generated'
  bounding_box_x_mm numeric,
  bounding_box_y_mm numeric,
  bounding_box_z_mm numeric,
  printability_status text default 'pending', -- 'pending' | 'ok' | 'warning' | 'error'
  printability_report jsonb,
  created_at timestamptz not null default now()
);

-- Sessão de divisão de um modelo
create table split_sessions (
  id uuid primary key default gen_random_uuid(),
  model_id uuid not null references models(id),
  user_id uuid not null references auth.users(id),
  build_plate_id uuid not null references build_plates(id),
  status text not null default 'draft', -- 'draft' | 'processing' | 'completed' | 'failed'
  cut_planes jsonb not null default '[]', -- [{ "position": [x,y,z], "normal": [x,y,z] }, ...]
  has_connectors boolean not null default false,
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

-- Peças resultantes de uma divisão
create table pieces (
  id uuid primary key default gen_random_uuid(),
  split_session_id uuid not null references split_sessions(id),
  piece_index int not null,
  storage_path text not null,
  bounding_box_x_mm numeric,
  bounding_box_y_mm numeric,
  bounding_box_z_mm numeric,
  fits_build_plate boolean not null,
  created_at timestamptz not null default now()
);

-- Assinatura (Stripe)
create table subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  stripe_customer_id text,
  stripe_subscription_id text,
  plan text not null default 'free',
  status text not null default 'active',
  current_period_end timestamptz
);

-- Contador de uso mensal (para limitar o plano grátis)
create table usage_counters (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id),
  month date not null, -- primeiro dia do mês, ex: 2026-08-01
  ai_generations_used int not null default 0,
  splits_used int not null default 0,
  connectors_used int not null default 0,
  unique (user_id, month)
);
```

## 6. Especificação das funcionalidades

### 6.1 Autenticação
Supabase Auth (email/senha + login social opcional). Middleware do Next.js protege rotas
autenticadas. Ao criar conta, criar automaticamente uma linha em `profiles` com `plan = 'free'`.

### 6.2 Upload e visualizador 3D
- Upload de STL/3MF para Supabase Storage (bucket privado, URLs assinadas).
- Limite de tamanho de arquivo: 50MB no MVP (ajustável).
- Visualizador com `@react-three/fiber`: carregar o `STLLoader`/parser de 3MF, permitir
  rotação, zoom, pan, e exibir dimensões (bounding box) do modelo sobre a cena.
- Ao terminar o upload, chamar o backend Python para calcular bounding box e rodar a checagem
  de "printability" (malha fechada, sem furos, sem geometria não-manifold) — usar `trimesh`.

### 6.3 Mesa de trabalho
CRUD simples de `build_plates`. **O usuário não escolhe um modelo de impressora de um
catálogo** — ele define diretamente as dimensões da própria mesa de trabalho (largura,
profundidade e altura em mm, ex: 256x256x256) e dá um apelido de sua escolha (ex: "Minha
impressora"). Não implementar nenhuma lista de modelos comerciais de impressora pré-cadastrada.

### 6.4 Divisor de peças (funcionalidade central — MVP)

**Fluxo funcional (não mudar sem aprovação do usuário):**

1. Usuário seleciona um modelo e uma mesa de trabalho.
2. Backend compara a bounding box do modelo com as dimensões da mesa de trabalho.
   Se já cabe em todos os eixos, pular direto para o passo 6 (nenhum corte necessário).
3. Se não cabe, o backend calcula o número mínimo de cortes necessários por eixo
   (`ceil(dimensão_modelo / dimensão_mesa)`) e retorna posições de corte sugeridas
   (divisão em partes aproximadamente iguais) — isso é heurística simples, **não é IA**.
4. No frontend, o usuário vê o modelo com um ou mais planos de corte sobrepostos
   (usar `THREE.Plane` + `material.clippingPlanes` para o preview, é performático e não exige
   recomputar geometria a cada movimento). O usuário arrasta/gira os planos
   (`TransformControls` do drei). A cada movimento, o frontend recalcula localmente a bounding
   box de cada pedaço resultante e mostra visualmente se cabe (verde) ou não (vermelho) na
   mesa de trabalho.
5. Ao confirmar, o frontend envia os planos de corte definitivos para o backend Python
   (`POST /split-sessions/{id}/execute`), que:
   a. Roda um passo de reparo prévio na malha (`trimesh` — fechar buracos, corrigir normais)
      para aumentar a robustez do corte.
   b. Executa o corte booleano real com `manifold3d`, um plano por vez.
   c. Tampa ("cap") cada face aberta resultante do corte, garantindo malha fechada (watertight).
   d. Valida que cada peça resultante é manifold e cabe na mesa de trabalho informada.
   e. Salva cada peça como um arquivo STL/3MF separado no Storage e cria as linhas em `pieces`.
6. Usuário baixa as peças (arquivo por peça, ou um único 3MF com múltiplos objetos) junto com
   um guia de montagem simples (ordem das peças, ilustração básica).

**Regra de negócio — plano grátis vs pago:**
- Plano grátis: cortes planos simples, sem geometria de encaixe. Limite de N divisões/mês
  (usar `usage_counters.splits_used`, valor exato de N a definir com o usuário).
- Plano pago: além dos cortes, gerar encaixes automáticos (pino + furo) nas faces de corte.
  Tolerância entre pino e furo configurável por material (ex: PLA ≈ 0,2mm de folga por lado;
  manter essa tabela de tolerâncias em um arquivo de configuração, não hardcoded no meio da
  lógica de corte). Incrementar `usage_counters.connectors_used`.

**Não implementar nesta fase:** segmentação automática por IA/visão computacional
("cortes inteligentes" que decidem sozinhos onde cortar seguindo contornos do objeto). O
usuário decidiu explicitamente que a v1 é corte assistido pelo usuário, não automático.

### 6.5 Geração de modelo via IA (fase 2 — depois do MVP)
Integração com a API da Meshy (text-to-3D e image-to-3D). Ver documentação oficial em
`https://docs.meshy.ai` antes de implementar — a API é paga por crédito (pay-before-you-go,
sem mensalidade fixa) e os modelos gerados pelo endpoint de geração expiram em poucos dias se
a conta não for Enterprise, então é preciso baixar e persistir no nosso Storage imediatamente
após a geração. **Não depender da funcionalidade "Auto Split" da Meshy** — ela hoje só
funciona dentro do produto deles e é limitada a modelos gerados na própria Meshy; o nosso
divisor (seção 6.4) é implementação própria e deve continuar sendo a fonte de verdade.

### 6.6 Sugestão de configuração de impressão (fase 2)
Endpoint que recebe material + mesa de trabalho e chama a API da Claude com um prompt
estruturado, cruzando com uma tabela de regras/valores de referência mantida no banco (não
deixar o modelo "inventar" temperatura/velocidade sem grounding). Custo por chamada deve ser
monitorado; usar o modelo mais econômico disponível para essa tarefa.

### 6.7 Monetização
Stripe Checkout + webhook para atualizar `subscriptions` e `profiles.plan`. Ao mudar de plano,
os limites em `usage_counters` devem refletir o novo plano no próximo ciclo mensal.

## 7. Convenções de código

- **TypeScript:** modo `strict` ativado. Sem `any` — usar tipos explícitos ou `unknown` com
  narrowing. ESLint + Prettier configurados desde o primeiro commit.
- **Python:** type hints obrigatórios em todas as funções públicas. Formatação com `ruff`.
  Contratos de API definidos com Pydantic models (espelhar em `packages/shared-types` sempre
  que possível para manter frontend e backend sincronizados).
- **Commits:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).
- **Testes:** Vitest para lógica de frontend, pytest para o backend Python. A lógica de corte e
  capping (seção 6.4) é a parte mais sensível do sistema — priorizar cobertura de testes ali
  antes de qualquer outra área.
- **Nomenclatura:** código e nomes de variáveis/funções em inglês; textos visíveis ao usuário
  (UI, mensagens de erro) em português do Brasil.

## 8. Variáveis de ambiente

```
# Supabase
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=        # apenas no backend, nunca expor ao cliente

# Backend Python
PYTHON_BACKEND_URL=               # ex: https://seu-servico.onrender.com
PYTHON_BACKEND_INTERNAL_TOKEN=    # autenticação simples entre Next.js e o backend

# IA (fase 2)
MESHY_API_KEY=
ANTHROPIC_API_KEY=

# Pagamentos
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=

NEXT_PUBLIC_APP_URL=
```

## 9. Segurança e privacidade (LGPD)

- Todo acesso a arquivos no Supabase Storage via URL assinada com expiração curta — nunca
  bucket público.
- RLS habilitado em 100% das tabelas descritas na seção 5.
- Implementar endpoint/fluxo de exclusão de conta que remove os arquivos do usuário do Storage,
  não apenas as linhas do banco.
- Não logar conteúdo de arquivos de usuário em logs de aplicação (nomes de arquivo e IDs, sim;
  conteúdo do modelo 3D, não).
- Termos de uso devem deixar claro quem é dono dos arquivos enviados e dos modelos gerados por
  IA (a licença da Meshy no plano grátis deles é CC BY 4.0 — isso se propaga para o que
  oferecemos no nosso próprio plano grátis, se usarmos a Meshy nesse tier).

## 10. Definição de pronto (Definition of Done) por funcionalidade

Uma funcionalidade só é considerada concluída quando:
1. Funciona ponta a ponta (frontend → API → backend/banco → resposta ao usuário).
2. Tem testes automatizados cobrindo o caminho feliz e pelo menos um caso de erro.
3. Respeita os limites de infraestrutura da seção 3 (nada pesado rodando em Vercel Function).
4. Não quebra RLS nem expõe dados de um usuário a outro.
5. Foi validada manualmente com um arquivo STL real (não só com mocks).
