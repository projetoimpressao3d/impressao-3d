# Roteiro de desenvolvimento — Plataforma de renderização e divisão de projetos 3D

> Este arquivo é o script de execução do projeto. Use-o junto com `AGENTS.md` (que o
> Antigravity carrega automaticamente como regras persistentes). Siga as fases em ordem — cada
> uma depende da anterior. Os blocos "Prompt sugerido" são textos prontos para colar no agente.

## Antes de começar

1. Crie a pasta do projeto e inicialize o repositório:
```bash
mkdir projeto-impressao-3d && cd projeto-impressao-3d
git init
```
   > ⚠️ Evite espaços e acentos no nome da pasta do projeto. Além do terminal (CMD/PowerShell)
   > interpretar espaços como separadores de argumento, ferramentas como Git, Docker e os
   > deploys da Vercel/Render também podem se comportar mal com caminhos assim. `projeto-impressao-3d`
   > já segue esse padrão.
2. Coloque `AGENTS.md` e este `ROTEIRO_DE_DESENVOLVIMENTO.md` na raiz da pasta antes de abrir
   o Antigravity — assim ele já carrega o contexto completo desde a primeira tarefa.
3. Crie as contas necessárias (pode fazer em paralelo às primeiras fases):
   - GitHub (repositório privado)
   - Vercel (conectado ao GitHub)
   - Supabase (novo projeto)
   - Render (para o backend Python)
4. Abra a pasta no Antigravity como um projeto (ele pode trabalhar com múltiplas pastas —
   `/apps/web` e `/apps/mesh-service` — dentro do mesmo projeto).

---

## Fase 1 — Fundação e setup (≈1-2 semanas)

**Objetivo:** repositório funcional, projeto Next.js rodando localmente, Supabase conectado,
schema do banco criado.

**Prompt sugerido:**
```
Leia o AGENTS.md deste projeto. Nesta primeira fase, quero que você:
1. Crie a estrutura de pastas /apps/web (Next.js + TypeScript + Tailwind, App Router) e
   /apps/mesh-service (FastAPI, com um endpoint de health check em /health).
2. Configure ESLint + Prettier no /apps/web e ruff no /apps/mesh-service.
3. Crie o arquivo .env.example na raiz com todas as variáveis listadas na seção 8 do
   AGENTS.md, sem valores reais.
4. Gere o SQL de todas as tabelas da seção 5 do AGENTS.md em
   /apps/web/supabase/migrations/0001_init.sql, incluindo as políticas de RLS básicas
   (cada usuário só acessa suas próprias linhas, usando auth.uid()).
5. Crie um README.md na raiz explicando como rodar o projeto localmente.
Não implemente nenhuma funcionalidade de produto ainda — só a fundação.
```

**Checklist de saída da fase:**
- [X] `npm run dev` sobe o frontend localmente
- [X] `uvicorn` sobe o backend Python localmente com `/health` respondendo
- [X] Migração SQL aplicada no projeto Supabase (rodar via Supabase CLI ou dashboard)
- [X] Repositório no GitHub, primeiro push feito
- [ ] Projeto conectado na Vercel (deploy automático do `/apps/web`)

---

## Fase 2 — Autenticação e upload (≈2 semanas)

**Prompt sugerido:**
```
Leia o AGENTS.md. Agora implemente:
1. Autenticação com Supabase Auth (cadastro, login, logout) no /apps/web, com criação
   automática da linha em `profiles` (plan='free') ao registrar.
2. Middleware do Next.js protegendo as rotas autenticadas.
3. Tela de upload de arquivos STL/3MF (bucket privado no Supabase Storage, URL assinada),
   respeitando o limite de 50MB da seção 6.2 do AGENTS.md.
4. Tela de listagem dos modelos do usuário (tabela `models`).
5. Endpoint no mesh-service que recebe a URL do arquivo recém-enviado, calcula a bounding box
   e roda a checagem de printability com trimesh (seção 6.2), atualizando `models` com o
   resultado.
Siga as convenções de código da seção 7 do AGENTS.md.
```

