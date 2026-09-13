# Benchmark e Engenharia Reversa: Split3MF.com
> **Data da analise:** Setembro de 2026
> **Referencia:** https://split3mf.com/ (Versao 3.1.0, por Taejoo Um)
> **Proposito:** Registro tecnico de arquitetura, algoritmos e funcionalidades para alimentar o desenvolvimento da nossa plataforma de preparacao e corte 3D (projeto-impressao-3d).

---

## 1. Visao Geral do Split3MF
O **Split3MF** e uma ferramenta web focada em fatiar/separar modelos 3D (especialmente arquivos 3MF pintados para AMS/Bambu Studio/OrcaSlicer/PrusaSlicer) em pecas independentes por cor com conectores automaticos.
- **Diferencial:** Permite que donos de impressoras de filamento unico (*single-extruder*) imprimam modelos multicoloridos divididos em pecas que sao coladas/encaixadas depois, evitando o desperdicio de tempo e filamento de torres de purga.
- **Processamento 100% Client-Side:** O modelo 3D nunca sobe para servidor nenhum (*"No server upload for files"*). Toda a geometria roda no navegador via Web Worker.

---

## 2. Arquitetura e Tecnologias Identificadas

| Camada | Tecnologia / Biblioteca | Funcao no Split3MF |
|---|---|---|
| **Visualizacao 3D** | Three.js (`WebGLRenderer`, `PerspectiveCamera`, `OrbitControls`, `BufferGeometry`) | Renderizacao da cena 3D, planos de corte e pecas fatiadas |
| **Motor Geometrico** | Web Worker dedicado (`assets/engine-worker-*.js`) | Execucao assincrona pesada sem travamento da UI |
| **Transporte de Dados** | Transferable Objects (`ArrayBuffer`, `Float32Array`, `Uint32Array`) | Troca de dados de malha entre thread principal e Worker com copia zero |
| **Triangulacao** | `earcut` + CDT (Constrained Delaunay Triangulation) | Triangulacao de poligonos 2D e fechamento de tampas |
| **Capping Organico** | Algoritmo *Soap Film* (Pelicula de Sabao / Superficie Minima) | Fechamento de tampas nao-planares por relaxamento laplaciano |
| **Winding / Tess** | Tessellation de multiplos contornos | Preenchimento de furos complexos e ilhas concentricas |
| **Manipulacao 3MF** | `pako` + `jszip` | Descompressao/compressao do pacote ZIP e manipulacao do XML 3MF |
| **Compatibilidade** | Namespaces Bambu Lab (`schemas.bambulab.com/package/2021`) | Preservacao de cores e metadados de filamento |
| **Autenticacao & DB** | Supabase (`tvmilayjdatmrdrmdljy.supabase.co`) | Auth (E-mail com codigo numerico, Google OAuth), RPC `increment_model_usage_count`, tabela `model_downloads` |
| **Protecao & CDN** | Cloudflare Pages + Cloudflare Turnstile | Hospedagem estatica e captcha transparente anti-bot |
| **Monetizacao** | Google AdSense + Doacoes Ko-fi | Banners laterais/inferiores e link de apoio |

---

## 3. Funcionalidades Detalhadas

### 3.1 Suavizacao e Ajuste de Borda (Smooth Boundary)
- Pincel interativo na viewport 3D para ajustar a fronteira entre pecas antes do corte:
  - **Left-click:** Puxa a area de fronteira em direcao ao cursor.
  - **Right-click:** Empurra a area de fronteira para longe.
  - **Arrastar (Drag):** Redesenha o contorno livremente.
  - **Slider de Suavidade (0-100%):** Remove o aspecto serrilhado dos triangulos.

### 3.2 Metodos de Fechamento de Corte (Capping)
1. **Soap Film:** Minimiza a area superficial (como tensao superficial de bolha de sabao), ideal para contornos organicos.
2. **CDT (Constrained Delaunay Triangulation):** Fechamento planar exato.
3. **Winding Fill (Tess):** Resolve poligonos complexos e auto-interseccoes.
4. **Projected Normal:** Projeta tampa com base na normal media.
5. **Centroid Cap:** Triangulacao rapida em leque a partir do centroide.
6. **Interlocking Volume:** Gera encaixes macho/femea por extrusao de volume (area projetada 0-100%, profundidade -10 a +10mm).

### 3.3 Sistema de Conectores Mecanicos
- **Formatos de pino:**
  - *Prisma Triangular:* Anti-rotacao e auto-alinhamento.
  - *Cilindro:* Tradicional redondo.
  - *Prisma Retangular:* Maxima rigidez contra torcao.
- **Polaridade:** *Part plug* (macho na peca selecionada) vs *Body plug* (macho no corpo restante).
- **Area (%):** Slider de 0 a 90% da face de corte.
- **Tolerancia do Encaixe (Socket Tolerance):** Ajuste fino em mm (padrao 0.3mm; orientacoes para PLA ~0.2-0.3mm, PETG ~0.35mm).

### 3.4 Modos de Corte Manual
- **Plano:** Eixos X, Y, Z, offset de posicao (-50% a +50%) e inclinacao (-90° a +90°).
- **Esboco (Sketch):** Selecao de uma face da bounding box e desenho de poligono livre de corte.

### 3.5 Visualizacao e UX
- **Split in Place:** Alterna entre visualizacao explodida (pecas separadas) e montada (na posicao original).
- **Undo / Redo:** Historico de acoes na viewport.
- **Download Gate:** A simulacao e corte sao 100% gratuitos; o clique em *Download* exige login (`downloadLoginRequired`), convertendo visitantes em contas cadastradas.

---

## 4. Oportunidades de Aplicacao no Nosso Projeto (projeto-impressao-3d)

1. **Conectores Anti-Rotacao (Prisma Triangular e Retangular):**
   - Incorporar na geracao de pinos/furos do nosso backend Python (`manifold3d`), evitando que partes cilindricas girem em falso apos montagem.
2. **Presets e Controle de Tolerancia na UI:**
   - Expor slider/input de tolerancia de folga (em mm) com presets automaticos por material (PLA: 0.2mm, PETG: 0.35mm, ABS: 0.3mm).
3. **Toggle "Vista Explodida" vs "Vista Montada" (Split in Place):**
   - Adicionar no nosso visualizador Three.js (`@react-three/fiber`) para o usuario inspecionar os pinos internos ou conferir o alinhamento da peca montada.
4. **Corte por Esboco (Sketch Cut):**
   - Funcionalidade futura para permitir ao usuario desviar de detalhes nobres (como faces ou texturas complexas) desenhando a linha de corte na bounding box.
5. **Geracao de 3MF Multi-Placa:**
   - Exportar pecas nao apenas em STLs avulsos, mas em um unico arquivo `.3mf` contendo as pecas ja distribuidas e identificadas para o Bambu Studio e OrcaSlicer.
6. **Estrategia de Aquisicao (Gate de Download):**
   - Manter a simulacao e conferencia da mesa de trabalho gratuitas, exigindo login/assinatura no momento de executar o corte booleano e fazer o download das pecas finais.
