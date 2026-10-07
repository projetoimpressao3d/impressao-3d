import sys, time
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
from app.mesh.color_splitter import parse_3mf_colors
from app.mesh.capper import close_color_piece
import manifold3d as m3d
import numpy as np

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Fabricio\Downloads\Modelos 3D\charizard_cores.3mf"
t = time.time()
r = parse_3mf_colors(path)
print("parse", time.time() - t)
for p in r.pieces:
    print(p.extruder_index, p.filament.color_hex, len(p.mesh.faces), p.mesh.extents, p.mesh.is_watertight, len(p.sub_meshes or []))
    t = time.time()
    c = close_color_piece(p.mesh)
    mm = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(c.vertices, np.float32), tri_verts=np.asarray(c.faces, np.uint32)))
    print("  capped wt", c.is_watertight, "manifold", mm.status(), "nfaces", len(c.faces), "bounds", c.bounds.round(1).tolist(), time.time() - t)
