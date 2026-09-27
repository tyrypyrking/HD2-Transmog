#!/usr/bin/env python3
"""Decode a pinned plaintext FileDiver mirror, never installed/encrypted game data.

The current typelib is stripped of member names. Member positions and types are
checked against the typelib; names are corroborated by FileDiver's parsers and
the historical named JSON. This is a catalog reference, never ownership proof.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "bf0ce329db3cf0043994eb717ea86433c303cb36"
KIT = 0xD9A55AA0
PASSIVE = 0x63CE0FEB


def dlsum(name):
    value = 5381
    for char in name:
        value = (value * 33 + ord(char)) & 0xFFFFFFFF
    return (value - 5381) & 0xFFFFFFFF


def unpack(fmt, data, offset=0):
    if offset < 0 or offset + struct.calcsize(fmt) > len(data):
        raise ValueError("truncated or out-of-bounds data")
    return struct.unpack_from(fmt, data, offset)


def typelib(data):
    magic, version, nt, ne, nm, nv, na, ds, ss = unpack("<4s8I", data)
    if magic != b"LTLD" or version != 4 or max(nt, ne, nm, nv, na) > 100000:
        raise ValueError("unsupported typelib")
    at = 36
    hashes = unpack("<" + "I" * nt, data, at)
    at += 4 * (nt + ne)
    descs = [unpack("<9I", data, at + i * 36) for i in range(nt)]
    at += nt * 36 + ne * 32
    members = [unpack("<18I", data, at + i * 72) for i in range(nm)]
    at += nm * 72 + nv * 16 + na * 8 + ds + ss
    if at != len(data):
        raise ValueError("typelib section size mismatch")
    result = {}
    for key, desc in zip(hashes, descs):
        if desc[7] + desc[6] > nm or key in result:
            raise ValueError("invalid type member range")
        result[key] = {"size": desc[3], "members": [
            {"offset": m[10], "size": m[6], "type": m[4], "flags": m[3]}
            for m in members[desc[7]:desc[7] + desc[6]]
        ]}
    return result


def validate_schema(types):
    expected = {
        "HelldiverCustomizationKit": (64, [(0,4),(4,4),(8,4),(12,4),(16,4),(20,4),(24,4),(28,4),(32,8),(40,4),(48,16)]),
        "HelldiverBodyTypePieces": (24, [(0,4),(8,16)]),
        "HelldiverCustomizationPieceInfo": (96, [(0,8),(8,4),(12,4),(16,4),(24,8),(32,8),(40,8),(48,8),(56,8),(64,8),(72,8),(80,8),(88,1)]),
        "HelldiverCustomizationPassiveBonusSettings": (56, [(0,4),(4,4),(8,8),(16,16),(32,16),(48,4)]),
        "HelldiverCustomizationPassiveBonusModifier": (16, [(0,4),(4,4),(8,4),(12,4)]),
        "HelldiverCustomizationStatModifier": (12, [(0,4),(4,4),(8,4)]),
    }
    result = {}
    for name, (size, fields) in expected.items():
        desc = types.get(dlsum(name))
        if not desc or desc["size"] != size or [(m["offset"],m["size"]) for m in desc["members"]] != fields:
            raise ValueError("unrecognized schema for " + name)
        result[name] = {"type_hash": f"{dlsum(name):08x}", **desc}
    for name, member, target in (("HelldiverCustomizationKit",10,"HelldiverBodyTypePieces"),
                                ("HelldiverBodyTypePieces",1,"HelldiverCustomizationPieceInfo"),
                                ("HelldiverCustomizationPassiveBonusSettings",3,"HelldiverCustomizationPassiveBonusModifier"),
                                ("HelldiverCustomizationPassiveBonusSettings",4,"HelldiverCustomizationStatModifier")):
        desc = result[name]["members"][member]
        if desc["type"] != dlsum(target) or desc["flags"] != 0x1401:
            raise ValueError("array type mismatch")
    return result


def blocks(data, type_hash, maximum=4096):
    count, = unpack("<I", data)
    if not 0 < count <= maximum:
        raise ValueError("record count out of bounds")
    at = 4
    for _ in range(count):
        magic, version, kind, size, wide = unpack("<4sIIIB7x", data, at)
        if magic != b"LDLD" or version != 1 or kind != type_hash or wide != 1 or not 0 < size <= 1048576:
            raise ValueError("invalid LDLD record")
        at += 24
        if at + size > len(data):
            raise ValueError("truncated LDLD record")
        yield data[at:at+size]
        at += size
    if at != len(data):
        raise ValueError("trailing LDLD data")


def array(data, offset, item_size, maximum):
    start, count = unpack("<qQ", data, offset)
    if count > maximum or (count and (start < 0 or start + count * item_size > len(data))):
        raise ValueError("array bounds rejected")
    return [data[start+i*item_size:start+(i+1)*item_size] for i in range(count)]


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def parse_passives(data):
    result = {}
    for record in blocks(data, PASSIVE, 256):
        key, name, icon = unpack("<IIQ", record)
        modifiers = array(record, 16, 16, 64)
        stats = array(record, 32, 12, 64)
        if key in result or len(record) < 56:
            raise ValueError("duplicate or invalid passive")
        # Include exact modifier bytes and trailing behavior tag; not UI enum order.
        effect_bytes = b"".join(modifiers) + b"|" + b"".join(stats) + record[48:52]
        result[key] = {"enum": key, "name_loc": name, "icon": f"{icon:016x}",
            "variant_id": "passive:" + fingerprint(effect_bytes)[:32],
            "modifiers": [dict(zip(("modifier_id","type","value","description_loc"), unpack("<IIfI", item))) for item in modifiers],
            "stat_modifiers": [dict(zip(("stat","add_value","mul_value"), unpack("<Iff", item))) for item in stats],
            "behavior_tag": unpack("<I", record, 48)[0],
            "raw_modifiers": [item.hex() for item in modifiers], "raw_stat_modifiers": [item.hex() for item in stats]}
    return result


def parse_kits(data, passives):
    result = {}
    for record in blocks(data, KIT):
        values = unpack("<8IQI", record)
        key, dlc, group, upper, cased, desc, rarity, passive, package, category = values
        if key == 0 or key in result or category not in (0,1,2) or passive not in passives:
            raise ValueError("invalid kit identity/category/passive")
        bodies = []
        for body in array(record, 48, 24, 8):
            kind, = unpack("<I", body)
            start, count = unpack("<qQ", body, 8)
            if kind > 3 or count > 64 or (count and (start < 0 or start + count * 96 > len(record))):
                raise ValueError("body piece bounds rejected")
            pieces = []
            for i in range(count):
                piece = record[start+i*96:start+(i+1)*96]
                path, slot, ptype, weight = unpack("<QIII", piece)
                if slot > 9 or ptype > 2 or weight > 2:
                    raise ValueError("invalid piece enums")
                pieces.append({"path":f"{path:016x}","slot":slot,"type":ptype,"weight":weight,"raw":piece.hex()})
            bodies.append({"type":kind,"pieces":pieces})
        result[key] = {"id":f"armor:{key:08x}","item_id":key,"dlc_id":dlc,"set_id":group,
            "name_upper":upper,"name_cased":cased,"description_loc":desc,"rarity":rarity,
            "passive_enum":passive,"passive_variant_id":passives[passive]["variant_id"],
            "package":f"{package:016x}","category":category,"bodies":bodies,
            "header":record[:44].hex(),"stats":None,
            "stats_status":"not_present_in_kit_record; native derivation unverified"}
    return result


def lua(value):
    if value is None: return "nil"
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, str): return json.dumps(value, ensure_ascii=True)
    if isinstance(value, (int,float)): return repr(value)
    if isinstance(value, list): return "{" + ",".join(lua(x) for x in value) + "}"
    return "{" + ",".join("[" + lua(k) + "]=" + lua(v) for k,v in value.items()) + "}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT/".cache/catalog-reference")
    parser.add_argument("--json", type=Path, default=ROOT/"reference/current_catalog.json")
    parser.add_argument("--lua", type=Path, default=ROOT/"src/catalog_data.lua")
    args = parser.parse_args()
    names = ("dl_library.dl_typelib","generated_customization_armor_sets.dl_bin","generated_customization_passive_bonuses.dl_bin")
    source = {name:(args.source/name).read_bytes() for name in names}
    schemas = validate_schema(typelib(source[names[0]]))
    passives = parse_passives(source[names[2]])
    kits = parse_kits(source[names[1]], passives)
    output = {"schema_version":1,"source_commit":COMMIT,"runtime_verified":False,
        "source_sha256":{name:fingerprint(data) for name,data in source.items()},
        "types":schemas,"kits":kits,"passives":passives}
    args.json.write_text(json.dumps(output, indent=2)+"\n")
    # Ship facts only; preserve source values and full piece bytes for exact comparison.
    compact = {"source_commit":COMMIT,"kits":kits,"passives":passives,"types":schemas}
    args.lua.write_text("-- Generated by tools/armor_catalog.py; reference facts, never ownership.\nreturn " + lua(compact)+"\n")
    print(json.dumps({"kits":len(kits),"armors":sum(k["category"]==0 for k in kits.values()),"passives":len(passives),"json":str(args.json),"lua":str(args.lua)}))


if __name__ == "__main__":
    main()
