with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/mesh/cutter.py", "r", encoding="utf-8") as f:
    content = f.read()

target1 = """    valid_pieces = [p for p in accumulated if len(p.vertices) > 0 and len(p.faces) > 0]
    return valid_pieces if valid_pieces else [mesh]"""

replacement1 = """    valid_pieces = [p for p in accumulated if len(p.vertices) > 0 and len(p.faces) > 0]
    if not valid_pieces:
        raise RuntimeError("Fatiador trimesh falhou: Corte resultou em 0 peças válidas.")
    return valid_pieces"""

content = content.replace(target1, replacement1)

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/mesh/cutter.py", "w", encoding="utf-8") as f:
    f.write(content)

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "r", encoding="utf-8") as f:
    content = f.read()

target2 = """        if not sub_meshes:
            logger.warning("Corte resultou em 0 peças; mantendo peça original da cor")
            sub_meshes = [target_piece.mesh]"""

replacement2 = """        if not sub_meshes:
            raise RuntimeError("O corte não gerou peças.")"""

content = content.replace(target2, replacement2)

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
