# Mapa Completo da Stack Tecnológica e Arquitetura do Projeto

> **Documento de Referência Técnica**  
> **Projeto:** Plataforma de Preparação, Divisão por Cores e Fatiamento 3D para Impressão FDM (`projeto-impressao-3d`)  
> **Data de Atualização:** Outubro de 2026

---

## 1. Visão Geral da Arquitetura

O sistema adota uma arquitetura desacoplada em microsserviços / monorepo, dividida entre:
1. **Frontend Web & Orquestração BFF:** Interface do usuário reativa e visualizador 3D em tempo real.
2. **Backend de Geometria Computacional (`mesh-service`):** Processamento pesado assíncrono de corte booleano, fechamento de cascas, conectores mecânicos e análise volumétrica de malhas 3D.
3. **Persistência & Nuvem (BaaS & Cloud):** Autenticação, banco relacional, armazenamento S3-compatível, hosting e monitoramento.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js 16 / React 19)                │
│  - Three.js + React Three Fiber / Drei (Viewport 3D WebGL)             │
│  - Tailwind CSS + UI Customizada                                       │
│  - Next.js Route Handlers (BFF / Proxy com Mesh Service)               │
└───────────────────▲───────────────────────────────▲────────────────────┘
                    │ REST API / Polling            │ Supabase Client SDK
                    ▼                               ▼
