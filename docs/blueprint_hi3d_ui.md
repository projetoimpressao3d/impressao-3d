# 📋 Prompt / Blueprint para o Agente Antigravity

**Objetivo:** Construir a interface de uma aplicação SaaS focada em IA/3D baseada no layout do Hi3D.
**Stack Tecnológica:** Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS.
**Abordagem de Componentização:** O layout deve usar CSS Grid e Flexbox para garantir que a tela ocupe 100% da altura (`h-screen`) e largura (`w-screen`), sem rolagem global (apenas rolagem interna nos painéis laterais). Use `lucide-react` para os ícones.

## 1. Paleta de Cores e Tipografia (Tailwind)

O tema é um **Dark Mode** sofisticado, focado em tons neutros quase pretos para destacar o conteúdo 3D central. Configure o `tailwind.config.ts` ou use as classes utilitárias baseadas em `zinc` ou `neutral`:

*   **Fundo Principal (Sidebar e Topbar):** `bg-zinc-950`
*   **Fundo Secundário (Painel de Propriedades):** `bg-zinc-900`
*   **Fundo do Canvas (Centro):** Um gradiente radial escuro para simular profundidade: `bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-zinc-800 to-zinc-950`.
*   **Textos:** Primário em `text-zinc-200`, secundário/desabilitado em `text-zinc-400` ou `text-zinc-500`.
*   **Bordas e Divisores:** Bordas muito sutis em `border-zinc-800`.
*   **Cores de Destaque (Acentos):**
    *   **Verde/Esmeralda (Estado Ativo e Botão de Ação):** `text-emerald-500`, `bg-emerald-600/20` (fundo translúcido), `border-emerald-500/50`.
    *   **Amarelo/Âmbar (Botões de Assinatura/Premium):** `bg-amber-500 text-black`, selos `bg-amber-500/20 text-amber-500`.
    *   **Azul (Selos "New"):** `bg-blue-600 text-white`.
*   **Tipografia:** Utilize a fonte **Inter** (padrão do Next.js) com pesos variando entre `font-normal` para menus, `font-medium` para botões e `font-semibold` para títulos.

## 2. Layout Estrutural Global

A tela é dividida em **três colunas principais**, além do Header superior à direita do Canvas.
A estrutura do layout principal (`app/layout.tsx` ou componente de layout de cliente) deve ser:

```tsx
<div className="flex h-screen w-full bg-zinc-950 text-zinc-200 overflow-hidden font-sans">
   {/* Sidebar Principal (Esquerda) */}
   {/* Painel de Propriedades (Meio-Esquerda) */}
   {/* Área Principal (Canvas 3D e Header) */}
</div>
```

## 3. Detalhamento dos Componentes

### A. Sidebar Principal (Esquerda - Navegação)
*   **Largura:** `w-[240px]` ou `w-64`, fixo.
*   **Borda:** `border-r border-zinc-800`.
*   **Logo:** No topo, texto simples com um ícone pontilhado.
*   **Links de Menu:** Estilo lista. `flex items-center gap-3 px-4 py-2 rounded-lg text-sm text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 transition-colors`.
*   **Estado Ativo (ex: "Imp partes"):** Quando um item está ativo, ele ganha uma borda esquerda ou altera a cor. Classe sugerida: `text-emerald-500 bg-emerald-950/30 border-l-2 border-emerald-500`.
*   **Badges nos menus:** Ao lado de "Agent", uma tag `<span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-blue-600 text-white">New</span>`.

### B. Painel de Propriedades (Coluna Central-Esquerda)
*   **Largura:** `w-[320px]`, fixo, `bg-zinc-900 border-r border-zinc-800 flex flex-col`.
*   **Tabs Superiores:** Estilo "pills" (botões arredondados). Um container `flex bg-zinc-950 p-1 rounded-lg m-4`. O tab ativo ganha `bg-zinc-800 text-white shadow`.
*   **Área de Upload (Dropzone):** 
    *   Aparência de caixa tracejada: `border-2 border-dashed border-zinc-700 rounded-xl flex flex-col items-center justify-center p-6 m-4 hover:border-zinc-500 transition-colors bg-zinc-950/50 cursor-pointer`.
    *   Ícone de caixa (box) no centro e texto "Envie o modelo aqui".
*   **Grid de Seleção (Modelos de divisão):** 
    *   Um grid responsivo para opções: `grid grid-cols-3 gap-2 px-4`.
    *   Cada item é um card vertical: `flex flex-col items-center p-2 rounded-lg border border-zinc-800 hover:bg-zinc-800 cursor-pointer`.
    *   *Estado ativo do card:* `border-emerald-500 bg-emerald-950/20`.
*   **Botão Flutuante (Bottom):** O botão "Gerar" deve ficar fixo no rodapé deste painel. `mt-auto p-4 border-t border-zinc-800`. Botão completo: `w-full bg-zinc-800 hover:bg-zinc-700 text-emerald-500 font-medium py-3 rounded-xl flex justify-center border border-zinc-700`.

### C. Header Superior (Barra de Ferramentas / Ações)
*   Localizado no topo da área do Canvas Principal: `h-14 flex items-center justify-between px-6 border-b border-zinc-800/50 w-full`.
*   **Breadcrumb/Título (Esquerda):** Ícone da ferramenta atual + texto ("Impressão em partes").
*   **Ações (Direita):** Um `flex gap-3 items-center`.
    *   Botões de ação ("Baixar Agent", "Recursos"): `px-3 py-1.5 text-xs text-zinc-300 bg-zinc-900 border border-zinc-800 rounded-lg hover:bg-zinc-800`.
    *   Créditos: `<div className="flex items-center gap-1 text-xs"><IconePresente/><span className="text-zinc-200">+ 100</span></div>`.
    *   Botão Assinar: `bg-amber-500 text-zinc-950 font-semibold px-4 py-1.5 rounded-lg text-sm hover:bg-amber-400`.
    *   Avatar do usuário: `w-8 h-8 rounded-full bg-indigo-600 text-white flex items-center justify-center`.

### D. Área Principal do Canvas (Visualizador)
*   A área que sobra: `flex-1 relative flex flex-col items-center justify-center bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-zinc-800 to-zinc-950`.
*   **Canvas 3D (Placehoder para o React 19 / Three.js):** Um div central expansível. `w-full h-full absolute inset-0 z-0`.
*   **Overlay Inferior (Exemplos):** Por cima do canvas (usando `z-10`), na parte inferior, há um texto descritivo e uma galeria.
    *   Container: `absolute bottom-8 flex flex-col items-center gap-4`.
    *   Miniaturas (Thumbnails): `flex gap-4`. Cada miniatura é um quadrado arredondado com fundo branco: `w-16 h-16 bg-white rounded-xl shadow-lg border-2 border-transparent hover:border-emerald-500 transition-transform hover:scale-105 cursor-pointer overflow-hidden`.

## 4. Detalhes de Borda, Sombras e Componentes UI (Design System)

Peça ao agente para criar os seguintes componentes reutilizáveis UI:

1.  **`Badge`**: Componentes `rounded-full text-[10px] px-2 py-0.5`. Variações de cor dependendo da props (`variant='new'`, `variant='beta'`).
2.  **`Panel`**: Containers com `bg-zinc-900 border border-zinc-800 rounded-xl`.
3.  **`IconButton`**: Botões iconizados com `p-2 rounded-lg hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200`.