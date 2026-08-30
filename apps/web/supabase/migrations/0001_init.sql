-- =============================================================================
-- 0001_init.sql — Schema inicial da plataforma de Impressão 3D
-- =============================================================================
-- Executar via: supabase db push  OU  supabase migration up
-- Requer: extensão pgcrypto (habilitada por padrão no Supabase)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- TABELAS
-- ---------------------------------------------------------------------------

-- Perfil público do usuário (auth.users já existe via Supabase Auth)
create table public.profiles (
  id             uuid        primary key references auth.users(id) on delete cascade,
  display_name   text,
  plan           text        not null default 'free'
                             check (plan in ('free', 'pro')),
  created_at     timestamptz not null default now()
);

comment on table public.profiles is
  'Perfil público do usuário. Criado automaticamente via trigger ao cadastrar conta.';

-- Mesas de trabalho cadastradas pelo usuário
-- O usuário define diretamente as dimensões — sem catálogo de modelos de impressora.
create table public.build_plates (
  id                   uuid        primary key default gen_random_uuid(),
  user_id              uuid        not null references auth.users(id) on delete cascade,
  name                 text        not null,
  build_volume_x_mm    numeric     not null check (build_volume_x_mm > 0),
  build_volume_y_mm    numeric     not null check (build_volume_y_mm > 0),
  build_volume_z_mm    numeric     not null check (build_volume_z_mm > 0),
  nozzle_diameter_mm   numeric     check (nozzle_diameter_mm > 0),
  is_default           boolean     not null default false,
  created_at           timestamptz not null default now()
);

comment on table public.build_plates is
  'Mesas de trabalho do usuário. As dimensões são definidas manualmente pelo próprio usuário.';

-- Modelos 3D (enviados pelo usuário ou gerados via IA na Fase 2)
create table public.models (
  id                    uuid        primary key default gen_random_uuid(),
  user_id               uuid        not null references auth.users(id) on delete cascade,
  name                  text        not null,
  original_filename     text,
  storage_path          text        not null,
  format                text        not null
                                    check (format in ('stl', '3mf', 'obj', 'gltf')),
  source                text        not null default 'upload'
                                    check (source in ('upload', 'ai_generated')),
  bounding_box_x_mm     numeric,
  bounding_box_y_mm     numeric,
  bounding_box_z_mm     numeric,
  printability_status   text        default 'pending'
                                    check (printability_status in ('pending', 'ok', 'warning', 'error')),
  printability_report   jsonb,
  created_at            timestamptz not null default now()
);

comment on table public.models is
  'Modelos 3D do usuário. storage_path aponta para um arquivo no Supabase Storage (bucket privado).';

-- Sessão de divisão de um modelo
create table public.split_sessions (
  id              uuid        primary key default gen_random_uuid(),
  model_id        uuid        not null references public.models(id) on delete cascade,
  user_id         uuid        not null references auth.users(id) on delete cascade,
  build_plate_id  uuid        not null references public.build_plates(id),
  status          text        not null default 'draft'
                              check (status in ('draft', 'processing', 'completed', 'failed')),
  -- Array de planos de corte: [{ "position": [x,y,z], "normal": [x,y,z] }, ...]
  cut_planes      jsonb       not null default '[]',
  has_connectors  boolean     not null default false,
  error_message   text,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

comment on table public.split_sessions is
  'Sessão de divisão de um modelo. cut_planes guarda os planos de corte confirmados pelo usuário.';

-- Peças resultantes de uma divisão
create table public.pieces (
  id                  uuid        primary key default gen_random_uuid(),
  split_session_id    uuid        not null references public.split_sessions(id) on delete cascade,
  piece_index         int         not null check (piece_index >= 0),
  storage_path        text        not null,
  bounding_box_x_mm   numeric,
  bounding_box_y_mm   numeric,
  bounding_box_z_mm   numeric,
  fits_build_plate    boolean     not null,
  created_at          timestamptz not null default now()
);

comment on table public.pieces is
  'Peças geradas por uma split_session. Cada peça é um arquivo STL/3MF separado no Storage.';

-- Assinatura via Stripe
create table public.subscriptions (
  id                      uuid        primary key default gen_random_uuid(),
  user_id                 uuid        not null references auth.users(id) on delete cascade,
  stripe_customer_id      text,
  stripe_subscription_id  text,
  plan                    text        not null default 'free'
                                      check (plan in ('free', 'pro')),
  status                  text        not null default 'active'
                                      check (status in ('active', 'canceled', 'past_due', 'trialing')),
  current_period_end      timestamptz
);

comment on table public.subscriptions is
  'Assinatura Stripe do usuário. Atualizada via webhook do Stripe.';

-- Contador de uso mensal (para limitar o plano grátis)
create table public.usage_counters (
  id                    uuid  primary key default gen_random_uuid(),
  user_id               uuid  not null references auth.users(id) on delete cascade,
  month                 date  not null, -- primeiro dia do mês, ex: 2026-08-01
  ai_generations_used   int   not null default 0 check (ai_generations_used >= 0),
  splits_used           int   not null default 0 check (splits_used >= 0),
  connectors_used       int   not null default 0 check (connectors_used >= 0),
  unique (user_id, month)
);

comment on table public.usage_counters is
  'Contador mensal de uso por usuário. month = primeiro dia do mês (ex: 2026-08-01).';

-- ---------------------------------------------------------------------------
-- ÍNDICES
-- ---------------------------------------------------------------------------

create index idx_build_plates_user_id    on public.build_plates(user_id);
create index idx_models_user_id          on public.models(user_id);
create index idx_split_sessions_user_id  on public.split_sessions(user_id);
create index idx_split_sessions_model_id on public.split_sessions(model_id);
create index idx_pieces_split_session_id on public.pieces(split_session_id);
create index idx_subscriptions_user_id   on public.subscriptions(user_id);
create index idx_usage_counters_user_id  on public.usage_counters(user_id);

-- ---------------------------------------------------------------------------
-- TRIGGER: criar profiles automaticamente ao criar conta
-- (seção 6.1 do AGENTS.md — "Ao criar conta, criar automaticamente uma linha
-- em profiles com plan = 'free'")
-- ---------------------------------------------------------------------------

create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, display_name, plan)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'display_name', new.email),
    'free'
  );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------------
