"use client";

/**
 * ThreeMFColoredObject — Renderiza arquivos .3mf do Bambu Studio com cores reais.
 *
 * Suporta dois formatos de colorização:
 *
 * A) "painted" — paint_color por triângulo (ex: Charizard com AMS painting)
 *    - Geometria: um único <object> com atributo paint_color em alguns <triangle>
 *    - Filamentos lidos de project_settings.config → filament_colour
 *    - Cor por triângulo via bitmask: pc=4→ext1, pc=8→ext2, etc.
 *
 * B) "multi_object" — objetos fisicamente separados por extruder (ex: Majin Buu "No AMS")
 *    - Geometria: múltiplos <object id="N"> em object_1.model
 *    - Extruder por objeto via model_settings.config → <part id="N" extruder="X">
 *    - Transforms de posição via 3dmodel.model → <component objectid="N" transform="...">
 *    - Cor de cada objeto = cor do filamento atribuído
 *
 * Detecção automática:
 *    - Se model_settings.config tem <part> com extruder E a geometria não tem paint_color → multi_object
 *    - Caso contrário → painted
 */

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { unzipSync } from "fflate";

// ─────────────────────────────────────────────────────────────────────────────
// Tipos exportados
// ─────────────────────────────────────────────────────────────────────────────

export interface ColorGroup {
  extruderIndex: number;   // 0-based
  colorHex: string;
  label?: string;          // nome da parte (disponível no formato multi_object)
  geometry: THREE.BufferGeometry;    // geometria mesclada (viewer principal)
  parts?: THREE.BufferGeometry[];    // geometrias individuais por sub-objeto (para preview)
  isBase: boolean;
}

interface ParseResult {
  groups: ColorGroup[];
  bbox: THREE.Box3;
  centeredPositionsYUp: Float32Array; // posições do grupo base para o pai
  method: "painted" | "multi_object";
}

interface ThreeMFColoredObjectProps {
  url: string;
  onBboxChange: (bbox: THREE.Box3) => void;
  onGeometryReady?: (positions: Float32Array) => void;
  onGroupsParsed?: (groups: ColorGroup[]) => void;
  opacity?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers comuns
// ─────────────────────────────────────────────────────────────────────────────

/** Extrai cores de filamentos do project_settings.config */
function parseFilamentColors(config: string): string[] {
  const match = config.match(/"filament_colour"\s*:\s*\[([^\]]+)\]/);
  if (!match) return [];
  return Array.from(match[1].matchAll(/"(#[0-9A-Fa-f]{6})"/g), (m) => m[1]);
}

/** Encontra o arquivo .model principal de geometria dentro do ZIP */
function findModelFile(files: Record<string, Uint8Array>): string | null {
  for (const name of Object.keys(files)) {
    if (name.startsWith("3D/Objects/") && name.endsWith(".model")) return name;
  }
  if ("3D/3dmodel.model" in files) return "3D/3dmodel.model";
  return null;
}

/** Constrói BufferGeometry a partir de uma lista plana de posições XYZ */
function buildGeoFromPositions(positions: Float32Array): THREE.BufferGeometry {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.computeVertexNormals();
  return geo;
}