**Checklist de saída da fase:**
- [X] Cadastro/login funcionando de ponta a ponta
- [X] Upload salva o arquivo no Storage e cria a linha em `models`
- [X] Bounding box e status de printability aparecem na tela após o upload
- [ ] RLS testado (um usuário não consegue ver modelo de outro usuário)

---

## Fase 3 — Visualizador 3D (≈2 semanas)

**Prompt sugerido:**
```
Leia o AGENTS.md. Implemente o visualizador 3D descrito na seção 6.2:
- Componente React com @react-three/fiber + drei carregando STL e 3MF.
- Controles de câmera (rotação, zoom, pan).
- Overlay mostrando as dimensões do modelo (bounding box) e comparando visualmente com as
  dimensões de uma mesa de trabalho, quando uma estiver selecionada.
Também implemente o CRUD de build_plates (seção 6.3) — o usuário define as dimensões da mesa
de trabalho manualmente (largura, profundidade, altura em mm) e dá um apelido a ela. Não
implemente nenhuma lista de modelos comerciais de impressora pré-cadastrada.
```

**Checklist de saída da fase:**
- [X] STL e 3MF renderizam corretamente no navegador
- [X] Usuário consegue cadastrar/editar/excluir mesas de trabalho com dimensões próprias
- [X] Comparação visual entre modelo e mesa de trabalho aparece na tela

---

## Fase 4 — Backend de análise geométrica (≈3 semanas)

**Objetivo:** consolidar a análise de printability e preparar o terreno para o divisor de
peças (fase 6), que é a funcionalidade central do produto.

**Prompt sugerido:**
```
Leia a seção 6.4 do AGENTS.md com atenção — é a funcionalidade central do produto.
Nesta fase, implemente no mesh-service:
1. Endpoint POST /split-sessions que recebe model_id + build_plate_id, compara a
   bounding box do modelo com as dimensões da mesa de trabalho, e retorna se cabe ou não, e se não
   couber, quantos cortes mínimos são necessários por eixo (heurística simples, conforme
   passo 3 da seção 6.4 — não é IA).
2. Passo de reparo prévio da malha com trimesh (fechar buracos, corrigir normais) reutilizável
   também pela checagem de printability da fase 2.
3. Testes cobrindo: modelo que já cabe, modelo que precisa de 1 corte, modelo que precisa de
   múltiplos cortes em mais de um eixo.
Ainda não implemente o corte em si (isso é a fase 6) — só o cálculo e a sugestão.
```

**Checklist de saída da fase:**
- [ ] Endpoint retorna corretamente se o modelo cabe ou não
- [ ] Sugestão de número de cortes por eixo está correta em testes automatizados
- [ ] Passo de reparo de malha funciona em arquivos STL reais "sujos" (com furos/erros)

---

## Fase 5 — Integração de IA generativa básica (≈2 semanas)

**Prompt sugerido:**
```
Leia as seções 6.5 e 6.6 do AGENTS.md. Implemente:
1. Endpoint que chama a API da Meshy (text-to-3D) para gerar um modelo a partir de um prompt
   de texto, baixa o resultado e salva no nosso Storage/tabela `models` (source='ai_generated')
   antes que expire na Meshy.
2. Endpoint que chama a API da Claude para sugerir configuração de impressão (material +
   mesa de trabalho → temperatura, velocidade, suporte), usando uma tabela de valores de
   referência no banco como grounding — não deixe o modelo inventar números sem essa base.
3. Registre o uso em `usage_counters` para permitir limitar isso no plano grátis depois.
```

**Checklist de saída da fase:**
- [ ] Geração via texto funciona e o resultado fica salvo no nosso Storage
- [ ] Sugestão de configuração de impressão retorna valores plausíveis e consistentes com a
      tabela de referência

---

