"use client";

import React, { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import * as THREE from "three";
import { createClient } from "@/lib/supabase/client";
import type {
  BuildPlate,
  CutPlaneData,
  ExecutedPiece,
  Model,
  PieceBboxStatus,
  PlanSessionResponse,
  StatusPollingResponse,
  SuggestResponse,
} from "@/types/database";
import type { ColorGroup } from "@/components/viewer/threemf-colored-object";
import type { ColorSplitResult } from "@/components/split/color-split-panel";
import { Badge } from "@/components/ui/badge";
import { IconButton } from "@/components/ui/icon-button";
import { BuildPlatesPropertiesPanel } from "./build-plates-properties-panel";
import { BuildPlateModal } from "./build-plate-modal";
import { ModelsPropertiesPanel } from "./models-properties-panel";
import { WorkspaceCanvas } from "./workspace-canvas";
import { SelectModelModal } from "./select-model-modal";
import {
  SmartSplitPropertiesPanel,
  type SmartSplitOption,
} from "./smart-split-properties-panel";

export type SidebarTabId = "build-plate" | "models" | "smart-split";

type SplitMode =
  | "idle"
  | "loading"
  | "planning"
  | "suggesting"
  | "separating"
  | "executing"
  | "done"
  | "error";

interface WorkspaceShellProps {
  userEmail: string;
  userPlan?: "free" | "pro";
  hasSubscription?: boolean;
  initialPlates?: BuildPlate[];
  initialModels?: Model[];
}

function quaternionFromNormal(normal: number[]): {
  qx: number;
  qy: number;
  qz: number;
  qw: number;
} {
  const from = new THREE.Vector3(0, 0, 1);
  const to = new THREE.Vector3(normal[0], normal[1], normal[2]).normalize();
  const q = new THREE.Quaternion().setFromUnitVectors(from, to);
  return { qx: q.x, qy: q.y, qz: q.z, qw: q.w };
}

function computePieceBboxes(
  positions: Float32Array,
  cutPlanes: CutPlaneData[],
  plate: BuildPlate | null,
): PieceBboxStatus[] {
  const N = cutPlanes.length;
  if (N === 0) return [];

  const normals = cutPlanes.map((cp) =>
    new THREE.Vector3(0, 0, 1)
      .applyQuaternion(new THREE.Quaternion(cp.qx, cp.qy, cp.qz, cp.qw))
      .normalize(),
  );
  const offsets = cutPlanes.map((cp, j) =>
    normals[j].dot(new THREE.Vector3(cp.px, cp.py, cp.pz)),
  );

  const numPieces = N + 1;
  const bboxes: PieceBboxStatus[] = Array.from(
    { length: numPieces },
    (_, i) => ({
      pieceIndex: i,
      bbox: null,
      fits: true,
    }),
  );

  const mins = Array.from({ length: numPieces }, () => [
    Infinity,
    Infinity,
    Infinity,
  ]);
  const maxs = Array.from({ length: numPieces }, () => [
    -Infinity,
    -Infinity,
    -Infinity,
  ]);

  const EPSILON = 1e-4;

  for (let vi = 0; vi < positions.length; vi += 3) {
    const px = positions[vi];
    const py = positions[vi + 1];
    const pz = positions[vi + 2];

    let assignedPiece = -1;

    for (let j = 0; j < N; j++) {
      const sd =
        normals[j].x * px +
        normals[j].y * py +
        normals[j].z * pz -
        offsets[j];

      if (sd >= -EPSILON) {
        const cp = cutPlanes[j];
        if (cp.bbox_min && cp.bbox_max) {
          const inBox =
            px >= cp.bbox_min[0] - 8.0 &&
            px <= cp.bbox_max[0] + 8.0 &&
            py >= cp.bbox_min[1] - 8.0 &&
            py <= cp.bbox_max[1] + 8.0 &&
            pz >= cp.bbox_min[2] - 8.0 &&
            pz <= cp.bbox_max[2] + 8.0;
          if (inBox) {
            assignedPiece = j;
            break;
          }
        } else {
          assignedPiece = j;
          break;
        }
      }
    }

    if (assignedPiece === -1) {
      assignedPiece = N;
    }

    if (px < mins[assignedPiece][0]) mins[assignedPiece][0] = px;
    if (py < mins[assignedPiece][1]) mins[assignedPiece][1] = py;
    if (pz < mins[assignedPiece][2]) mins[assignedPiece][2] = pz;
    if (px > maxs[assignedPiece][0]) maxs[assignedPiece][0] = px;
    if (py > maxs[assignedPiece][1]) maxs[assignedPiece][1] = py;
    if (pz > maxs[assignedPiece][2]) maxs[assignedPiece][2] = pz;
  }

  for (let i = 0; i < numPieces; i++) {
    if (mins[i][0] === Infinity) {
      bboxes[i] = { pieceIndex: i, bbox: null, fits: true };
      continue;
    }
    const bbox = {
      x: maxs[i][0] - mins[i][0],
      y: maxs[i][1] - mins[i][1],
      z: maxs[i][2] - mins[i][2],
    };
    const center = {
      x: (maxs[i][0] + mins[i][0]) / 2,
      y: (maxs[i][1] + mins[i][1]) / 2,
      z: (maxs[i][2] + mins[i][2]) / 2,
    };
    const fits = plate
      ? bbox.x <= plate.build_volume_x_mm &&
        bbox.y <= plate.build_volume_y_mm &&
        bbox.z <= plate.build_volume_z_mm
      : true;
    bboxes[i] = { pieceIndex: i, bbox, center, minY: mins[i][1], fits };
  }

  return bboxes;
}

const MENU_ITEMS: {
  id: SidebarTabId;
  label: string;
  badge?: string;
  icon: React.ReactNode;
}[] = [
  {
    id: "build-plate",
    label: "Mesa de Trabalho",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z"
        />
      </svg>
    ),
  },
  {
    id: "models",
    label: "Modelos",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12"
        />
      </svg>
    ),
  },
  {
    id: "smart-split",
    label: "Divisão Inteligente de Modelos",
    badge: "New",
    icon: (
      <svg
        className="h-4 w-4 shrink-0"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.8}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M14.121 14.121L19 19m-7-7l7-7m-7 7l-2.879 2.879M12 12L9.121 9.121m0 5.758a3 3 0 10-4.243 4.243 3 3 0 004.243-4.243zm0-5.758a3 3 0 10-4.243-4.243 3 3 0 004.243 4.243z"
        />
      </svg>
    ),
  },
];

