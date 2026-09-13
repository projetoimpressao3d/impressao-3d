"use client";

/**
 * ColorPiecesPreviewScene - Exibe cada peca separada por cor em sua propria
 * mesa virtual, lado a lado na cena 3D.
 *
 * Snap Z individual por sub-objeto:
 *  - Cada sub-objeto fisico (part id no 3MF) e posicionado independentemente
 *    com seu minimo Z na base da mesa — igual ao comportamento do Split3mf.
 *  - O viewer principal (ThreeMFColoredObject) usa group.geometry que tem
 *    coordenadas originais (sem snap), para exibir o modelo montado corretamente.
 *
 * Sistema de coordenadas:
 *  - As geometrias estao em espaco 3MF (Z-up), centradas ao redor do centroide global.
 *  - O grupo pai tem rotation=[-PI/2, 0, 0], que mapeia 3MF->Three.js:
 *      3MF X -> Three.js X  (largura)
 *      3MF Y -> Three.js -Z (profundidade)
 *      3MF Z -> Three.js Y  (altura)
 *  - meshOffset.z -> controla Three.js Y (altura)
 *  - BuildPlateBox: altura pz, centrada em Y=0, base em Y=-pz/2
 *  - Para sentar na base: meshOffset.z = -plateH/2 - partBbox.min.z
 */

import { useMemo } from "react";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import type { BuildPlate } from "@/types/database";
import type { ColorGroup } from "./threemf-colored-object";
import { BuildPlateBox } from "./build-plate-box";

interface ColorPiecesPreviewSceneProps {
  groups: ColorGroup[];
  selectedPlate: BuildPlate | null;
}

function getGroupBBox(geo: THREE.BufferGeometry): THREE.Box3 {
  geo.computeBoundingBox();
  return geo.boundingBox!.clone();
}

interface PartLayout {
  geometry: THREE.BufferGeometry;
  colorHex: string;
  offset: THREE.Vector3;
}

interface PlateLayout {
  platePos: THREE.Vector3;
  parts: PartLayout[];
}

export function ColorPiecesPreviewScene({ groups, selectedPlate }: ColorPiecesPreviewSceneProps) {
  const plateW  = selectedPlate?.build_volume_x_mm ?? 256;
  const plateD  = selectedPlate?.build_volume_y_mm ?? 256;
  const plateH  = selectedPlate?.build_volume_z_mm ?? 256;
  const GAP     = Math.max(80, plateW * 0.4);

  const layouts = useMemo((): PlateLayout[] => {
    const result: PlateLayout[] = [];
    const totalWidth = groups.length * plateW + (groups.length - 1) * GAP;
    let xCursor = 0;

    for (const group of groups) {
      const plateCenterX = xCursor + plateW / 2 - totalWidth / 2;
      const platePos = new THREE.Vector3(plateCenterX, 0, 0);

      // Usar as geometrias individuais por sub-objeto (group.parts)
      // Se nao houver parts (formato painted), usar a geometria mesclada como uma parte unica
      const subGeos: THREE.BufferGeometry[] = group.parts && group.parts.length > 0
        ? group.parts
        : [group.geometry];

      // Calcular o bounding box do grupo inteiro para centralizar XY na mesa
      const groupBbox = getGroupBBox(group.parts && group.parts.length > 0
        ? group.geometry  // centroide da geometria mesclada para centralizar XY
        : group.geometry);
      const groupCenter = new THREE.Vector3();
      groupBbox.getCenter(groupCenter);

      const parts: PartLayout[] = subGeos.map((partGeo) => {
        const partBbox = getGroupBBox(partGeo);

        // offset no espaco LOCAL do grupo rotacionado (3MF Z-up):
        //   X: centralizar cada parte conforme sua posicao relativa no grupo
        //   Y: centralizar profundidade
        //   Z: snap individual da parte para a base da mesa (plateH/2 = base do BuildPlateBox)
        const offset = new THREE.Vector3(
          plateCenterX - groupCenter.x,   // X: centralizar o grupo na mesa
          -groupCenter.y,                  // Y: centralizar profundidade
          -plateH / 2 - partBbox.min.z,   // Z->Y: snap individual para a base
        );

        return { geometry: partGeo, colorHex: group.colorHex, offset };
      });

      result.push({ platePos, parts });
      xCursor += plateW + GAP;
    }

    return result;
  }, [groups, plateW, plateD, GAP, plateH]);

  if (groups.length === 0) return null;

  return (
    <>
      {/* Grupo rotacionado: converte 3MF (Z-up) para Three.js (Y-up) */}
      <group rotation={[-Math.PI / 2, 0, 0]}>
        {layouts.flatMap(({ parts }) =>
          parts.map(({ geometry, colorHex, offset }, pi) => (
            <group key={`${colorHex}-${pi}`} position={offset}>
              <mesh geometry={geometry} castShadow receiveShadow>
                <meshStandardMaterial
                  color={new THREE.Color(colorHex)}
                  roughness={0.55}
                  metalness={0.0}
                  side={THREE.DoubleSide}
                />
              </mesh>
            </group>
          ))
        )}
      </group>

      {/* Mesas de trabalho (no espaco Three.js normal) */}
      {selectedPlate && layouts.map(({ platePos }, i) => (
        <group key={`plate-${i}`} position={platePos}>
          <BuildPlateBox plate={selectedPlate} />
        </group>
      ))}

      <OrbitControls
        enablePan enableZoom enableRotate makeDefault
        minDistance={10} maxDistance={50000} zoomSpeed={1.5}
      />
    </>
  );
}