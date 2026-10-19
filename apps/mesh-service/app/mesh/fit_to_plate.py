import logging
import numpy as np
import trimesh
from scipy import ndimage as ndi
from scipy.spatial import cKDTree

from .connectors import slice_and_cap_with_connectors, split_spatially_disconnected
from .cutter import CutPlaneInput, _clean_piece_shards, cut_mesh_by_planes

logger = logging.getLogger(__name__)


def _fits_plate(extents: np.ndarray | list[float], plate_x: float, plate_y: float, plate_z: float) -> bool:
    return (
        float(extents[0]) <= plate_x
        and float(extents[1]) <= plate_y
        and float(extents[2]) <= plate_z
    )


def _orient_piece_to_fit_if_needed(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
) -> trimesh.Trimesh:
    """
    Se a peça não cabe na orientação atual mas cabe girando no plano XY
    ou deitando o maior eixo, aplica a rotação limpa que a faz caber.
    """
    if _fits_plate(mesh.extents, plate_x, plate_y, plate_z):
        return mesh

    rotations = [
        trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1]),
        trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]),
        trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]),
        trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]),
        trimesh.transformations.rotation_matrix(-np.pi / 2, [0, 1, 0]),
    ]
    for R in rotations:
        cand = mesh.copy()
        cand.apply_transform(R)
        if _fits_plate(cand.extents, plate_x, plate_y, plate_z):
            cand.metadata.update(mesh.metadata)
            return cand

    for deg in range(15, 180, 15):
        R = trimesh.transformations.rotation_matrix(np.radians(deg), [0, 0, 1])
        cand = mesh.copy()
        cand.apply_transform(R)
        if _fits_plate(cand.extents, plate_x, plate_y, plate_z):
            cand.metadata.update(mesh.metadata)
            return cand

    return mesh


def _ensure_no_floating_islands(mesh: trimesh.Trimesh) -> list[trimesh.Trimesh]:
    """
    Garante que nenhum objeto contenha ilhas desconectadas flutuando no ar,
    usando agrupamento espacial 3D (`cKDTree` com `gap_mm=1.2`) para preservar
    as tampas planares e os pinos de encaixe unidos à peça principal.
    """
    try:
        clusters = split_spatially_disconnected(mesh, gap_mm=1.2, min_speckle_faces=45)
        if not clusters:
            return [mesh]
        if len(clusters) == 1:
            clusters[0].metadata.update(mesh.metadata)
            return [clusters[0]]

        main_comp = clusters[0]
        main_comp.metadata.update(mesh.metadata)
        main_faces = len(main_comp.faces)
        out = [main_comp]

        for idx, c in enumerate(clusters[1:], start=2):
            if len(c.faces) >= max(600, int(0.18 * main_faces)):
                c.metadata.update(mesh.metadata)
                base_lbl = mesh.metadata.get("label", "Parte")
                c.metadata["label"] = f"{base_lbl} ({idx})"
                out.append(c)

        return out
    except Exception:
        return [mesh]


def _cut_appendage_localized_trimesh(
    body_mesh: trimesh.Trimesh,
    reg_mask: np.ndarray,
    vm_origin: np.ndarray,
    vm_pitch: float,
    plane_origin: np.ndarray,
    plane_normal: np.ndarray,
    generate_connectors: bool,
    connector_tolerance_mm: float,
    connector_pin_shape: str,
) -> tuple[trimesh.Trimesh | None, trimesh.Trimesh, int]:
    """
    Executa um corte planar LOCALIZADO (Bounded Cut) diretamente na malha Trimesh original:
    Apenas os triângulos dentro da máscara dilatada do apêndice (`reg_mask`) são seccionados
    pelo plano da junta, garantindo que o plano nunca atinja outras partes do modelo
    e adicionando conectores macho/fêmea via `polylabel`.
    """
    dil = ndi.binary_dilation(reg_mask, iterations=5)
    c_f = body_mesh.triangles_center
    idx = np.clip(
        np.floor((c_f - vm_origin) / vm_pitch).astype(int),
        0,
        np.array(dil.shape) - 1,
    )
    in_zone = dil[idx[:, 0], idx[:, 1], idx[:, 2]]
    in_indices = np.where(in_zone)[0]
    out_indices = np.where(~in_zone)[0]

    if len(in_indices) < 30 or len(out_indices) < 30:
        return None, body_mesh, 0

    sub_in = body_mesh.submesh([in_indices], append=True)
    sub_out = body_mesh.submesh([out_indices], append=True)

    part_raw, rest_in_raw, pins = slice_and_cap_with_connectors(
        sub_in,
        plane_origin=plane_origin,
        plane_normal=plane_normal,
        generate_connectors=generate_connectors,
        tolerance_mm=connector_tolerance_mm,
        pin_shape=connector_pin_shape,
        reintegrate_grazed_islands=True,
    )

    if len(part_raw.faces) < 30 or len(rest_in_raw.faces) == 0:
        return None, body_mesh, 0

    part_clusters = split_spatially_disconnected(part_raw, gap_mm=1.2, min_speckle_faces=30)
    if not part_clusters:
        return None, body_mesh, 0

    part_main = part_clusters[0]
    extra_for_body = part_clusters[1:] if len(part_clusters) > 1 else []

    new_body = trimesh.util.concatenate([sub_out, rest_in_raw] + extra_for_body)
    new_body.merge_vertices()

    body_clusters = split_spatially_disconnected(new_body, gap_mm=1.2, min_speckle_faces=35)
    if len(body_clusters) > 1:
        main_body = body_clusters[0]
        tree_part = cKDTree(part_main.vertices)
        tree_body = cKDTree(main_body.vertices)
        kept_body = [main_body]
        attach_to_part = []
        for bc in body_clusters[1:]:
            d_part = float(np.min(tree_part.query(bc.vertices, k=1)[0]))
            d_body = float(np.min(tree_body.query(bc.vertices, k=1)[0]))
            if d_part < d_body:
                attach_to_part.append(bc)
            else:
                kept_body.append(bc)
        if attach_to_part:
            part_main = trimesh.util.concatenate([part_main] + attach_to_part)
            part_main.merge_vertices()
        new_body = trimesh.util.concatenate(kept_body)
        new_body.merge_vertices()

    part_main.metadata["pins_created"] = pins
    return part_main, new_body, pins


