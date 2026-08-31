// =============================================================================
// Tipos TypeScript espelhando o schema do banco de dados (seção 5 do AGENTS.md)
// Manter sincronizado com apps/web/supabase/migrations/0001_init.sql
// =============================================================================

export interface Profile {
  id: string;
  display_name: string | null;
  plan: "free" | "pro";
  created_at: string;
}

export interface BuildPlate {
  id: string;
  user_id: string;
  name: string;
  build_volume_x_mm: number;
  build_volume_y_mm: number;
  build_volume_z_mm: number;
  nozzle_diameter_mm: number | null;
  is_default: boolean;
  created_at: string;
}

export interface Model {
  id: string;
  user_id: string;
  name: string;
  original_filename: string | null;
  storage_path: string;
  format: "stl" | "3mf" | "obj" | "gltf";
  source: "upload" | "ai_generated";
  bounding_box_x_mm: number | null;
  bounding_box_y_mm: number | null;
  bounding_box_z_mm: number | null;
  printability_status: "pending" | "ok" | "warning" | "error";
  printability_report: PrintabilityReport | null;
  created_at: string;
}

export interface PrintabilityReport {
  is_watertight: boolean;
  is_volume: boolean;
  non_manifold_edge_count: number;
  face_count: number;
  vertex_count: number;
  error?: string;
}

export interface SplitSession {
  id: string;
  model_id: string;
  user_id: string;
  build_plate_id: string;
  status: "draft" | "processing" | "completed" | "failed";
  cut_planes: CutPlane[];
  has_connectors: boolean;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface CutPlane {
  position: [number, number, number];
  normal: [number, number, number];
}

export interface Piece {
  id: string;
  split_session_id: string;
  piece_index: number;
  storage_path: string;
  bounding_box_x_mm: number | null;
  bounding_box_y_mm: number | null;
  bounding_box_z_mm: number | null;
  fits_build_plate: boolean;
  created_at: string;
}

export interface Subscription {
  id: string;
  user_id: string;
  stripe_customer_id: string | null;
  stripe_subscription_id: string | null;
  plan: "free" | "pro";
  status: "active" | "canceled" | "past_due" | "trialing";
  current_period_end: string | null;
}

// ---------------------------------------------------------------------------
// Contratos de API entre Next.js e mesh-service
// ---------------------------------------------------------------------------

export interface AnalyzeRequest {
  model_id: string;
  storage_path: string;
  user_id: string;
}

export interface UploadUrlResponse {
  signedUrl: string;
  storagePath: string;
  format: string;
}

export interface CreateModelRequest {
  name: string;
  storage_path: string;
  format: Model["format"];
  original_filename: string;
}

// ---------------------------------------------------------------------------
// Contratos de API — Split Sessions (Fase 5)
// ---------------------------------------------------------------------------

/** Estado de um plano de corte no frontend (posição + quaternion em R3F/Three.js). */
export interface CutPlaneData {
  id: string;
  /** Posição do centro do plano no espaço do modelo (centrado na origem). */
  px: number;
  py: number;
  pz: number;
  /** Quaternion representando a orientação do plano. PlaneGeometry padrão: normal = [0,0,1]. */
  qx: number;
  qy: number;
  qz: number;
  qw: number;
  label: string;
  /**
   * Origem do plano:
   * - "suggested_natural": detectado como gargalo anatômico por trimesh.section
   * - "suggested_grid_fallback": gerado por divisão em grade (sem gargalo natural)
   * - "manual": adicionado pelo usuário via "+ Adicionar plano"
   */
  source: "suggested_natural" | "suggested_grid_fallback" | "manual";
}

/** Status de fit de uma peça resultante do corte. */
export interface PieceBboxStatus {
  pieceIndex: number;
  /** Dimensões em mm (da bounding box, após corte — aproximadas por filtragem de vértices). */
  bbox: { x: number; y: number; z: number } | null;
  fits: boolean;
}

/** Resposta do POST /split-sessions (planejamento). */
export interface PlanSessionResponse {
  split_session_id: string;
  fits: boolean;
  model_dimensions: { x: number; y: number; z: number };
  plate_dimensions: { x: number; y: number; z: number };
  cut_planes: Array<{
    normal: number[];
    origin: number[];
    label: string;
    source: "suggested_natural" | "suggested_grid_fallback";
  }>;
}


/** Resposta do POST /split-sessions/{id}/execute. */
export interface ExecuteResponse {
  split_session_id: string;
  status: string;
  piece_count: number;
  pieces: ExecutedPiece[];
}

/** Peça resultante do corte booleano, com URL assinada para download. */
export interface ExecutedPiece {
  id: string;
  piece_index: number;
  storage_path: string;
  bounding_box_x_mm: number | null;
  bounding_box_y_mm: number | null;
  bounding_box_z_mm: number | null;
  fits_build_plate: boolean;
  download_url: string | null;
}

/** Resposta do POST /split-sessions/{id}/suggest (análise automática de gargalos). */
export interface SuggestResponse {
  split_session_id: string;
  cut_planes: Array<{
    normal: number[];
    origin: number[];
    label: string;
    source: "suggested_natural" | "suggested_grid_fallback";
  }>;
  natural_count: number;
  grid_count: number;
}