-- ROW LEVEL SECURITY (RLS)
-- Regra geral: cada usuário só acessa suas próprias linhas (auth.uid() = user_id)
-- ---------------------------------------------------------------------------

-- profiles
alter table public.profiles enable row level security;

create policy "profiles: usuário vê o próprio perfil"
  on public.profiles for select
  using (auth.uid() = id);

create policy "profiles: usuário atualiza o próprio perfil"
  on public.profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- Profiles são criados via trigger (service_role), não pelo usuário diretamente.
-- Não há política de INSERT/DELETE para o usuário final aqui.

-- build_plates
alter table public.build_plates enable row level security;

create policy "build_plates: select próprio"
  on public.build_plates for select
  using (auth.uid() = user_id);

create policy "build_plates: insert próprio"
  on public.build_plates for insert
  with check (auth.uid() = user_id);

create policy "build_plates: update próprio"
  on public.build_plates for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "build_plates: delete próprio"
  on public.build_plates for delete
  using (auth.uid() = user_id);

-- models
alter table public.models enable row level security;

create policy "models: select próprio"
  on public.models for select
  using (auth.uid() = user_id);

create policy "models: insert próprio"
  on public.models for insert
  with check (auth.uid() = user_id);

create policy "models: update próprio"
  on public.models for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "models: delete próprio"
  on public.models for delete
  using (auth.uid() = user_id);

-- split_sessions
alter table public.split_sessions enable row level security;

create policy "split_sessions: select próprio"
  on public.split_sessions for select
  using (auth.uid() = user_id);

create policy "split_sessions: insert próprio"
  on public.split_sessions for insert
  with check (auth.uid() = user_id);

create policy "split_sessions: update próprio"
  on public.split_sessions for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "split_sessions: delete próprio"
  on public.split_sessions for delete
  using (auth.uid() = user_id);

-- pieces
-- Usuário acessa peças se for dono da split_session correspondente
alter table public.pieces enable row level security;

create policy "pieces: select se dono da sessão"
  on public.pieces for select
  using (
    exists (
      select 1 from public.split_sessions ss
      where ss.id = pieces.split_session_id
        and ss.user_id = auth.uid()
    )
  );

-- INSERT/DELETE em pieces é feito pelo backend (service_role) — sem política para usuário final.

-- subscriptions
-- Leitura pelo usuário; escrita apenas via service_role (webhook Stripe)
alter table public.subscriptions enable row level security;

create policy "subscriptions: select próprio"
  on public.subscriptions for select
  using (auth.uid() = user_id);

-- usage_counters
alter table public.usage_counters enable row level security;

create policy "usage_counters: select próprio"
  on public.usage_counters for select
  using (auth.uid() = user_id);

-- Incremento de contadores é feito pelo backend (service_role) — sem política de INSERT/UPDATE para usuário.