def _try_anatomical_appendage_split(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
    generate_connectors: bool,
    connector_tolerance_mm: float,
    connector_pin_shape: str,
) -> tuple[trimesh.Trimesh, list[trimesh.Trimesh]]:
    """
    Detecta apêndices proeminentes (Asas, Cauda, etc.) usando transformada de distância
    volumétrica rápida (1.0mm) e destaca apenas os apêndices necessários nas juntas
    diretamente na malha original (sem remalhamento por voxel).
    Mantém membros pequenos (ex: braços curtos) unidos ao tronco se o tronco + braços
    já couber na largura da mesa.
    """
    try:
        from .region_split import _mask_to_mesh, segment_regions, to_manifold, voxelize_solid

        seg_pitch = 1.0
        vm = voxelize_solid(mesh, seg_pitch, close_iters=1)
        if vm.solid.sum() < 100:
            return mesh, []

        m_vox = to_manifold(_mask_to_mesh(vm.solid, vm.origin, vm.pitch))
        seg = segment_regions(m_vox, seg_pitch=seg_pitch)
        if not seg.regions:
            return mesh, []

        # Verificar se os braços podem permanecer unidos ao tronco sem estourar a largura X da mesa
        trunk_plus_arms = seg.trunk_mask.copy()
        for r in seg.regions:
            if r.label.startswith("Braço"):
                trunk_plus_arms |= r.mask
        ta_pts = seg.vm.centers(trunk_plus_arms)
        ta_ext = ta_pts.max(0) - ta_pts.min(0)
        keep_arms_on_trunk = float(ta_ext[0]) <= plate_x * 1.02

        detached_pieces: list[trimesh.Trimesh] = []
        current_body = mesh.copy()

        for r in seg.regions:
            if keep_arms_on_trunk and r.label.startswith("Braço"):
                logger.info("Mantendo '%s' unido ao tronco para preservar integridade do busto.", r.label)
                continue

            part_mesh, current_body, pins = _cut_appendage_localized_trimesh(
                current_body,
                reg_mask=r.mask,
                vm_origin=seg.vm.origin,
                vm_pitch=seg.vm.pitch,
                plane_origin=r.plane_origin,
                plane_normal=r.plane_normal,
                generate_connectors=generate_connectors,
                connector_tolerance_mm=connector_tolerance_mm,
                connector_pin_shape=connector_pin_shape,
            )
            if part_mesh is not None and len(part_mesh.faces) >= 50:
                part_mesh = _orient_piece_to_fit_if_needed(part_mesh, plate_x, plate_y, plate_z)
                part_mesh.metadata["label"] = r.label
                part_mesh.metadata["pins_created"] = pins
                detached_pieces.append(part_mesh)
                logger.info(
                    "Apêndice destacado na junta: '%s' extents=%s pins=%d",
                    r.label,
                    np.round(part_mesh.extents, 1).tolist(),
                    pins,
                )

        if detached_pieces:
            current_body.metadata["is_trunk"] = True
            current_body.metadata["label"] = "Tronco"

        return current_body, detached_pieces
    except Exception as exc:
        logger.warning("Segmentação anatômica de apêndices ignorada (%s); usando bisseção balanceada.", exc)
        return mesh, []


