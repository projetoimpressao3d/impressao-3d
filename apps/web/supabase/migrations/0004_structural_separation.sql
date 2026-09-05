-- =============================================================================
-- 0004_structural_separation.sql
-- Adiciona colunas para funcionalidade "Separar Peças" (seção 6.4.1 do AGENTS.md)
-- =============================================================================
-- Aplicar via: Supabase Dashboard → SQL Editor → Cole e execute este script.
-- =============================================================================

-- Sensibilidade usada no último processamento estrutural (null se nunca rodada)
-- Valor entre 0.0 e 1.0 (ex: 0.07 = 7%)
alter table public.split_sessions
  add column if not exists structural_sensitivity numeric
    check (structural_sensitivity is null or (structural_sensitivity >= 0 and structural_sensitivity <= 1));

-- Grupo estrutural da peça: rótulo interno do apêndice de origem.
-- Ex: "branch-0", "branch-1", "trunk". Null para cortes não-estruturais.
alter table public.pieces
  add column if not exists structural_group text;

comment on column public.split_sessions.structural_sensitivity is
  'Limiar mínimo de volume (fração do total) para apêndice virar peça separável. Seção 6.4.1.';

comment on column public.pieces.structural_group is
  'Rótulo interno do apêndice estrutural de origem (ex: branch-0, trunk). Seção 6.4.1.';
