-- =============================================================================
-- 0002_storage.sql — Bucket privado para modelos 3D + políticas RLS do Storage
-- =============================================================================
-- Execute no SQL Editor do Supabase antes do primeiro upload.
-- =============================================================================

-- Criar bucket privado (public = false → URLs assinadas obrigatórias)
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'models',
  'models',
  false,
  52428800,  -- 50 MB em bytes
  array['model/stl', 'application/sla', 'application/vnd.ms-pki.stl',
        'application/octet-stream', 'model/3mf', 'application/vnd.ms-package.3dmanufacturing-3dmodel+xml']
)
on conflict (id) do nothing;

-- RLS do Storage: usuário autenticado só acessa objetos no path {user_id}/**
create policy "models storage: insert próprio"
  on storage.objects for insert to authenticated
  with check (
    bucket_id = 'models'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "models storage: select próprio"
  on storage.objects for select to authenticated
  using (
    bucket_id = 'models'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "models storage: delete próprio"
  on storage.objects for delete to authenticated
  using (
    bucket_id = 'models'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