def _choose_best_bisection_plane(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
    depth: int,
) -> tuple[int, float, str, str]:
    """
    Escolhe o eixo e a posição de corte dentro da janela central [0.32, 0.68] que:
    1. Evita rachar o tronco/cabeça verticalmente ao meio em X quando um corte horizontal em Z resolve;
    2. Maximiza o número de metades resultantes que já cabem 100% na mesa (Lookahead de encaixe);
    3. Minimiza o perímetro da seção transversal (corta na cintura/gargalo mais estreito).
    """
    extents = mesh.extents
    plates = [plate_x, plate_y, plate_z]
    ratios = [extents[0] / plate_x, extents[1] / plate_y, extents[2] / plate_z]
    is_trunk = bool(mesh.metadata.get("is_trunk", False))

    if is_trunk and extents[2] > plate_z:
        candidate_axes = [2]
    else:
        oversized_axes = [ax for ax in range(3) if extents[ax] > plates[ax]]
        candidate_axes = oversized_axes if oversized_axes else [int(np.argmax(ratios))]

    verts = mesh.vertices
    bounds = mesh.bounds

    best_choice = None

    for ax in candidate_axes:
        b_min = float(bounds[0][ax])
        b_max = float(bounds[1][ax])
        length = b_max - b_min
        if length < 1e-3:
            continue

        normal = [0.0, 0.0, 0.0]
        normal[ax] = 1.0

        test_fracs = np.linspace(0.32, 0.68, 13)
        for frac in test_fracs:
            pos = float(b_min + frac * length)
            u_verts = verts[verts[:, ax] >= pos]
            l_verts = verts[verts[:, ax] <= pos]
            if len(u_verts) < 10 or len(l_verts) < 10:
                continue

            u_ext = u_verts.max(0) - u_verts.min(0)
            l_ext = l_verts.max(0) - l_verts.min(0)

            u_fits = int(_fits_plate(u_ext, plate_x, plate_y, plate_z))
            l_fits = int(_fits_plate(l_ext, plate_x, plate_y, plate_z))
            both_fit = int(u_fits == 1 and l_fits == 1)

            remaining_over = sum(1 for i in range(3) if u_ext[i] > plates[i]) + sum(
                1 for i in range(3) if l_ext[i] > plates[i]
            )
            max_over_ratio = max(
                max(u_ext[i] / plates[i] for i in range(3)),
                max(l_ext[i] / plates[i] for i in range(3)),
            )

            orig = [0.0, 0.0, 0.0]
            orig[ax] = pos
            perim = float("inf")
            try:
                lines = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=orig)
                if lines is not None and len(lines) > 0:
                    perim = float(np.sum(np.linalg.norm(lines[:, 0] - lines[:, 1], axis=1)))
            except Exception:
                pass

            axis_pref = 0 if ax == 2 else (1 if ax == 1 else 2)
            key = (
                -both_fit,
                -(u_fits + l_fits),
                remaining_over,
                axis_pref,
                round(max_over_ratio, 2),
                perim,
            )
            if best_choice is None or key < best_choice[0]:
                best_choice = (key, ax, pos)

    if best_choice is None:
        ax = int(np.argmax(ratios))
        pos = float(0.5 * (bounds[0][ax] + bounds[1][ax]))
    else:
        _, ax, pos = best_choice

    if is_trunk and ax == 2:
        lbl_top = "Busto e Cabeça"
        lbl_bot = "Base e Pernas"
    elif ax == 2:
        lbl_top = "Parte Superior"
        lbl_bot = "Parte Inferior"
    elif ax == 1:
        lbl_top = f"Parte Traseira (Y_{depth+1})"
        lbl_bot = f"Parte Frontal (Y_{depth+1})"
    else:
        lbl_top = f"Parte Direita (X_{depth+1})"
        lbl_bot = f"Parte Esquerda (X_{depth+1})"

    return ax, pos, lbl_top, lbl_bot


