import sys, time
sys.path.insert(0, __file__.rsplit("scripts", 1)[0])
import numpy as np
import trimesh
from scipy import ndimage as ndi
from app.mesh.color_splitter import parse_3mf_colors
from app.mesh.capper import close_color_piece

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\Fabricio\Downloads\Modelos 3D\charizard_cores.3mf"
ext = int(sys.argv[2]) if len(sys.argv) > 2 else 0
r = parse_3mf_colors(path)
p = [q for q in r.pieces if q.extruder_index == ext][0]
c = close_color_piece(p.mesh)
pitch = 1.0
t = time.time()
n = int(c.area / (pitch * pitch) * 6)
pts, _ = trimesh.sample.sample_surface(c, n)
pts = np.vstack([pts, c.vertices])
pad = 6
origin = c.bounds[0] - pad * pitch
idx = np.floor((pts - origin) / pitch).astype(int)
shape = idx.max(0) + pad + 1
shell = np.zeros(shape, bool)
shell[idx[:, 0], idx[:, 1], idx[:, 2]] = True
print("shell", shell.sum(), time.time() - t)
for k in [1, 2, 3, 4]:
    d = ndi.binary_dilation(shell, iterations=k)
    lab, nl = ndi.label(~d)
    ext_lab = lab[0, 0, 0]
    exterior = lab == ext_lab
    solid = ~ndi.binary_dilation(exterior, iterations=k)
    print("k", k, "solid", solid.sum(), "interior comps", nl, time.time() - t)
S = solid
dt = ndi.distance_transform_edt(S)
print("dt max", dt.max())
for rad in [3, 4, 5, 6, 8, 10, 12]:
    core = dt > rad
    core = ndi.binary_dilation(core, iterations=rad) & S
    lab, nn = ndi.label(core)
    sizes = ndi.sum(core, lab, range(1, nn + 1))
    out = [(int(sizes[i]), (np.array(ndi.center_of_mass(core, lab, i + 1)) * pitch + origin).round(0).tolist()) for i in np.argsort(-sizes)[:6] if sizes[i] > 200]
    rest = S & ~core
    lab2, n2 = ndi.label(rest)
    s2 = ndi.sum(rest, lab2, range(1, n2 + 1))
    out2 = [(int(s2[i]), (np.array(ndi.center_of_mass(rest, lab2, i + 1)) * pitch + origin).round(0).tolist()) for i in np.argsort(-s2)[:8] if s2[i] > 200]
    print(rad, "core", out, "\n   rest", out2)
