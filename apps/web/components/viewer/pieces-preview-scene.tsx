"use client";

import { useMemo, useEffect } from "react";
import { useLoader, useThree } from "@react-three/fiber";
import { OrbitControls, Html } from "@react-three/drei";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import { ThreeMFLoader } from "three/examples/jsm/loaders/3MFLoader.js";
import * as THREE from "three";
import type { BuildPlate, CutPlaneData, PieceBboxStatus } from "@/types/database";
import { BuildPlateBox } from "./build-plate-box";

/** Cores vibrantes e distintas para cada peca separada. */
export const PIECE_COLORS = [
  "#3b82f6", // Azul royal
  "#10b981", // Esmeralda
  "#f59e0b", // Âmbar
  "#ec4899", // Rosa
  "#8b5cf6", // Violeta
  "#06b6d4", // Ciano
  "#ef4444", // Coral
  "#84cc16", // Lima
];

interface PiecesPreviewSceneProps {
  url: string;
  format: "stl" | "3mf";
  selectedPlate: BuildPlate | null;
  cutPlanes: CutPlaneData[];
  pieceBboxes: PieceBboxStatus[];
}

function fmm(v: number): string {
  return v.toFixed(1);
}

function getClippingPlanesForPiece(
  cutPlanes: CutPlaneData[],
  pieceIdx: number,
  worldOffset: THREE.Vector3,
): THREE.Plane[] {
  const N = cutPlanes.length;
  const planes: THREE.Plane[] = [];

  for (let j = 0; j < N; j++) {
    const cp = cutPlanes[j];
    const q = new THREE.Quaternion(cp.qx, cp.qy, cp.qz, cp.qw);
    const normal = new THREE.Vector3(0, 0, 1).applyQuaternion(q).normalize();
    const origin = new THREE.Vector3(cp.px, cp.py, cp.pz);
    const localOffset = normal.dot(origin);

    if (pieceIdx < N) {
      if (j < pieceIdx) {
        const n = normal.clone().negate();
        const c = localOffset - n.dot(worldOffset);
        planes.push(new THREE.Plane(n, c));
      } else if (j === pieceIdx) {
        const n = normal.clone();
        const c = -localOffset - n.dot(worldOffset);
        planes.push(new THREE.Plane(n, c));
      }
    } else {
      const n = normal.clone().negate();
      const c = localOffset - n.dot(worldOffset);
      planes.push(new THREE.Plane(n, c));
    }
  }

  return planes;
}

function STLPreviewPiece({
  url,
  translation,
  clippingPlanes,
  color,
}: {
  url: string;
  translation: THREE.Vector3;
  clippingPlanes: THREE.Plane[];
  color: string;
}) {
  const rawGeometry = useLoader(STLLoader, url);
  const geometry = useMemo(() => {
    const geo = rawGeometry.clone();
    geo.center();
    geo.computeVertexNormals();
    return geo;
  }, [rawGeometry]);

  return (
    <mesh geometry={geometry} position={translation} castShadow receiveShadow>
      <meshStandardMaterial
        color={color}
        roughness={0.45}
        metalness={0.1}
        side={THREE.DoubleSide}
        clippingPlanes={clippingPlanes}
        clipShadows
      />
    </mesh>
  );
}

function ThreeMFPreviewPiece({
  url,
  translation,
  clippingPlanes,
  color,
}: {
  url: string;
  translation: THREE.Vector3;
  clippingPlanes: THREE.Plane[];
  color: string;
}) {
  const rawGroup = useLoader(
    ThreeMFLoader as unknown as typeof THREE.ObjectLoader,
    url,
  ) as unknown as THREE.Group;

  const pieceGroup = useMemo(() => {
    const g = rawGroup.clone(true);
    const bbox = new THREE.Box3().setFromObject(g);
    const center = new THREE.Vector3();
    bbox.getCenter(center);
    // Posiciona o modelo original centrado com a translacao desejada
    g.position.copy(translation).sub(center);

    g.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.material = new THREE.MeshStandardMaterial({
          color,
          roughness: 0.45,
          metalness: 0.1,
          side: THREE.DoubleSide,
          clippingPlanes,
          clipShadows: true,
        });
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    return g;
  }, [rawGroup, color, clippingPlanes, translation]);

  return <primitive object={pieceGroup} />;
}

