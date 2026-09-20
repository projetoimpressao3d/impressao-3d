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
      // Se nao houver parts (formato painted antigo), usar a geometria mesclada como uma parte unica
      const subGeos: THREE.BufferGeometry[] =
        group.parts && group.parts.length > 0 ? group.parts : [group.geometry];

      const margin = 8;
      const spacing = 8;
      const usableW = Math.max(10, plateW - 2 * margin);

      interface PartItem {
        geo: THREE.BufferGeometry;
        ew: number;
        ed: number;
        center: THREE.Vector3;
        minZ: number;
      }

      const items: PartItem[] = subGeos.map((geo) => {
        const bbox = getGroupBBox(geo);
        const center = new THREE.Vector3();
        bbox.getCenter(center);
        return {
          geo,
          ew: bbox.max.x - bbox.min.x,
          ed: bbox.max.y - bbox.min.y,
          center,
          minZ: bbox.min.z,
        };
      });

      // Ordenar por área de projeção decrescente
      items.sort((a, b) => b.ew * b.ed - a.ew * a.ed);

      // Shelf packing 2D (em coordenadas relativas de mesa)
      let currentX = 0;
      let currentY = 0;
      let rowMaxD = 0;

      interface PlacedItem {
        item: PartItem;
        relX: number;
        relY: number;
      }

      const placed: PlacedItem[] = [];

      for (const it of items) {
        if (currentX + it.ew > usableW && currentX > 0) {
          currentX = 0;
          currentY += rowMaxD + spacing;
          rowMaxD = 0;
        }

        const relX = currentX + it.ew / 2;
        const relY = currentY + it.ed / 2;
        rowMaxD = Math.max(rowMaxD, it.ed);
        currentX += it.ew + spacing;

        placed.push({ item: it, relX, relY });
      }

      // Calcular o bounding box do layout colocado
      let minRelX = Infinity, maxRelX = -Infinity;
      let minRelY = Infinity, maxRelY = -Infinity;

      for (const p of placed) {
        const halfW = p.item.ew / 2;
        const halfD = p.item.ed / 2;
        if (p.relX - halfW < minRelX) minRelX = p.relX - halfW;
        if (p.relX + halfW > maxRelX) maxRelX = p.relX + halfW;
        if (p.relY - halfD < minRelY) minRelY = p.relY - halfD;
        if (p.relY + halfD > maxRelY) maxRelY = p.relY + halfD;
      }

      const layoutW = maxRelX - minRelX;
      const layoutD = maxRelY - minRelY;

      // Centralizar o layout na mesa:
      // X da mesa está centralizado em plateCenterX
      // Y da mesa (profundidade 3MF) está centralizado em 0
      const shiftX = (plateCenterX - layoutW / 2) - minRelX;
      const shiftY = (-layoutD / 2) - minRelY;

      const parts: PartLayout[] = placed.map(({ item, relX, relY }) => {
        const targetX = relX + shiftX;
        const targetY = relY + shiftY;

        // offset no espaco LOCAL do grupo rotacionado (3MF Z-up):
        //   X: targetX - item.center.x (centralizado/arranjado na mesa)
        //   Y: targetY - item.center.y (centralizado/arranjado na mesa)
        //   Z: -plateH / 2 - item.minZ (snap individual na base da mesa)
        const offset = new THREE.Vector3(
          targetX - item.center.x,
          targetY - item.center.y,
          -plateH / 2 - item.minZ,
        );

        return { geometry: item.geo, colorHex: group.colorHex, offset };
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