## Fase 6 — Divisor de peças interativo (≈3 semanas) — FUNCIONALIDADE CENTRAL

**Prompt sugerido:**
```
Leia a seção 6.4 do AGENTS.md do início ao fim antes de começar — esta é a funcionalidade
mais importante do produto. Implemente:

Frontend (/apps/web):
1. No visualizador 3D, permita ao usuário adicionar um ou mais planos de corte sobre o modelo,
   usando TransformControls do drei para posicionar/rotacionar cada plano.
2. Use THREE.Plane + material.clippingPlanes para o preview em tempo real (não recompute
   geometria a cada movimento).
3. A cada movimento do plano, calcule localmente a bounding box de cada pedaço resultante e
   mostre visualmente (cor verde/vermelha) se cada pedaço cabe na mesa de trabalho
   selecionada.
4. Ao confirmar, envie os planos definitivos para o backend.

Backend (/apps/mesh-service):
5. Endpoint POST /split-sessions/{id}/execute que recebe os planos de corte confirmados e
   executa o fluxo completo da seção 6.4: reparo prévio, corte booleano com manifold3d
   (um plano por vez), capping de cada face aberta, validação de manifold + validação de que
   cabe no volume informado, e salvamento de cada peça como STL/3MF no Storage com a
   respectiva linha em `pieces`.
6. Implemente o limite do plano grátis usando usage_counters.splits_used (a definir o valor
   exato de N comigo antes de travar o número no código).

Não implemente ainda a geração de encaixes (isso é a fase 7). Gere só cortes planos limpos
por enquanto.
```

**Checklist de saída da fase:**
- [ ] Usuário consegue posicionar e ajustar planos de corte interativamente
- [ ] Preview em tempo real mostra corretamente se cada pedaço cabe ou não
- [ ] Corte real gera peças watertight e manifold (testar com pelo menos 3 modelos STL reais
      de complexidades diferentes)
- [ ] Download das peças funciona (arquivo por peça e/ou 3MF único com múltiplos objetos)
- [ ] Limite do plano grátis é respeitado

---

## Fase 7 — Encaixes automáticos + monetização + beta (≈3-4 semanas)

**Prompt sugerido:**
```
Leia a seção 6.4 (regra de negócio) e 6.7 do AGENTS.md. Implemente:
1. Geração automática de encaixes (pino + furo) nas faces de corte, como recurso do plano
   pago, seguindo a tabela de tolerâncias por material descrita no AGENTS.md (crie essa
   tabela em um arquivo de configuração separado, não hardcoded na lógica de corte).
2. Integração com Stripe Checkout + webhook, atualizando `subscriptions` e `profiles.plan`.
3. Bloqueio de funcionalidades pagas (encaixes, limite maior de divisões/mês, geração via IA
   sem limite) para usuários no plano grátis.
4. Antes de finalizar esta fase, me avise para migrarmos Vercel e Supabase para os planos
   pagos, já que a partir daqui o uso passa a ser comercial (seção 3 do AGENTS.md).
```

**Checklist de saída da fase:**
- [ ] Encaixes gerados se alinham corretamente entre as peças (testar imprimindo ao menos uma
      vez, se possível)
- [ ] Fluxo de pagamento completo (checkout → webhook → liberação do plano) funciona
- [ ] Limites por plano aplicados corretamente em todos os endpoints relevantes
- [ ] Migração Vercel/Supabase para planos pagos feita antes de abrir para usuários reais
- [ ] Grupo beta convidado

---

## Depois do lançamento beta

- Monitorar custo real de API (Meshy + Claude) vs. estimativa do planejamento estratégico.
- Coletar feedback do grupo beta especificamente sobre o divisor de peças (fluxo mais
  importante do produto) antes de investir em novas funcionalidades.
- Reavaliar se vale a pena implementar cortes "inteligentes" (seguindo contornos naturais do
  objeto) como evolução do plano pago, com base no uso real do corte manual assistido.
