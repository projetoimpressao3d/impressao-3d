-- =============================================================================
-- 0003_drop_usage_counters.sql
-- Remove a tabela usage_counters — o modelo de cobrança mudou de
-- "por uso (splits/mês)" para "por assinatura ativa" (subscriptions.status = 'active').
-- Não há mais contadores mensais de uso. O acesso às funcionalidades é binário:
-- assinante ativo = acesso completo; sem assinatura = acesso às funcionalidades gratuitas.
-- Referência: seção 6.4 e 6.7 do AGENTS.md (atualizado em 2026-08-30).
-- =============================================================================

-- Remover políticas RLS antes de dropar a tabela
drop policy if exists "usage_counters: select próprio" on public.usage_counters;

-- Remover índice
drop index if exists public.idx_usage_counters_user_id;

-- Remover tabela (cascade remove constraints automaticamente)
drop table if exists public.usage_counters;