export function PiecesPreviewScene({
  url,
  format,
  selectedPlate,
  cutPlanes,
  pieceBboxes,
}: PiecesPreviewSceneProps) {
  const { gl } = useThree();

  useEffect(() => {
    gl.localClippingEnabled = true;
    return () => {
      gl.localClippingEnabled = false;
    };
  }, [gl]);

  const totalPieces = cutPlanes.length + 1;
  const plateX = selectedPlate?.build_volume_x_mm ?? 200;
  const plateY = selectedPlate?.build_volume_y_mm ?? 200;
  const plateZ = selectedPlate?.build_volume_z_mm ?? 200;

  // Espacamento entre mesas (30% de folga)
  const spacingX = plateX * 1.30;
  const spacingZ = plateY * 1.30;

  // Filtrar pecas validas e calcular disposicao
  const activeLayouts = useMemo(() => {
    // Apenas pecas com bbox existente
    const validPieces = pieceBboxes.filter((pb) => pb && pb.bbox !== null);
    const count = validPieces.length > 0 ? validPieces.length : totalPieces;

    const layouts: Array<{
      pieceIndex: number;
      pieceDisplayIndex: number;
      plateCenterX: number;
      plateCenterZ: number;
      translation: THREE.Vector3;
      clippingPlanes: THREE.Plane[];
      fits: boolean;
      bbox: { x: number; y: number; z: number } | null;
    }> = [];

    const isGrid = count > 3;
    const cols = isGrid ? 2 : count;

    validPieces.forEach((pb, idx) => {
      const origIdx = pb.pieceIndex;
      let pcX = 0;
      let pcZ = 0;

      if (!isGrid) {
        pcX = (idx - (count - 1) / 2) * spacingX;
        pcZ = 0;
      } else {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        const totalRows = Math.ceil(count / cols);
        pcX = (col - (cols - 1) / 2) * spacingX;
        pcZ = (row - (totalRows - 1) / 2) * spacingZ;
      }

      const centerX = pb?.center?.x ?? 0;
      const minY = pb?.minY ?? 0;
      const centerZ = pb?.center?.z ?? 0;

      // Repousa a peca exatamente no piso da mesa (que fica em -plateZ / 2)
      const translation = new THREE.Vector3(
        pcX - centerX,
        -plateZ / 2 - minY,
        pcZ - centerZ,
      );

      const clippingPlanes = getClippingPlanesForPiece(
        cutPlanes,
        origIdx,
        translation,
      );

      layouts.push({
        pieceIndex: origIdx,
        pieceDisplayIndex: idx + 1,
        plateCenterX: pcX,
        plateCenterZ: pcZ,
        translation,
        clippingPlanes,
        fits: pb.fits,
        bbox: pb.bbox,
      });
    });

    return layouts;
  }, [pieceBboxes, totalPieces, spacingX, spacingZ, plateZ, cutPlanes]);

  return (
    <>
      <OrbitControls
        makeDefault
        target={[0, 0, 0]}
        minDistance={20}
        maxDistance={25000}
        enableDamping
        dampingFactor={0.08}
      />

      {activeLayouts.map((layout) => {
        const color = PIECE_COLORS[layout.pieceIndex % PIECE_COLORS.length];

        return (
          <group key={`preview-piece-${layout.pieceIndex}`}>
            {/* Mesa de trabalho da peca */}
            {selectedPlate && (
              <group position={[layout.plateCenterX, 0, layout.plateCenterZ]}>
                <BuildPlateBox plate={selectedPlate} />
              </group>
            )}

            {/* Peca cortada em 3D */}
            {format === "3mf" ? (
              <ThreeMFPreviewPiece
                url={url}
                translation={layout.translation}
                clippingPlanes={layout.clippingPlanes}
                color={color}
              />
            ) : (
              <STLPreviewPiece
                url={url}
                translation={layout.translation}
                clippingPlanes={layout.clippingPlanes}
                color={color}
              />
            )}

            {/* Rotulo discreto e elegante na frente da mesa (piso) */}
            <Html
              position={[layout.plateCenterX, -plateZ / 2, layout.plateCenterZ + plateY / 2 + 12]}
              center
              distanceFactor={280}
              style={{ pointerEvents: "none" }}
            >
              <div className="flex items-center gap-1.5 rounded-full border border-gray-700/80 bg-gray-900/90 px-2.5 py-1 text-[11px] font-medium text-white shadow-lg backdrop-blur-sm whitespace-nowrap select-none">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                <span>Mesa {layout.pieceDisplayIndex}: Peca {layout.pieceDisplayIndex}</span>
                {layout.bbox && (
                  <span className="text-gray-400 font-mono text-[10px]">
                    ({fmm(layout.bbox.x)}x{fmm(layout.bbox.y)}x{fmm(layout.bbox.z)}mm)
                  </span>
                )}
                <span className={layout.fits ? "text-emerald-400 font-bold" : "text-amber-400 font-bold"}>
                  {layout.fits ? "✓" : "⚠"}
                </span>
              </div>
            </Html>
          </group>
        );
      })}
    </>
  );
}
