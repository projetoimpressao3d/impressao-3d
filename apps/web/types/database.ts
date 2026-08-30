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