/** Calcula bounding box de uma lista plana de posições XYZ */
function calcBBox(positions: Float32Array): {
  min: [number, number, number];
  max: [number, number, number];
  center: [number, number, number];
} {
  let mnX = Infinity, mnY = Infinity, mnZ = Infinity;
  let mxX = -Infinity, mxY = -Infinity, mxZ = -Infinity;
  for (let i = 0; i < positions.length; i += 3) {
    const x = positions[i], y = positions[i + 1], z = positions[i + 2];
    if (x < mnX) mnX = x; if (x > mxX) mxX = x;
    if (y < mnY) mnY = y; if (y > mxY) mxY = y;
    if (z < mnZ) mnZ = z; if (z > mxZ) mxZ = z;
  }
  return {
    min: [mnX, mnY, mnZ],
    max: [mxX, mxY, mxZ],
    center: [(mnX + mxX) / 2, (mnY + mxY) / 2, (mnZ + mxZ) / 2],
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// MÉTODO A: paint_color por triângulo (Charizard / AMS painted)
// ─────────────────────────────────────────────────────────────────────────────

/** paint_color hex string → índice de extruder 0-based.
 *  Dois formatos:
 *  - Antigo (decimal): valores como "4", "16" → fórmula: max(0, bitPos - 1)
 *  - Novo Bambu TriangleSelector (hex): cascade de 3 bits a partir do LSB.
 *    Estado = 0-indexed ext (0=laranja, 1=creme, 2=preto, 3=vermelho, 4=azul, 5=branco).
 *    Usa BigInt para suportar strings hex longas (> 32 bits).
 */
function paintColorToExtruder(pc: string | null, useNewFormat: boolean): number {
  if (!pc) return 0;
  if (useNewFormat) {
    // Bambu TriangleSelector: cascade 3-bit LSB
    // state diretamente = índice de extrusor 0-based; 0=NONE, 7=SPLIT
    try {
      let val = BigInt('0x' + pc);
      while (val > 0n) {
        const state = val & 7n;
        val >>= 3n;
        if (state === 0n || state === 7n) continue;   // NONE ou SPLIT — pula
        return Number(state);
      }
    } catch { /* string inválida */ }
    return 0;
  }
  // Formato antigo: bitmask decimal
  const val = parseInt(pc, 16);
  if (!val) return 0;
  const lowestBit = val & -val;
  const bitPos = Math.log2(lowestBit);
  return Math.max(0, bitPos - 1);
}

function parsePainted(xmlText: string, filamentColors: string[]): ParseResult {
  const vertRe = /<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"/g;
  const triRe  = /<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"(?:[^/\n>]*paint_color="([0-9A-Fa-f]+)")?/g;

  // Detectar formato Bambu hex (tem chars A-F nos valores de paint_color)
  const useNewFormat = /paint_color="[0-9]*[A-Fa-f][0-9A-Fa-f]*"/.test(xmlText);

  const rawVerts: number[] = [];
  for (const m of xmlText.matchAll(vertRe)) {
    rawVerts.push(parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3]));
  }

  const facesByExt = new Map<number, number[][]>();
  for (const m of xmlText.matchAll(triRe)) {
    const pcStr = m[4] !== undefined ? m[4] : null;
    const ext   = paintColorToExtruder(pcStr, useNewFormat);
    if (!facesByExt.has(ext)) facesByExt.set(ext, []);
    facesByExt.get(ext)!.push([parseInt(m[1]), parseInt(m[2]), parseInt(m[3])]);
  }

  // Bounding box global
  const bb = calcBBox(new Float32Array(rawVerts));
  const [cx, cy, cz] = bb.center;

  const groups: ColorGroup[] = [];
  const sortedExts = Array.from(facesByExt.keys()).sort((a, b) => a - b);

  for (const ext of sortedExts) {
    const faces = facesByExt.get(ext)!;
    const pos = new Float32Array(faces.length * 9);
    let p = 0;
    for (const [v1, v2, v3] of faces) {
      const i1 = v1 * 3, i2 = v2 * 3, i3 = v3 * 3;
      pos[p++] = rawVerts[i1] - cx; pos[p++] = rawVerts[i1+1] - cy; pos[p++] = rawVerts[i1+2] - cz;
      pos[p++] = rawVerts[i2] - cx; pos[p++] = rawVerts[i2+1] - cy; pos[p++] = rawVerts[i2+2] - cz;
      pos[p++] = rawVerts[i3] - cx; pos[p++] = rawVerts[i3+1] - cy; pos[p++] = rawVerts[i3+2] - cz;
    }
    const colorHex = ext < filamentColors.length ? filamentColors[ext] : "#888888";
    groups.push({ extruderIndex: ext, colorHex, geometry: buildGeoFromPositions(pos), isBase: ext === 0 });
  }

  // Posições centralizadas Y-up para o pai (grupo base)
  const n = rawVerts.length;
  const centeredYUp = new Float32Array(n);
  for (let i = 0; i < n; i += 3) {
    centeredYUp[i]     = rawVerts[i] - cx;
    centeredYUp[i + 1] = -(rawVerts[i + 2] - cz);
    centeredYUp[i + 2] = rawVerts[i + 1] - cy;
  }

  const bbox = new THREE.Box3(
    new THREE.Vector3(bb.min[0] - cx, -(bb.max[2] - cz), bb.min[1] - cy),
    new THREE.Vector3(bb.max[0] - cx, -(bb.min[2] - cz), bb.max[1] - cy),
  );

  return { groups, bbox, centeredPositionsYUp: centeredYUp, method: "painted" };
}

// ─────────────────────────────────────────────────────────────────────────────
// MÉTODO B: objetos separados por extruder (Majin Buu / No AMS)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Parseia o model_settings.config e retorna Map<objectId, extruderIndex_0based>
 * e Map<objectId, partName>
 */
