"""
Testes para o modulo skeleton.py - deteccao de candidatos estruturais de corte.
Secao 6.4.1 do AGENTS.md.
"""
import types
import networkx as nx
import numpy as np
import pytest
import trimesh

from app.mesh.skeleton import (
    DEFAULT_SENSITIVITY,
    StructuralCutPlane,
    _estimate_appendage_volume,
    _find_branch_and_endpoints,
    _find_branches,
    find_structural_candidates,
)


# ---------------------------------------------------------------------------
# Helpers para criar esqueleto sintetico (sem precisar rodar skeletor)
# ---------------------------------------------------------------------------


def make_star_skel(n_arms: int = 3) -> object:
    """Cria um esqueleto sintetico em estrela com n_arms bracos."""
    G = nx.Graph()
    arm_len = 20.0
    vertices = [np.array([0.0, 0.0, 0.0])]
    for i in range(n_arms):
        angle = 2 * np.pi * i / n_arms
        tip = np.array([arm_len * np.cos(angle), arm_len * np.sin(angle), 0.0])
        vertices.append(tip)
        G.add_edge(0, i + 1)

    skel = types.SimpleNamespace(
        vertices=np.array(vertices),
        edges=list(G.edges()),
    )
    skel.get_graph = lambda: G
    return skel


class TestFindBranchAndEndpoints:
    def test_linear_graph_has_no_branches(self) -> None:
        G = nx.Graph()
        G.add_edges_from([(0, 1), (1, 2)])
        branches, endpoints = _find_branch_and_endpoints(G)
        assert branches == []
        assert sorted(endpoints) == [0, 2]

    def test_star_graph_has_one_branch_node(self) -> None:
        G = nx.Graph()
        G.add_edges_from([(0, 1), (0, 2), (0, 3)])
        branches, endpoints = _find_branch_and_endpoints(G)
        assert 0 in branches
        assert len(endpoints) == 3

    def test_y_shape_graph(self) -> None:
        G = nx.Graph()
        G.add_edges_from([(0, 1), (1, 2), (2, 3), (2, 4)])
        branches, endpoints = _find_branch_and_endpoints(G)
        assert 2 in branches
        assert set(endpoints) == {0, 3, 4}


class TestFindBranches:
    def test_star_graph_three_branches(self) -> None:
        G = nx.Graph()
        G.add_edges_from([(0, 1), (0, 2), (0, 3)])
        bs = _find_branches(G, [0], [1, 2, 3])
        assert len(bs) == 3

    def test_linear_graph_one_branch(self) -> None:
        G = nx.Graph()
        G.add_edges_from([(0, 1), (1, 2)])
        bs = _find_branches(G, [], [0, 2])
        assert len(bs) >= 1


class TestEstimateAppendageVolume:
    def test_center_cut_has_nonzero_volume(self) -> None:
        sphere = trimesh.creation.icosphere(radius=10.0)
        origin = np.array([0.0, 0.0, 0.0])
        normal = np.array([1.0, 0.0, 0.0])
        vol = _estimate_appendage_volume(sphere, origin, normal)
        assert vol > 0

    def test_far_plane_gives_zero(self) -> None:
        sphere = trimesh.creation.icosphere(radius=5.0)
        origin = np.array([100.0, 0.0, 0.0])
        normal = np.array([1.0, 0.0, 0.0])
        vol = _estimate_appendage_volume(sphere, origin, normal)
        assert vol == 0.0


class TestFindStructuralCandidates:
    def setup_method(self) -> None:
        self.mesh = trimesh.creation.icosphere(radius=10.0)
        self.skel = make_star_skel(n_arms=3)

    def test_sensitivity_zero_returns_all(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=0.0)
        assert isinstance(candidates, list)

    def test_sensitivity_one_filters_all(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=1.0)
        assert candidates == []

    def test_candidates_have_required_fields(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=0.0)
        for cp in candidates:
            assert isinstance(cp, StructuralCutPlane)
            assert len(cp.normal) == 3
            assert len(cp.origin) == 3
            assert cp.source == "suggested_structural"
            assert cp.structural_group.startswith("branch-")
            assert 0.0 <= cp.appendage_volume_ratio <= 1.0

    def test_default_sensitivity_filters_near_zero_ratios(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=DEFAULT_SENSITIVITY)
        for cp in candidates:
            assert cp.appendage_volume_ratio >= DEFAULT_SENSITIVITY

    def test_candidates_sorted_by_volume_descending(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=0.0)
        if len(candidates) >= 2:
            for a, b in zip(candidates, candidates[1:]):
                assert a.appendage_volume_ratio >= b.appendage_volume_ratio

    def test_structural_group_label(self) -> None:
        candidates = find_structural_candidates(self.skel, self.mesh, sensitivity=0.0)
        for cp in candidates:
            assert cp.structural_group.startswith("branch-")
