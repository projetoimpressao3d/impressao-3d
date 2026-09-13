"use client";

import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Suspense } from "react";
import type * as THREE from "three";
import type { BuildPlate, CutPlaneData, PieceBboxStatus } from "@/types/database";
import { STLMesh } from "./stl-mesh";
import { ThreeMFColoredObject } from "./threemf-colored-object";
import type { ColorGroup } from "./threemf-colored-object";
import { BuildPlateBox } from "./build-plate-box";
import { SplitEditor } from "./split-editor";
import { PiecesPreviewScene } from "./pieces-preview-scene";
import { ColorPiecesPreviewScene } from "./color-pieces-preview-scene";

interface ViewerSceneProps {
  url: string;
  format: "stl" | "3mf";
  selectedPlate: BuildPlate | null;
  onBboxChange: (bbox: THREE.Box3) => void;
  splitMode?: boolean;
  activeView?: "editor" | "preview";
  cutPlanes?: CutPlaneData[];
  pieceBboxes?: PieceBboxStatus[];
  selectedPlaneId?: string | null;
  transformMode?: "translate" | "rotate";
  onSelectPlane?: (id: string | null) => void;
  onCutPlaneMoved?: (
    id: string,
    px: number,
    py: number,
    pz: number,
    qx: number,
    qy: number,
    qz: number,
    qw: number,
  ) => void;
  onDragEnd?: () => void;
  onGeometryReady?: (positions: Float32Array) => void;
  colorPreviewMode?: boolean;
  colorGroups?: ColorGroup[];
  onGroupsParsed?: (groups: ColorGroup[]) => void;
}

export function ViewerScene({
  url,
  format,
  selectedPlate,
  onBboxChange,
  splitMode = false,
  activeView = "editor",
  cutPlanes = [],
  pieceBboxes = [],
  selectedPlaneId = null,
  transformMode = "translate",
  onSelectPlane,
  onCutPlaneMoved,
  onDragEnd,
  onGeometryReady,
  colorPreviewMode = false,
  colorGroups = [],
  onGroupsParsed,
}: ViewerSceneProps) {
  return (
    <Canvas
      camera={{ position: [0, 120, 280], fov: 45, near: 0.1, far: 100000 }}
      gl={{ antialias: true, alpha: false }}
      style={{ background: "#111827" }}
      onPointerMissed={splitMode ? () => onSelectPlane?.(null) : undefined}
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[200, 400, 300]} intensity={1.4} castShadow={false} />
      <directionalLight position={[-150, -100, -200]} intensity={0.3} />
      <hemisphereLight args={["#d0e8ff", "#1a1a2e", 0.5]} />
      <gridHelper args={[2000, 200, "#334155", "#1e293b"]} />

      <Suspense fallback={null}>
        {colorPreviewMode && colorGroups.length > 0 ? (
          <ColorPiecesPreviewScene
            groups={colorGroups}
            selectedPlate={selectedPlate}
          />
        ) : splitMode ? (
          activeView === "preview" && cutPlanes.length > 0 ? (
            <PiecesPreviewScene
              url={url}
              format={format}
              selectedPlate={selectedPlate}
              cutPlanes={cutPlanes}
              pieceBboxes={pieceBboxes}
            />
          ) : (
            <SplitEditor
              url={url}
              format={format}
              selectedPlate={selectedPlate}
              cutPlanes={cutPlanes}
              selectedPlaneId={selectedPlaneId}
              transformMode={transformMode}
              onBboxChange={onBboxChange}
              onSelectPlane={onSelectPlane ?? (() => {})}
              onCutPlaneMoved={onCutPlaneMoved ?? (() => {})}
              onDragEnd={onDragEnd ?? (() => {})}
              onGeometryReady={onGeometryReady ?? (() => {})}
            />
          )
        ) : (
          <>
            {format === "stl" ? (
              <STLMesh url={url} onBboxChange={onBboxChange} />
            ) : (
              <ThreeMFColoredObject
                url={url}
                onBboxChange={onBboxChange}
                onGeometryReady={onGeometryReady}
                onGroupsParsed={onGroupsParsed}
              />
            )}
            {selectedPlate && <BuildPlateBox plate={selectedPlate} />}
            <OrbitControls
              enablePan
              enableZoom
              enableRotate
              makeDefault
              minDistance={1}
              maxDistance={15000}
              zoomSpeed={1.2}
              panSpeed={0.8}
            />
          </>
        )}
      </Suspense>
    </Canvas>
  );
}