┌──────────────────────────────────────┐  ┌──────────────────────────────┐
│  GEOMETRY BACKEND (mesh-service)     │  │   PERSISTÊNCIA & AUTH        │
│  - Python 3.11+ / FastAPI / Uvicorn  │  │   (Supabase Cloud)           │
│  - Trimesh, Manifold3D, Shapely,     │  │   - PostgreSQL 15+           │
│    SciPy (cKDTree), Scikit-image     │  │   - Supabase Auth (Cookies)  │
│  - Polylabel, Earcut, Fast-Simp.     │  │   - Storage S3 (Bucket:      │
│  - Hospedado no Render (Web Service) │  │     'models')                │
└──────────────────────────────────────┘  └──────────────────────────────┘
```

---

## 2. Frontend (`apps/web`)

Responsável pela experiência do usuário, visualização interativa do modelo 3D fatiado nas mesas de impressão, manipulação de cores e acionamento dos fluxos de corte.

| Tecnologia / Pacote | Versão | Função no Projeto |
|---|---|---|
| **Next.js** | `16.3.3` (App Router) | Framework fullstack React, SSR, roteamento e API Route Handlers (BFF). |
| **React** | `19.0.0` | Biblioteca de UI central (renderização baseada em componentes). |
| **React DOM** | `19.0.0` | Acoplamento do React ao DOM do navegador. |
| **Three.js** | `^0.185.1` | Motor gráfico 3D via WebGL para renderização de malhas, iluminação, sombras e mesas de impressão virtuais. |
| **@react-three/fiber** | `^9.7.0` | Reconciliador declarativo React para o Three.js (gerencia a cena 3D dentro do ciclo de vida React). |
| **@react-three/drei** | `^10.7.8` | Componentes utilitários para 3D (controles de câmera `OrbitControls`, iluminação ambiental, grids de mesa, helpers visuais). |
| **Tailwind CSS** | `^3.4.17` | Framework de estilização utilitária moderna para interfaces responsivas, painéis flutuantes e tema dark. |
| **@tailwindcss/typography** | `^0.5.15` | Estilização padronizada para blocos de texto e documentações embutidas. |
| **PostCSS** / **Autoprefixer** | `^8.5.1` / `^10.4.20` | Pipeline de compilação, otimização e vendor prefixes para CSS. |
| **TypeScript** | `^5.x` | Tipagem estática em 100% da aplicação para segurança no tráfego de dados e objetos geométricos. |
| **@supabase/ssr** | `^0.5.2` | Gerenciamento seguro de autenticação e cookies em aplicações Next.js Server Components e Client Components. |
| **@supabase/supabase-js** | `^2.46.2` | SDK cliente do Supabase para upload direto de arquivos 3D e comunicação com o banco de dados. |
| **ESLint** + **Prettier** | `^9.x` / `^3.4.2` | Padronização e formatação de código no padrão Clean Code. |

---

## 3. Backend de Geometria Computacional (`apps/mesh-service`)

Serviço de alta performance em Python focado em matemática vetorial, algoritmos de grafos 3D, operações booleanas sólidas e empacotamento em placas.

### 3.1 Framework Web & Infraestrutura de Rede
| Tecnologia | Versão | Função |
|---|---|---|
| **Python** | `3.11+` | Linguagem base para processamento científico e geométrico. |
| **FastAPI** | `>=0.115.0` | Framework web assíncrono de alta performance para criação das APIs REST (`/color-split`, `/analyze`, etc.). |
| **Uvicorn** | `>=0.32.0` | Servidor ASGI rápido para rodar a aplicação FastAPI. |
| **Pydantic** | `>=2.10.0` | Validação estrita de contratos de entrada/saída de dados geométricos e configurações. |
| **pydantic-settings** | `>=2.7.0` | Gestão tipada de variáveis de ambiente do sistema. |
| **HTTPX** | `>=0.28.0` | Cliente HTTP assíncrono para download e upload de malhas sem bloquear a thread principal. |
| **Colorlog** | `>=6.0.0` | Logs formatados e coloridos no terminal para diagnóstico de processamento. |

### 3.2 Motores de Malha, Geometria e Operações Booleanas
| Biblioteca | Versão | Papel Exato no Fatiamento / Corte |
|---|---|---|
| **Trimesh** | `>=4.4.0` | Núcleo de carregamento, exportação, análise de fechamento (*watertight*), transformações rígidas de matrizes 4x4 e cortes planos bisseccionais. |
| **Manifold3D** | `>=2.5.0` | Motor booleano CSG de última geração (desenvolvido pela elalish/manifold). Realiza união, subtração e cortes 100% garantidos contra auto-interseções (*manifold guarantees*). |
| **Shapely** | `>=2.0.0` | Geometria computacional 2D planar baseada em GEOS. Utilizado para encontrar o contorno das seções de corte e calcular polígonos de encaixe. |
| **shapely.ops.polylabel** | Embutido | Algoritmo do *Polo de Inacessibilidade* (círculo máximo inscrito). Encontra com perfeição o ponto mais espesso de uma peça para posicionar os pinos de encaixe sem furar as paredes externas. |
| **SciPy (`scipy.spatial.cKDTree`)** | `>=1.11.0` | Estrutura de árvore espacial k-d para agrupamento por proximidade euclidiana de ilhas desconectadas flutuantes (`gap_mm`). Elimina pedaços soltos pós-corte. |
| **NumPy** | `>=1.26.0` | Operações matriciais ultra-rápidas sobre matrizes de vértices `(N, 3)` e triângulos `(M, 3)`. |
| **NetworkX** | `>=3.0` | Análise de grafos topológicos de arestas e faces para identificação de componentes conexos nas malhas. |
| **mapbox_earcut** | `>=1.0.2` | Algoritmo Earcut para triangulação de tampas de corte planares e fechamento de polígonos complexos com ilhas/furos. |
| **fast_simplification** | `>=0.1.7` | Simplificação e decimação de malhas ultra-densas preservando a forma e bordas críticas. |
| **Skeletor** | `>=1.7.0` | Extração de esqueletos topológicos (curvatura e contração laplaciana) para identificação anatômica estrutural. |
| **Scikit-image** | `>=0.22.0` | Processamento de volumes voxelizados (Marching Cubes) para geração de malhas sólidas a partir de nuvens volumétricas. |
| **Rtree** | `>=1.2.0` | Indexação espacial R-Tree para consultas de colisão e interseção acelerada por hardware de bounding boxes. |
| **LXML** | `>=5.0.0` | Parser e gerador XML ultra-rápido para manipular o arquivo estrutural `[Content_Types].xml` e `3D/3dmodel.model` do formato 3MF. |
| **Pillow (PIL)** | `>=10.0.0` | Processamento de texturas, mapas de cores e prévias bidimensionais. |
| **xxhash** | `>=3.0.0` | Geração de hashes de integridade rápidos para evitar reprocessamento de malhas idênticas (caching). |

---

## 4. Banco de Dados, Armazenamento e BaaS (Supabase)

Utilizado como espinha dorsal de dados persistentes do ecossistema:

| Recurso Supabase | Função no Sistema |
|---|---|
| **Supabase Auth** | Autenticação de usuários via JWT em cookies HTTPOnly compatíveis com Next.js SSR. |
| **PostgreSQL 15+** | Banco de dados relacional que registra: dados cadastrais, sessões de corte (`split_sessions`), metadados dos modelos enviados, limites de mesa das impressoras e status de fatiamento. |
| **Supabase Storage** | Bucket S3-compatível (`models`) para armazenamento persistente dos arquivos 3MF e STL brutos, das partes fatiadas e dos zips finais para download. |
| **Storage Signed URLs** | URLs com tempo de expiração temporário geradas com segurança para transferência entre o frontend e o backend sem expor credenciais mestras. |

---

## 5. Infraestrutura, Hospedagem e Ferramentas Externas

Toda a arquitetura opera em ambiente serverless/cloud sob demanda:

| Serviço / Provedor | Tipo de Serviço | Função / Configuração |
|---|---|---|
| **Render.com** | Cloud PaaS (Web Services) | Hospeda o backend Python `mesh-service` (`impressao-3d-mesh`) com containerização Docker, alocação de 1 vCPU e 2 GB RAM (instância Standard), exposto via HTTPS. |
| **Render API (`/v1/services`)** | Automação Cloud | Usada pelo script `render-service.ps1` para suspender (`suspend`) e ligar (`resume`) a máquina sob demanda, reduzindo custos durante desenvolvimento. |
| **Vercel** *(ou Render Frontend)* | Cloud Edge Platform | Hospedagem de alta velocidade para a aplicação Next.js / React, com CDN global e renderização estática/incremental. |
| **GitHub** | Repositório Git & CI/CD | Versionamento do código-fonte monorepo e automação de deploys com gatilho contínuo no push da branch `main`. |
| **UptimeRobot** | Monitoramento Externo | Serviço de ping e checagem periódica da URL `/health` para monitoramento de disponibilidade e alertas de queda. |

---

## 6. Fluxo de Dados e Integração dos Componentes

1. **Upload:** O usuário envia o modelo `.3mf` no navegador através da aplicação Next.js. O arquivo é gravado no **Supabase Storage**.
2. **Requisição de Corte:** O frontend dispara uma chamada REST para o **Mesh Service** no Render informando o ID do modelo e as dimensões da mesa (ex.: $100 \times 100 \times 100\text{ mm}$).
3. **Download e Análise:** O `mesh-service` autentica com o Supabase via service role, baixa a malha para um diretório temporário isolado e executa a segregação por cores (extrusores Bambu/Orca).
4. **Resolução de Encaixe e Bisseção:**
   - O algoritmo testa a rotação $360^\circ$ no plano $Z$ (aproveitamento da diagonal).
   - Se a peça exceder a mesa, o algoritmo anatômico isola extremidades (asas, cauda, membros) ou aplica bisseção ortogonal em planos de menor área.
   - Aplica-se o **Shapely Polylabel** para perfurar fêmeas e extrudar pinos machos com tolerância de folga mecânica ($0{,}2\text{ mm}$).
   - O **SciPy cKDTree** agrupa vértices e limpa quaisquer estilhaços flutuantes desconectados.
5. **Armazenamento e Retorno:** As peças fatiadas são reempacotadas num arquivo unificado `.3mf` com matrizes de cor preservadas, submetidas de volta ao **Supabase Storage**, e o frontend recebe as URLs assinadas para renderização visual imediata no **Three.js**.
