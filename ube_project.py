# UBE Tailor - Copyright (C) 2026 Desertravel. Licensed under the GNU GPL v3 or later (see LICENSE).
"""Generate real UBE BodySlide projects for 3BA/CBBE outfits (step 1: nif with the UBE body added).

add_ube_body(src, dst): copies the outfit nif (all blocks kept by nifly) and adds the UBE base body
shape "BaseShape" from UBE SE 2.0 Release Body.nif with its skin, bones, weights, partitions and shader.
"""
import ctypes
import os

from nifly_env import NifFile
import ube_field



def _copy_struct(buf):
    new = type(buf)()
    ctypes.pointer(new)[0] = buf
    return new


def add_ube_body(src, dst, shape_name="BaseShape"):
    return add_ube_refs(src, dst, [ube_field.parts()[0][2]])


def add_ube_refs(src, dst, ref_nifs, rename=None):
    """Copy outfit nif src -> dst, renaming shapes in `rename` {old: new} and adding the first shape of
    each UBE reference nif (body / feet / hands) under its own name."""
    nif = NifFile(src)
    for old, newname in (rename or {}).items():
        sh = nif.shape_dict[old]
        sh.name = newname
        sh.write_properties()
    for ref in ref_nifs:
        _copy_shape(NifFile(ref), nif)
    nif.filepath = dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    nif.save()
    return dst


def _copy_shape(ube, nif):
    b = ube.shapes[0]
    shape_name = b.name
    if shape_name in nif.shape_dict:
        raise ValueError(f"target already has a {shape_name} shape")
    new = nif.createShapeFromData(shape_name, b.verts, b.tris, b.uvs, b.normals,
                                  props=_copy_struct(b.properties), parent=nif.rootNode)
    new.skin()
    new.set_global_to_skin(b.global_to_skin)
    for bone in b.bone_names:
        node = ube.nodes.get(bone)
        parent = node.parent.name if node is not None and node.parent is not None else None
        xf = node.transform if node is not None else None
        new.add_bone(bone, xf, parent if parent and parent != ube.rootNode.name else None)
    weights = b.bone_weights
    for bone in b.bone_names:
        new.set_skin_to_bone_xform(bone, b.get_shape_skin_to_bone(bone))
        new.setShapeWeights(bone, weights.get(bone, []))
    sh = new.shader
    sh._properties = _copy_struct(b.shader.properties)
    sh.name = b.shader.name or ""
    new.save_shader_attributes()
    for slot, path in b.textures.items():
        if path:
            new.set_texture(slot, path)
    if b.partitions:
        new.set_partitions(b.partitions, b.partition_tris)