def fit_to_plate(
    mesh: trimesh.Trimesh,
    plate_x: float,
    plate_y: float,
    plate_z: float,
    generate_connectors: bool = True,
    connector_tolerance_mm: float = 0.2,
    connector_pin_shape: str = "hex",
    depth: int = 0,
    max_depth: int = 4,
) -> list[trimesh.Trimesh]:
    if len(mesh.vertices) < 4 or len(mesh.faces) < 20:
        return [mesh]

    # No nível raiz (depth=0), remover micro-respingos de pintura isolados no espaço
    if depth == 0:
        clean_initial = split_spatially_disconnected(mesh, gap_mm=1.2, min_speckle_faces=40)
        if clean_initial:
            meta_bak = dict(mesh.metadata)
            mesh = clean_initial[0]
            mesh.metadata.update(meta_bak)

    mesh = _orient_piece_to_fit_if_needed(mesh, plate_x, plate_y, plate_z)
    extents = mesh.extents

    if _fits_plate(extents, plate_x, plate_y, plate_z):
        return _ensure_no_floating_islands(mesh)

    if depth >= max_depth:
        logger.warning(
            "fit_to_plate atingiu profundidade máxima (%d >= %d) para peça com extents=%s.",
            depth,
            max_depth,
            extents,
        )
        return _ensure_no_floating_islands(mesh)

    # Passo 1 (depth=0): Em peças grandes/complexas que estouram em múltiplos eixos,
    # destacar apêndices (Asas, Cauda) nas juntas usando corte localizado antes de bisseccionar o tronco
    detached_results: list[trimesh.Trimesh] = []
    oversized_axes_count = sum(
        1 for e, p in zip(extents, (plate_x, plate_y, plate_z)) if e > p
    )
    if depth == 0 and len(mesh.faces) >= 15000 and oversized_axes_count >= 2:
        mesh, detached = _try_anatomical_appendage_split(
            mesh,
            plate_x,
            plate_y,
            plate_z,
            generate_connectors=generate_connectors,
            connector_tolerance_mm=connector_tolerance_mm,
            connector_pin_shape=connector_pin_shape,
        )
        for dp in detached:
            dp_lbl = dp.metadata.get("label", "Apêndice")
            dp_pins = dp.metadata.get("pins_created", 0)
            sub_dp = fit_to_plate(
                dp,
                plate_x,
                plate_y,
                plate_z,
                generate_connectors=generate_connectors,
                connector_tolerance_mm=connector_tolerance_mm,
                connector_pin_shape=connector_pin_shape,
                depth=depth + 1,
                max_depth=max_depth,
            )
            if len(sub_dp) == 1:
                sub_dp[0].metadata["label"] = dp_lbl
                sub_dp[0].metadata.setdefault("pins_created", dp_pins)
            else:
                for k, s in enumerate(sub_dp, start=1):
                    s.metadata["label"] = f"{dp_lbl} ({k})"
            detached_results.extend(sub_dp)

        mesh = _orient_piece_to_fit_if_needed(mesh, plate_x, plate_y, plate_z)
        if _fits_plate(mesh.extents, plate_x, plate_y, plate_z):
            return _ensure_no_floating_islands(mesh) + detached_results

    # Passo 2: Escolher o melhor plano de bisseção (com lookahead de encaixe + prioridade horizontal no tronco)
    max_axis, best_pos, lbl_top, lbl_bot = _choose_best_bisection_plane(
        mesh, plate_x, plate_y, plate_z, depth
    )
    axis_names = ["X", "Y", "Z"]

    normal = [0.0, 0.0, 0.0]
    normal[max_axis] = 1.0
    origin = [0.0, 0.0, 0.0]
    origin[max_axis] = best_pos

    cut_plane = CutPlaneInput(
        normal=normal,
        origin=origin,
        label=f"Bisseção {axis_names[max_axis]}-{depth+1}",
    )

    sub_meshes = cut_mesh_by_planes(
        mesh,
        [cut_plane],
        generate_connectors=generate_connectors,
        connector_tolerance_mm=connector_tolerance_mm,
        connector_pin_shape=connector_pin_shape,
    )

    if not sub_meshes or len(sub_meshes) <= 1:
        logger.warning("Split no eixo %s não gerou mais de 1 peça válida; interrompendo recursão.", axis_names[max_axis])
        return _ensure_no_floating_islands(mesh) + detached_results

    labels_pair = [lbl_top, lbl_bot]
    result: list[trimesh.Trimesh] = []

    for idx, m in enumerate(sub_meshes):
        if len(m.vertices) < 4 or len(m.faces) < 20:
            continue

        lbl = labels_pair[idx] if idx < len(labels_pair) else f"Parte {axis_names[max_axis]}_{idx+1}"
        m_pins = m.metadata.get("pins_created", 0)
        m.metadata["label"] = lbl

        if m.extents[max_axis] >= mesh.extents[max_axis] * 0.98:
            logger.warning("Corte não reduziu significativamente o eixo %s; parando recursão nesta sub-peça.", axis_names[max_axis])
            for item in _ensure_no_floating_islands(m):
                item.metadata.setdefault("pins_created", m_pins)
                result.append(item)
        else:
            sub_res = fit_to_plate(
                m,
                plate_x,
                plate_y,
                plate_z,
                generate_connectors=generate_connectors,
                connector_tolerance_mm=connector_tolerance_mm,
                connector_pin_shape=connector_pin_shape,
                depth=depth + 1,
                max_depth=max_depth,
            )
            if len(sub_res) == 1:
                sub_res[0].metadata["label"] = lbl
                sub_res[0].metadata.setdefault("pins_created", m_pins)
            result.extend(sub_res)

    final_pieces = result + detached_results
    return final_pieces if final_pieces else [mesh]