function parseModelSettings(configXml: string): {
  partExtruder: Map<string, number>;
  partName: Map<string, string>;
} {
  const partExtruder = new Map<string, number>();
  const partName     = new Map<string, string>();

  const partRe = /<part id="(\d+)"[^>]*>([\s\S]*?)<\/part>/g;
  for (const pm of configXml.matchAll(partRe)) {
    const id   = pm[1];
    const body = pm[2];
    const extM  = body.match(/key="extruder" value="(\d+)"/);
    const nameM = body.match(/key="name" value="([^"]+)"/);
    if (extM) partExtruder.set(id, parseInt(extM[1]) - 1); // 0-based
    if (nameM) partName.set(id, nameM[1]);
  }
  return { partExtruder, partName };
}

/**
 * Parseia o 3dmodel.model (root) e retorna Map<objectId, transform[12]>
 * Transform format (3MF spec row-major): m00 m01 m02 m10 m11 m12 m20 m21 m22 tx ty tz
 */
function parseComponentTransforms(rootXml: string): Map<string, number[]> {
  const transforms = new Map<string, number[]>();
  const compRe = /objectid="(\d+)"[^>]*transform="([^"]+)"/g;
  for (const m of rootXml.matchAll(compRe)) {
    const id   = m[1];
    const vals = m[2].trim().split(/\s+/).map(Number);
    if (vals.length === 12) transforms.set(id, vals);
  }
  return transforms;
}

/**
 * Aplica transform 3MF (12 valores row-major) a um ponto (x, y, z).
 * new_x = m00*x + m01*y + m02*z + tx
 * new_y = m10*x + m11*y + m12*z + ty
 * new_z = m20*x + m21*y + m22*z + tz
 */
function applyTransform3MF(x: number, y: number, z: number, t: number[]): [number, number, number] {
  return [
    t[0]*x + t[1]*y + t[2]*z + t[9],
    t[3]*x + t[4]*y + t[5]*z + t[10],
    t[6]*x + t[7]*y + t[8]*z + t[11],
  ];
}

/** Parseia um bloco XML de um único <object> e retorna suas posições após aplicar transform */
function parseObjectBlock(block: string, transform: number[] | null): Float32Array {
  // Extrair vértices deste objeto (índices locais, começando em 0)
  const vertRe = /<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"/g;
  const triRe  = /<triangle v1="(\d+)" v2="(\d+)" v3="(\d+)"/g;

  const localVerts: number[] = [];
  for (const m of block.matchAll(vertRe)) {
    let x = parseFloat(m[1]), y = parseFloat(m[2]), z = parseFloat(m[3]);
    if (transform) {
      [x, y, z] = applyTransform3MF(x, y, z, transform);
    }
    localVerts.push(x, y, z);
  }

  // Contar triângulos para alocar buffer
  const tris: [number, number, number][] = [];
  for (const m of block.matchAll(triRe)) {
    tris.push([parseInt(m[1]), parseInt(m[2]), parseInt(m[3])]);
  }

  // Expandir (indexed → flat)
  const positions = new Float32Array(tris.length * 9);
  let p = 0;
  for (const [v1, v2, v3] of tris) {
    const i1 = v1 * 3, i2 = v2 * 3, i3 = v3 * 3;
    positions[p++] = localVerts[i1]; positions[p++] = localVerts[i1+1]; positions[p++] = localVerts[i1+2];
    positions[p++] = localVerts[i2]; positions[p++] = localVerts[i2+1]; positions[p++] = localVerts[i2+2];
    positions[p++] = localVerts[i3]; positions[p++] = localVerts[i3+1]; positions[p++] = localVerts[i3+2];
  }
  return positions;
}

