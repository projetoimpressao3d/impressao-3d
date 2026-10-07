with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """        if not sub_meshes:
            logger.warning("Corte resultou em 0 peças; mantendo peça original da cor")
            sub_meshes = [target_piece.mesh]"""

replacement = """        if not sub_meshes:
            logger.warning("Corte resultou em 0 peças; mantendo peça original da cor")
            sub_meshes = [target_piece.mesh]
            
        from app.mesh.fit_to_plate import fit_to_plate
        final_sub_meshes = []
        for sm in sub_meshes:
            # Check and orient first? The requirements say:
            # "Se uma peça não couber na mesa após orientá-la, dividi-la recursivamente"
            # It already orientation? The requirements just say to split it horizontally.
            final_sub_meshes.extend(fit_to_plate(sm, plate_x, plate_y, plate_z))
        sub_meshes = final_sub_meshes"""

content = content.replace(target, replacement)

with open("C:/Users/Fabricio/Downloads/projeto-impressao-3d/apps/mesh-service/app/routers/color_split.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Done")