export function WorkspaceShell({
  userEmail,
  userPlan = "free",
  hasSubscription = false,
  initialPlates = [],
  initialModels = [],
}: WorkspaceShellProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<SidebarTabId>("models");
  const [accountPopoverOpen, setAccountPopoverOpen] = useState(false);

  // Estado das Mesas de Trabalho
  const [plates, setPlates] = useState<BuildPlate[]>(initialPlates);
  const [selectedPlateId, setSelectedPlateId] = useState<string | null>(
    () =>
      initialPlates.find((p) => p.is_default)?.id ??
      initialPlates[0]?.id ??
      null,
  );
  const [plateModalOpen, setPlateModalOpen] = useState(false);
  const [editingPlate, setEditingPlate] = useState<BuildPlate | null>(null);

  // Estado dos Modelos 3D (inicia null para exigir seleção explícita quando clicar em Divisão Inteligente sem modelo carregado)
  const [models, setModels] = useState<Model[]>(initialModels);
  const [selectedModel, setSelectedModel] = useState<Model | null>(null);
  const [selectModelModalOpen, setSelectModelModalOpen] = useState(false);

  // Opção ativa em Divisão Inteligente ("colors" | "linear" | null)
  const [smartSplitOption, setSmartSplitOption] =
    useState<SmartSplitOption>(null);

  // Estado de Divisão por Cores (3MF)
  const [colorGroups, setColorGroups] = useState<ColorGroup[]>([]);
  const [colorPreviewMode, setColorPreviewMode] = useState(false);
  const [active3DUrl, setActive3DUrl] = useState<string | null>(null);
  const [colorSplitResult, setColorSplitResult] =
    useState<ColorSplitResult | null>(null);
  const [selectedColorPlateIdx, setSelectedColorPlateIdx] = useState<
    number | "all"
  >("all");

  // Estado de Corte Linear
  const [splitMode, setSplitMode] = useState<SplitMode>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [splitError, setSplitError] = useState<string | null>(null);
  const [cutPlanes, setCutPlanes] = useState<CutPlaneData[]>([]);
  const [selectedPlaneId, setSelectedPlaneId] = useState<string | null>(null);
  const [transformMode, setTransformMode] = useState<"translate" | "rotate">(
    "translate",
  );
  const [pieceBboxes, setPieceBboxes] = useState<PieceBboxStatus[]>([]);
  const [activeView, setActiveView] = useState<"editor" | "preview">("editor");
  const [separateFeedback, setSeparateFeedback] = useState<string | null>(null);
  const [executedPieces, setExecutedPieces] = useState<ExecutedPiece[]>([]);
  const [generateConnectors, setGenerateConnectors] = useState<boolean>(true);
  const [connectorPinShape, setConnectorPinShape] = useState<
    "hex" | "triangle" | "cylinder"
  >("hex");

  const modelPositionsRef = useRef<Float32Array | null>(null);
  const planeCounterRef = useRef(0);

  const activeItem =
    MENU_ITEMS.find((item) => item.id === activeTab) ?? MENU_ITEMS[0];

  const resetSplitStates = useCallback(() => {
    setColorGroups([]);
    setColorPreviewMode(false);
    setActive3DUrl(null);
    setColorSplitResult(null);
    setSelectedColorPlateIdx("all");
    setSplitMode("idle");
    setSessionId(null);
    setSplitError(null);
    setCutPlanes([]);
    setSelectedPlaneId(null);
    setPieceBboxes([]);
    setActiveView("editor");
    setSeparateFeedback(null);
    setExecutedPieces([]);
    modelPositionsRef.current = null;
  }, []);

  const handleSelectModel = useCallback(
    (model: Model) => {
      if (selectedModel?.id !== model.id) {
        resetSplitStates();
        setSmartSplitOption(model.format === "3mf" ? "colors" : "linear");
      }
      setSelectedModel(model);
    },
    [selectedModel?.id, resetSplitStates],
  );

  function handleNavigateToSmartSplit(preferredOption?: SmartSplitOption) {
    setActiveTab("smart-split");
    if (!selectedModel) {
      setSelectModelModalOpen(true);
      return;
    }
    if (preferredOption) {
      setSmartSplitOption(preferredOption);
    } else if (!smartSplitOption) {
      setSmartSplitOption(selectedModel.format === "3mf" ? "colors" : "linear");
    }
  }

  const refreshModels = useCallback(async () => {
    try {
      const res = await fetch("/api/models");
      if (res.ok) {
        const data = (await res.json()) as { models?: Model[] };
        if (data.models) {
          setModels(data.models);
          setSelectedModel((prev) => {
            if (!prev) return null;
            return data.models?.find((m) => m.id === prev.id) ?? null;
          });
        }
      }
    } catch {
      // Fallback silencioso
    }
    router.refresh();
  }, [router]);

  const hasPendingModels = models.some(
    (m) => m.printability_status === "pending",
  );
  useEffect(() => {
    if (!hasPendingModels) return;
    const interval = setInterval(() => {
      void refreshModels();
    }, 6000);
    return () => clearInterval(interval);
  }, [hasPendingModels, refreshModels]);

  async function refreshPlates() {
    try {
      const res = await fetch("/api/build-plates");
      if (res.ok) {
        const data = (await res.json()) as { plates?: BuildPlate[] };
        if (data.plates) {
          const sorted = [...data.plates].sort((a, b) =>
            a.is_default === b.is_default ? 0 : a.is_default ? -1 : 1,
          );
          setPlates(sorted);
          setSelectedPlateId((prev) => {
            if (prev && sorted.some((p) => p.id === prev)) return prev;
            return (
              sorted.find((p) => p.is_default)?.id ?? sorted[0]?.id ?? null
            );
          });
        }
      }
    } catch {
      // Fallback
    }
    router.refresh();
  }

  // ── Handlers de Corte Linear ───────────────────────────────────────────────

  const handleGeometryReady = useCallback((positions: Float32Array) => {
    modelPositionsRef.current = positions;
  }, []);

  const handleDragEnd = useCallback(() => {
    if (!modelPositionsRef.current) return;
    const plate = plates.find((p) => p.id === selectedPlateId) ?? null;
    const result = computePieceBboxes(
      modelPositionsRef.current,
      cutPlanes,
      plate,
    );
    setPieceBboxes(result);
  }, [cutPlanes, selectedPlateId, plates]);

  const handleStartSplit = useCallback(async () => {
    if (!selectedModel || !selectedPlateId) return;
    setSplitMode("loading");
    setSplitError(null);

    try {
      const res = await fetch("/api/split-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_id: selectedModel.id,
          build_plate_id: selectedPlateId,
        }),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as PlanSessionResponse;
      setSessionId(data.split_session_id);

      const initialPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
        const q = quaternionFromNormal(cp.normal);
        planeCounterRef.current += 1;
        return {
          id: `plane-${planeCounterRef.current}`,
          px: cp.origin[0],
          py: cp.origin[1],
          pz: cp.origin[2],
          ...q,
          label: cp.label,
          source: cp.source,
        };
      });

      setCutPlanes(initialPlanes);
      setPieceBboxes([]);
      setSplitMode("planning");
    } catch (err) {
      setSplitError(String(err));
      setSplitMode("error");
    }
  }, [selectedModel, selectedPlateId]);

  const handleAutoSuggest = useCallback(async () => {
    if (!sessionId) return;
    setSplitMode("suggesting");
    setSplitError(null);

    try {
      const res = await fetch(`/api/split-sessions/${sessionId}/suggest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const err = (await res.json()) as { detail?: string };
        throw new Error(err.detail ?? `HTTP ${res.status}`);
      }
      const data = (await res.json()) as SuggestResponse;

      const newPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
        const q = quaternionFromNormal(cp.normal);
        planeCounterRef.current += 1;
        return {
          id: `plane-${planeCounterRef.current}`,
          px: cp.origin[0],
          py: cp.origin[1],
          pz: cp.origin[2],
          ...q,
          label: cp.label,
          source: cp.source as CutPlaneData["source"],
        };
      });

      setCutPlanes(newPlanes);
      setSelectedPlaneId(null);

      if (modelPositionsRef.current && newPlanes.length > 0) {
        const plate = plates.find((p) => p.id === selectedPlateId) ?? null;
        const bboxes = computePieceBboxes(
          modelPositionsRef.current,
          newPlanes,
          plate,
        );
        setPieceBboxes(bboxes);
        setActiveView("preview");
      } else {
        setPieceBboxes([]);
        setActiveView("editor");
      }

      setSplitMode("planning");
    } catch (err) {
      setSplitError(String(err));
      setSplitMode("planning");
    }
  }, [sessionId, plates, selectedPlateId]);

  const handleSeparateParts = useCallback(
    async (sensitivity: number, template: string = "auto") => {
      if (!selectedModel || !selectedPlateId) return;
      setSplitMode("separating");
      setSplitError(null);

      try {
        let activeSessionId = sessionId;
        if (!activeSessionId) {
          const res = await fetch("/api/split-sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              model_id: selectedModel.id,
              build_plate_id: selectedPlateId,
            }),
          });
          if (!res.ok) {
            const err = (await res.json()) as { detail?: string };
            throw new Error(err.detail ?? `HTTP ${res.status}`);
          }
          const data = (await res.json()) as { split_session_id: string };
          activeSessionId = data.split_session_id;
          setSessionId(activeSessionId);
        }

        const sepRes = await fetch(
          `/api/split-sessions/${activeSessionId}/separate`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              structural_sensitivity: sensitivity,
              template,
            }),
          },
        );
        if (!sepRes.ok) {
          const err = (await sepRes.json()) as { detail?: string };
          throw new Error(err.detail ?? `HTTP ${sepRes.status}`);
        }

        let attempts = 0;
        const maxAttempts = 60;
        const poll = async (): Promise<void> => {
          if (attempts >= maxAttempts) {
            throw new Error("Tempo limite excedido. Tente novamente.");
          }
          attempts++;

          const statusRes = await fetch(
            `/api/split-sessions/${activeSessionId}/status`,
            { method: "GET" },
          );
          if (!statusRes.ok)
            throw new Error(`Polling falhou: HTTP ${statusRes.status}`);

          const statusData = (await statusRes.json()) as StatusPollingResponse;

          if (statusData.status === "completed") {
            const newPlanes: CutPlaneData[] = statusData.cut_planes.map(
              (cp) => {
                const q = quaternionFromNormal(cp.normal);
                planeCounterRef.current += 1;
                return {
                  id: `plane-${planeCounterRef.current}`,
                  px: cp.origin[0],
                  py: cp.origin[1],
                  pz: cp.origin[2],
                  ...q,
                  label: cp.label,
                  source: cp.source as CutPlaneData["source"],
                  structural_group: cp.structural_group ?? null,
                  bbox_min:
                    (cp as { bbox_min?: [number, number, number] | null })
                      .bbox_min ?? null,
                  bbox_max:
                    (cp as { bbox_max?: [number, number, number] | null })
                      .bbox_max ?? null,
                };
              },
            );

            setCutPlanes(newPlanes);
            setSelectedPlaneId(null);

            if (modelPositionsRef.current && newPlanes.length > 0) {
              const plate =
                plates.find((p) => p.id === selectedPlateId) ?? null;
              const bboxes = computePieceBboxes(
                modelPositionsRef.current,
                newPlanes,
                plate,
              );
              setPieceBboxes(bboxes);
              setSeparateFeedback(null);
              setActiveView("preview");
            } else {
              setPieceBboxes([]);
              setSeparateFeedback(
                `Nenhum apêndice atingiu o limiar de ${(sensitivity * 100).toFixed(0)}% do volume total. ` +
                  `Dica: reduza o controle de sensibilidade (ex: 3% ou 5%) e clique novamente em "Separar Peças".`,
              );
              setActiveView("editor");
            }

            setSplitMode("planning");
          } else if (statusData.status === "failed") {
            throw new Error(
              statusData.error_message ?? "Separação estrutural falhou.",
            );
          } else {
            await new Promise<void>((resolve) => setTimeout(resolve, 2000));
            return poll();
          }
        };

        await poll();
      } catch (err) {
        setSplitError(String(err));
        setSplitMode(sessionId ? "planning" : "error");
      }
    },
    [sessionId, selectedModel, selectedPlateId, plates],
  );

  const handleGeneralSplit = useCallback(
    async (granularity: string = "auto") => {
      if (!selectedModel || !selectedPlateId) return;
      setSplitMode("suggesting");
      setSplitError(null);

      try {
        let activeSessionId = sessionId;
        if (!activeSessionId) {
          const res = await fetch("/api/split-sessions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              model_id: selectedModel.id,
              build_plate_id: selectedPlateId,
            }),
          });
          if (!res.ok) {
            const err = (await res.json()) as { detail?: string };
            throw new Error(err.detail ?? `HTTP ${res.status}`);
          }
          const data = (await res.json()) as { split_session_id: string };
          activeSessionId = data.split_session_id;
          setSessionId(activeSessionId);
        }

        const res = await fetch(
          `/api/split-sessions/${activeSessionId}/general-split`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ granularity }),
          },
        );
        if (!res.ok) {
          const err = (await res.json()) as { detail?: string };
          throw new Error(err.detail ?? `HTTP ${res.status}`);
        }
        const data = (await res.json()) as SuggestResponse;

        const newPlanes: CutPlaneData[] = data.cut_planes.map((cp) => {
          const q = quaternionFromNormal(cp.normal);
          planeCounterRef.current += 1;
          return {
            id: `plane-${planeCounterRef.current}`,
            px: cp.origin[0],
            py: cp.origin[1],
            pz: cp.origin[2],
            ...q,
            label: cp.label,
            source: cp.source as CutPlaneData["source"],
          };
        });

        setCutPlanes(newPlanes);
        setSelectedPlaneId(null);

        if (modelPositionsRef.current && newPlanes.length > 0) {
          const plate = plates.find((p) => p.id === selectedPlateId) ?? null;
          const bboxes = computePieceBboxes(
            modelPositionsRef.current,
            newPlanes,
            plate,
          );
          setPieceBboxes(bboxes);
          setActiveView("preview");
        } else {
          setPieceBboxes([]);
          setActiveView("editor");
        }

        setSplitMode("planning");
      } catch (err) {
        setSplitError(String(err));
        setSplitMode(sessionId ? "planning" : "error");
      }
    },
    [sessionId, selectedModel, selectedPlateId, plates],
  );

  const handleAddPlane = useCallback(() => {
    planeCounterRef.current += 1;
    const newPlane: CutPlaneData = {
      id: `plane-${planeCounterRef.current}`,
      px: 0,
      py: 0,
      pz: 0,
      qx: 0,
      qy: 0,
      qz: 0,
      qw: 1,
      label: "",
      source: "manual",
    };
    setCutPlanes((prev) => [...prev, newPlane]);
    setSelectedPlaneId(newPlane.id);
  }, []);

  const handleRemovePlane = useCallback((id: string) => {
    setCutPlanes((prev) => prev.filter((p) => p.id !== id));
    setPieceBboxes([]);
  }, []);

  const handleCutPlaneMoved = useCallback(
    (
      id: string,
      px: number,
      py: number,
      pz: number,
      qx: number,
      qy: number,
      qz: number,
      qw: number,
    ) => {
      setCutPlanes((prev) =>
        prev.map((p) =>
          p.id === id ? { ...p, px, py, pz, qx, qy, qz, qw } : p,
        ),
      );
    },
    [],
  );

  const handleExecute = useCallback(async () => {
    if (!sessionId || cutPlanes.length === 0) return;
    setSplitMode("executing");

    const planesPayload = cutPlanes.map((cp) => {
      const q = new THREE.Quaternion(cp.qx, cp.qy, cp.qz, cp.qw);
      const normal = new THREE.Vector3(0, 0, 1).applyQuaternion(q).normalize();
      return {
        normal: [normal.x, normal.y, normal.z],
        origin: [cp.px, cp.py, cp.pz],
        label: cp.label,
        bbox_min: cp.bbox_min ?? null,
        bbox_max: cp.bbox_max ?? null,
      };
    });

    try {
      const res = await fetch(`/api/split-sessions/${sessionId}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cut_planes: planesPayload,
          generate_connectors: generateConnectors,
          connector_tolerance_mm: 0.2,
          connector_pin_shape: connectorPinShape,
        }),
      });

      if (!res.ok) {
        const errData = (await res.json()) as { detail?: string };
        const msg = errData.detail ?? `HTTP ${res.status}`;
        setSplitError(msg);
        setSplitMode("error");
        return;
      }

      const data = (await res.json()) as { pieces: ExecutedPiece[] };
      setExecutedPieces(data.pieces);
      setSplitMode("done");
    } catch (err) {
      setSplitError(String(err));
      setSplitMode("error");
    }
  }, [sessionId, cutPlanes, generateConnectors, connectorPinShape]);

  const handleCancelLinearSplit = useCallback(() => {
    setSplitMode("idle");
    setCutPlanes([]);
    setSelectedPlaneId(null);
    setPieceBboxes([]);
    setSessionId(null);
    setSplitError(null);
    setActiveView("editor");
    setSeparateFeedback(null);
  }, []);

  function handleOpenCreatePlate() {
    setEditingPlate(null);
    setPlateModalOpen(true);
  }

  function handleOpenEditPlate(plate: BuildPlate) {
    setEditingPlate(plate);
    setPlateModalOpen(true);
  }

  async function handleLogout() {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  }

  const isInLinearSplitMode =
    activeTab === "smart-split" &&
    smartSplitOption === "linear" &&
    (splitMode === "planning" ||
      splitMode === "suggesting" ||
      splitMode === "separating" ||
      splitMode === "executing");

  return (
    <div className="flex h-screen w-full overflow-hidden bg-zinc-950 font-sans text-zinc-200">
      {/* 1. Sidebar Principal (Esquerda) */}
      <aside className="flex w-64 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-zinc-800/60 px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg border border-emerald-500/40 bg-emerald-600/20 text-emerald-500">
            <svg
              className="h-4 w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
            >
              <circle cx="12" cy="12" r="2" />
              <circle cx="6" cy="6" r="1.5" />
              <circle cx="18" cy="6" r="1.5" />
              <circle cx="6" cy="18" r="1.5" />
              <circle cx="18" cy="18" r="1.5" />
            </svg>
          </div>
          <span className="text-sm font-semibold tracking-tight text-zinc-100">
            Impressão 3D
          </span>
        </div>

        {/* Navegação Principal */}
        <nav className="flex flex-1 flex-col gap-1.5 p-3">
          <p className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Ferramentas
          </p>
          {MENU_ITEMS.map((item) => {
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  if (item.id === "smart-split") {
                    handleNavigateToSmartSplit();
                  } else {
                    setActiveTab(item.id);
                    setSelectModelModalOpen(false);
                  }
                }}
                className={`flex w-full items-center gap-3 rounded-lg px-3.5 py-2.5 text-left text-sm transition-colors ${
                  isActive
                    ? "border-l-2 border-emerald-500 bg-emerald-950/30 font-medium text-emerald-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200"
                }`}
              >
                {item.icon}
                <span className="flex-1 leading-snug">{item.label}</span>
                {item.badge && <Badge variant="new">{item.badge}</Badge>}
              </button>
            );
          })}
        </nav>

        {/* Rodapé da Sidebar: Botões 1 (Conta), 2 (Upgrade), 3 (Logout) */}
        <div className="relative border-t border-zinc-800 p-3">
          {accountPopoverOpen && (
            <div className="mb-3 rounded-xl border border-zinc-800 bg-zinc-900 p-3 text-xs shadow-xl">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-zinc-200">Minha Conta</span>
                <Badge variant={userPlan === "pro" ? "pro" : "default"}>
                  {userPlan === "pro" ? "PRO" : "FREE"}
                </Badge>
              </div>
              <p className="mt-1.5 truncate text-zinc-400" title={userEmail}>
                {userEmail}
              </p>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2">
            {/* 1 - CONTA */}
            <IconButton
              title={`Conta (${userEmail})`}
              active={accountPopoverOpen}
              onClick={() => setAccountPopoverOpen((prev) => !prev)}
              className="flex flex-col items-center gap-1 py-2.5"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                />
              </svg>
              <span className="text-[10px] font-medium">Conta</span>
            </IconButton>

            {/* 2 - UPGRADE */}
            <button
              type="button"
              title="Fazer Upgrade para Pro"
              className="flex flex-col items-center justify-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/15 py-2.5 text-amber-400 transition-colors hover:bg-amber-500 hover:text-zinc-950"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"
                />
              </svg>
              <span className="text-[10px] font-semibold">Upgrade</span>
            </button>

            {/* 3 - LOGOUT */}
            <IconButton
              title="Sair da conta"
              onClick={handleLogout}
              className="flex flex-col items-center gap-1 py-2.5 hover:border-red-500/40 hover:bg-red-950/30 hover:text-red-400"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.8}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                />
              </svg>
              <span className="text-[10px] font-medium">Logout</span>
            </IconButton>
          </div>
        </div>
      </aside>

      {/* 2. Painel de Propriedades (Meio-Esquerda) */}
      <section className="flex w-[320px] shrink-0 flex-col border-r border-zinc-800 bg-zinc-900">
        {/* Cabeçalho do Painel de Propriedades */}
        <div className="flex h-14 items-center justify-between border-b border-zinc-800 px-4">
          <h2 className="truncate text-sm font-semibold text-zinc-200">
            {activeItem.label}
          </h2>
          <Badge variant="beta">Painel</Badge>
        </div>

        {/* Conteúdo Dinâmico por Aba */}
        {activeTab === "build-plate" ? (
          <BuildPlatesPropertiesPanel
            plates={plates}
            selectedPlateId={editingPlate?.id}
            onCreateNew={handleOpenCreatePlate}
            onEditPlate={handleOpenEditPlate}
            onDeletedPlate={() => {
              if (editingPlate) {
                setPlateModalOpen(false);
                setEditingPlate(null);
              }
              void refreshPlates();
            }}
          />
        ) : activeTab === "models" ? (
          <ModelsPropertiesPanel
            models={models}
            selectedModelId={selectedModel?.id}
            userPlan={userPlan}
            onSelectModel={(model) => handleSelectModel(model)}
            onModelsChanged={() => {
              void refreshModels();
            }}
          />
        ) : (
          <SmartSplitPropertiesPanel
            selectedModel={selectedModel}
            onOpenSelectModelModal={() => setSelectModelModalOpen(true)}
            selectedOption={smartSplitOption}
            onSelectOption={(opt) => setSmartSplitOption(opt)}
            buildPlates={plates}
            selectedPlateId={selectedPlateId}
            onPlateChange={(id) => setSelectedPlateId(id)}
            hasSubscription={hasSubscription}
            hasColorGroups={colorGroups.length > 0}
            colorPreviewMode={colorPreviewMode}
            onToggleColorPreview={() => setColorPreviewMode((v) => !v)}
            selectedColorPlateIdx={selectedColorPlateIdx}
            onSelectColorPlateIdx={setSelectedColorPlateIdx}
            onColorSplitCompleted={(result) => {
              setColorSplitResult(result);
              if (result.plates && result.plates.length > 0) {
                setSelectedColorPlateIdx(0);
              }
              if (result.unified_download_url) {
                const sep = result.unified_download_url.includes("?")
                  ? "&"
                  : "?";
                setActive3DUrl(
                  `${result.unified_download_url}${sep}t=${Date.now()}`,
                );
              }
              setColorPreviewMode(true);
            }}
            onColorSplitReset={() => {
              setActive3DUrl(null);
              setColorPreviewMode(false);
              setColorSplitResult(null);
              setSelectedColorPlateIdx("all");
            }}
            sessionId={sessionId}
            splitMode={splitMode}
            splitError={splitError}
            cutPlanes={cutPlanes}
            selectedPlaneId={selectedPlaneId}
            transformMode={transformMode}
            pieceBboxes={pieceBboxes}
            activeView={activeView}
            onViewChange={setActiveView}
            separateFeedback={separateFeedback}
            onStartSplit={handleStartSplit}
            onAutoSuggest={handleAutoSuggest}
            onSeparateParts={handleSeparateParts}
            onGeneralSplit={handleGeneralSplit}
            onAddPlane={handleAddPlane}
            onRemovePlane={handleRemovePlane}
            onSelectPlane={setSelectedPlaneId}
            onSetTransformMode={setTransformMode}
            onExecute={handleExecute}
            onCancel={handleCancelLinearSplit}
            generateConnectors={generateConnectors}
            onToggleConnectors={setGenerateConnectors}
            connectorPinShape={connectorPinShape}
            onConnectorPinShapeChange={setConnectorPinShape}
            executedPieces={executedPieces}
          />
        )}
      </section>

      {/* 3. Área Principal (Canvas 3D e Header) */}
      <main className="relative flex flex-1 flex-col overflow-hidden">
        {/* Header Superior da Área Principal */}
        <header className="flex h-14 w-full shrink-0 items-center justify-between border-b border-zinc-800/50 bg-zinc-950 px-6">
          {/* Breadcrumb / Título à esquerda */}
          <div className="flex items-center gap-2.5 text-sm">
            <span className="text-emerald-500">{activeItem.icon}</span>
            <span className="font-semibold text-zinc-200">
              {activeItem.label}
            </span>
            {selectedModel && (
              <>
                <span className="text-zinc-600">/</span>
                <span className="truncate text-xs text-zinc-400">
                  {selectedModel.name}
                </span>
              </>
            )}
          </div>

          {/* Indicadores / Ações à direita */}
          <div className="flex items-center gap-3">
            <span className="rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-1.5 text-xs text-zinc-400">
              Workspace 3D
            </span>
            <div
              title={userEmail}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-emerald-500/40 bg-emerald-600/20 text-xs font-semibold uppercase text-emerald-400"
            >
              {userEmail ? userEmail.charAt(0) : "U"}
            </div>
          </div>
        </header>

        {/* Área do Canvas 3D Central + Modais */}
        <div className="relative flex flex-1 flex-col items-center justify-center overflow-hidden bg-[radial-gradient(ellipse_at_center,_var(--tw-gradient-stops))] from-zinc-800 to-zinc-950">
          <WorkspaceCanvas
            model={selectedModel}
            buildPlates={plates}
            selectedPlateId={selectedPlateId}
            onPlateChange={setSelectedPlateId}
            onOpenCreatePlate={() => {
              setActiveTab("build-plate");
              handleOpenCreatePlate();
            }}
            showSmartSplitButton={
              selectedModel !== null && activeTab !== "smart-split"
            }
            onClickSmartSplitButton={() =>
              handleNavigateToSmartSplit("colors")
            }
            active3DUrl={active3DUrl}
            colorSplitResult={colorSplitResult}
            selectedColorPlateIdx={selectedColorPlateIdx}
            onSelectColorPlateIdx={setSelectedColorPlateIdx}
            colorPreviewMode={colorPreviewMode}
            colorGroups={colorGroups}
            onGroupsParsed={setColorGroups}
            splitMode={isInLinearSplitMode}
            activeView={activeView}
            onViewChange={setActiveView}
            cutPlanes={cutPlanes}
            pieceBboxes={pieceBboxes}
            selectedPlaneId={selectedPlaneId}
            transformMode={transformMode}
            onSelectPlane={setSelectedPlaneId}
            onCutPlaneMoved={handleCutPlaneMoved}
            onDragEnd={handleDragEnd}
            onGeometryReady={handleGeometryReady}
          />

          {/* Popup de Cadastro / Edição de Mesa sobre a Área Principal */}
          {plateModalOpen && (
            <BuildPlateModal
              existing={editingPlate}
              onClose={() => {
                setPlateModalOpen(false);
                setEditingPlate(null);
              }}
              onSaved={() => {
                setPlateModalOpen(false);
                setEditingPlate(null);
                void refreshPlates();
              }}
            />
          )}

          {/* Popup de Seleção de Modelos Cadastrados (Divisão Inteligente sem modelo ativo) */}
          {selectModelModalOpen && (
            <SelectModelModal
              models={models}
              onSelectModel={(model) => {
                handleSelectModel(model);
                setSelectModelModalOpen(false);
                setActiveTab("smart-split");
              }}
              onGoToUpload={() => {
                setSelectModelModalOpen(false);
                setActiveTab("models");
              }}
              onClose={() => setSelectModelModalOpen(false)}
            />
          )}
        </div>
      </main>
    </div>
  );
}