function parseMultiObject(
  objXml: string,
  rootXml: string,
  modelSettingsXml: string,
  filamentColors: string[],
): ParseResult {
  const { partExtruder, partName } = parseModelSettings(modelSettingsXml);
  const compTransforms = parseComponentTransforms(rootXml);

  const objRe = /\<object id="(\d+)"[^>]*>([\s\S]*?)\<\/object>/g;

  // Acumular posições por extruder (para mesclagem — viewer principal)
  const posByExt    = new Map<number, number[]>();
  // Acumular posições POR OBJETO INDIVIDUAL dentro de cada extruder (para preview)
  const partsByExt  = new Map<number, number[][]>();
  const labelByExt  = new Map<number, string[]>();

  for (const m of objXml.matchAll(objRe)) {
    const objId     = m[1];
    const block     = m[2];
    const extIdx    = partExtruder.get(objId) ?? 0;
    const transform = compTransforms.get(objId) ?? null;
    const name      = partName.get(objId);

    const positions = parseObjectBlock(block, transform);
    if (positions.length === 0) continue;

    if (!posByExt.has(extIdx)) {
      posByExt.set(extIdx, []);
      partsByExt.set(extIdx, []);
      labelByExt.set(extIdx, []);
    }

    // Geometria mesclada (coordenadas originais, sem snap)
    const arr = posByExt.get(extIdx)!;
    for (let i = 0; i < positions.length; i++) arr.push(positions[i]);

    // Cópia independente deste sub-objeto (para preview com snap individual)
    const partRaw: number[] = [];
    for (let i = 0; i < positions.length; i++) partRaw.push(positions[i]);
    partsByExt.get(extIdx)!.push(partRaw);

    if (name) labelByExt.get(extIdx)!.push(name);
  }

  // Calcular bounding box e centroide GLOBAL (todas as posições, todos os extruders)
  let mnX = Infinity, mnY = Infinity, mnZ = Infinity;
  let mxX = -Infinity, mxY = -Infinity, mxZ = -Infinity;
  for (const positions of posByExt.values()) {
    for (let i = 0; i < positions.length; i += 3) {
      const x = positions[i], y = positions[i+1], z = positions[i+2];
      if (x < mnX) mnX = x; if (x > mxX) mxX = x;
      if (y < mnY) mnY = y; if (y > mxY) mxY = y;
      if (z < mnZ) mnZ = z; if (z > mxZ) mxZ = z;
    }
  }
  const cx = (mnX + mxX) / 2;
  const cy = (mnY + mxY) / 2;
  const cz = (mnZ + mxZ) / 2;

  // Construir ColorGroups com centralização global completa (viewer principal)
  const groups: ColorGroup[] = [];
  const sortedExts = Array.from(posByExt.keys()).sort((a, b) => a - b);

  for (const ext of sortedExts) {
    const rawPos = posByExt.get(ext)!;

    // Geometria mesclada (viewer principal — coordenadas originais centradas)
    const positions = new Float32Array(rawPos.length);
    for (let i = 0; i < rawPos.length; i += 3) {
      positions[i]   = rawPos[i]   - cx;
      positions[i+1] = rawPos[i+1] - cy;
      positions[i+2] = rawPos[i+2] - cz;  // Z centrado — modelo aparece em posição original
    }

    // Geometrias individuais por sub-objeto (preview — mesmo centroide global, sem snap)
    // O snap Z individual será aplicado no ColorPiecesPreviewScene por parte
    const rawParts = partsByExt.get(ext) ?? [];
    const partGeos: THREE.BufferGeometry[] = rawParts.map((rawPart) => {
      const partPos = new Float32Array(rawPart.length);
      for (let i = 0; i < rawPart.length; i += 3) {
        partPos[i]   = rawPart[i]   - cx;
        partPos[i+1] = rawPart[i+1] - cy;
        partPos[i+2] = rawPart[i+2] - cz;  // mesmo centroide global
      }
      return buildGeoFromPositions(partPos);
    });

    const colorHex = ext < filamentColors.length ? filamentColors[ext] : "#888888";
    const labels   = labelByExt.get(ext) ?? [];
    groups.push({
      extruderIndex: ext,
      colorHex,
      label: labels.join(", "),
      geometry: buildGeoFromPositions(positions),
      parts: partGeos,
      isBase: ext === 0,
    });
  }

  // Posições Y-up do grupo base para callbacks do viewer principal
  const baseGroup   = groups.find(g => g.isBase) ?? groups[0];
  const basePosAttr = baseGroup?.geometry.getAttribute("position");
  const n           = basePosAttr?.count ?? 0;
  const centeredYUp = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    centeredYUp[i*3]   = basePosAttr!.getX(i);
    centeredYUp[i*3+1] = -basePosAttr!.getZ(i);  // rot -90X: 3MF Z → Three.js Y
    centeredYUp[i*3+2] = basePosAttr!.getY(i);
  }

  const bbox = new THREE.Box3(
    new THREE.Vector3(mnX - cx, -(mxZ - cz), mnY - cy),
    new THREE.Vector3(mxX - cx, -(mnZ - cz), mxY - cy),
  );

  return { groups, bbox, centeredPositionsYUp: centeredYUp, method: "multi_object" };
}

// ─────────────────────────────────────────────────────────────────────────────
// Detecção automática de formato
// ─────────────────────────────────────────────────────────────────────────────

