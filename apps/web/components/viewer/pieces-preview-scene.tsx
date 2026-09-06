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
    geo.computeBoundingBox();
    geo.center();
    geo.computeVertexNormals();
    return geo;
  }, [rawGeometry]);

  return (
    <mesh geometry={geometry} position={translation} castShadow receiveShadow>
      <meshStandardMaterial
        color={color}
        roughness={0.4}
        metalness={0.15}
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
    g.position.sub(center);

    g.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        child.material = new THREE.MeshStandardMaterial({
          color,
          roughness: 0.4,
          metalness: 0.15,
          side: THREE.DoubleSide,
          clippingPlanes,
          clipShadows: true,
        });
        child.castShadow = true;
        child.receiveShadow = true;
      }
    });

    return g;
  }, [rawGroup, color, clippingPlanes]);

  return (
    <group position={translation}>
      <primitive object={pieceGroup} />
    </group>
  );
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

  const numPieces = cutPlanes.length + 1;
  const plateX = selectedPlate?.build_volume_x_mm ?? 200;
  const plateY = selectedPlate?.build_volume_y_mm ?? 200;
  const plateZ = selectedPlate?.build_volume_z_mm ?? 200;

  const spacingX = plateX * 1.35;
  const spacingZ = plateY * 1.35;

  const plateLayouts = useMemo(() => {
    const layouts: Array<{
      plateCenterX: number;
      plateCenterZ: number;
      translation: THREE.Vector3;
      clippingPlanes: THREE.Plane[];
    }> = [];

    const isGrid = numPieces > 3;
    const cols = isGrid ? 2 : numPieces;

    for (let i = 0; i < numPieces; i++) {
      let pcX = 0;
      let pcZ = 0;

      if (!isGrid) {
        pcX = (i - (numPieces - 1) / 2) * spacingX;
        pcZ = 0;
      } else {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const totalRows = Math.ceil(numPieces / cols);
        pcX = (col - (cols - 1) / 2) * spacingX;
        pcZ = (row - (totalRows - 1) / 2) * spacingZ;
      }

      const pb = pieceBboxes[i];
      const centerX = pb?.center?.x ?? 0;
      const minY = pb?.minY ?? 0;
      const centerZ = pb?.center?.z ?? 0;

      const translation = new THREE.Vector3(
        pcX - centerX,
        -minY,
        pcZ - centerZ,
      );

      const clippingPlanes = getClippingPlanesForPiece(
        cutPlanes,
        i,
        translation,
      );

      layouts.push({
        plateCenterX: pcX,
        plateCenterZ: pcZ,
        translation,
        clippingPlanes,
      });
    }

    return layouts;
  }, [numPieces, spacingX, spacingZ, pieceBboxes, cutPlanes]);

  const controlsTarget = useMemo(() => {
    return new THREE.Vector3(0, plateZ * 0.35, 0);
  }, [plateZ]);

  return (
    <>
      <OrbitControls
        makeDefault
        target={controlsTarget}
        minDistance={20}
        maxDistance={25000}
        enableDamping
        dampingFactor={0.08}
      />

      {plateLayouts.map((layout, i) => {
        const color = PIECE_COLORS[i % PIECE_COLORS.length];
        const pb = pieceBboxes[i];
        const fits = pb ? pb.fits : true;
        const bbox = pb?.bbox;

        return (
          <group key={`preview-piece-${i}`}>
            {selectedPlate && (
              <group position={[layout.plateCenterX, 0, layout.plateCenterZ]}>
                <BuildPlateBox plate={selectedPlate} />
              </group>
            )}

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

            <Html
              position={[layout.plateCenterX, plateZ + 20, layout.plateCenterZ]}
              center
              distanceFactor={380}
              style={{ pointerEvents: "none" }}
            >
              <div className="flex flex-col items-center gap-1 rounded-xl border border-gray-700 bg-gray-900/95 px-3 py-2 text-center shadow-xl backdrop-blur-md select-none">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block h-3 w-3 rounded-full shadow-sm"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-xs font-bold text-white tracking-wide">
                    Mesa {i + 1}: Peca {i + 1}
                  </span>
                </div>
                {bbox && (
                  <span className="text-[10px] text-gray-400 font-mono">
                    {fmm(bbox.x)} x {fmm(bbox.y)} x {fmm(bbox.z)} mm
                  </span>
                )}
                <span
                  className={`mt-0.5 rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                    fits
                      ? "bg-emerald-950/80 text-emerald-400 border border-emerald-800"
                      : "bg-red-950/80 text-red-400 border border-red-800"
                  }`}
                >
                  {fits ? "✓ Cabe na mesa" : "⚠ Excede a mesa"}
                </span>
              </div>
            </Html>
          </group>
        );
      })}
    </>
  );
}