function detectMethod(
  objXml: string,
  modelSettingsXml: string | null,
): "painted" | "multi_object" {
  // Se model_settings tem <part> com extruder
  if (modelSettingsXml) {
    const hasParts    = /<part id="/.test(modelSettingsXml);
    const hasExtruder = /key="extruder"/.test(modelSettingsXml);
    if (hasParts && hasExtruder) {
      // Verificar paint_color no conteúdo inteiro — os primeiros 50KB são só vértices
      const hasPaintColor = /paint_color="[0-9A-Fa-f]+"/.test(objXml);
      if (!hasPaintColor) return "multi_object";
    }
  }
  return "painted";
}

// ─────────────────────────────────────────────────────────────────────────────
// Hook de carregamento e parsing
// ─────────────────────────────────────────────────────────────────────────────

function useThreeMFParsed(url: string) {
  const [result, setResult] = useState<ParseResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);

    (async () => {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const buffer = await resp.arrayBuffer();
        const files = unzipSync(new Uint8Array(buffer));

        const modelPath = findModelFile(files);
        if (!modelPath) throw new Error("Geometria nao encontrada no 3MF");

        const objXml  = new TextDecoder().decode(files[modelPath]);
        const rootXml = files["3D/3dmodel.model"]
          ? new TextDecoder().decode(files["3D/3dmodel.model"])
          : "";

        let filamentColors: string[] = [];
        let modelSettingsXml: string | null = null;
        if (files["Metadata/project_settings.config"]) {
          filamentColors = parseFilamentColors(
            new TextDecoder().decode(files["Metadata/project_settings.config"]),
          );
        }
        if (files["Metadata/model_settings.config"]) {
          modelSettingsXml = new TextDecoder().decode(files["Metadata/model_settings.config"]);
        }

        const method = detectMethod(objXml, modelSettingsXml);
        console.log("[3MF] Método detectado:", method, "| Filamentos:", filamentColors);

        let parsed: ParseResult;
        if (method === "multi_object" && modelSettingsXml) {
          parsed = parseMultiObject(objXml, rootXml, modelSettingsXml, filamentColors);
        } else {
          parsed = parsePainted(objXml, filamentColors);
        }

        console.log("[3MF] Grupos:", parsed.groups.map(g => ({
          ext: g.extruderIndex + 1,
          color: g.colorHex,
          label: g.label,
          triangles: g.geometry.attributes.position.count / 3,
        })));

        if (!cancelled) setResult(parsed);
      } catch (err) {
        console.error("[3MF] Erro:", err);
        if (!cancelled) setError(String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => { cancelled = true; };
  }, [url]);

  return { result, loading, error };
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-componente: mesh individual por grupo de cor
// ─────────────────────────────────────────────────────────────────────────────

function ColorMesh({ group, renderOrder }: { group: ColorGroup; renderOrder: number }) {
  const color = useMemo(() => new THREE.Color(group.colorHex), [group.colorHex]);

  if (group.isBase) {
    return (
      <mesh geometry={group.geometry} renderOrder={0} castShadow receiveShadow>
        <meshStandardMaterial color={color} roughness={0.55} metalness={0.0} side={THREE.FrontSide} />
      </mesh>
    );
  }

  return (
    <mesh geometry={group.geometry} renderOrder={renderOrder}>
      <meshStandardMaterial
        color={color}
        roughness={0.55}
        metalness={0.0}
        side={THREE.DoubleSide}
        depthWrite={false}
        polygonOffset
        polygonOffsetFactor={-renderOrder}
        polygonOffsetUnits={-renderOrder}
      />
    </mesh>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Componente principal exportado
// ─────────────────────────────────────────────────────────────────────────────

export function ThreeMFColoredObject({
  url,
  onBboxChange,
  onGeometryReady,
  onGroupsParsed,
  opacity = 1,
}: ThreeMFColoredObjectProps) {
  const { result, loading, error } = useThreeMFParsed(url);
  const reportedRef = useRef(false);

  useEffect(() => {
    if (!result || reportedRef.current) return;
    reportedRef.current = true;
    onBboxChange(result.bbox);
    onGeometryReady?.(result.centeredPositionsYUp);
    onGroupsParsed?.(result.groups);
  }, [result, onBboxChange, onGeometryReady, onGroupsParsed]);

  if (loading || !result) return null;
  if (error) { console.error("ThreeMFColoredObject:", error); return null; }

  return (
    <group rotation={[-Math.PI / 2, 0, 0]}>
      {result.groups.map((g, i) => (
        <ColorMesh key={g.extruderIndex} group={g} renderOrder={i} />
      ))}
    </group>
  );
}