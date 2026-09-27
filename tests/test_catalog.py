"""Catalog format/race/ownership tests using synthetic memory, never the game."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("armor_catalog", ROOT/"tools/armor_catalog.py")
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)
DATA = json.loads((ROOT/"reference/current_catalog.json").read_text())


def test_catalog_has_current_exact_bundles_without_ownership_or_stats_inference():
    assert len(DATA["kits"]) == 411
    assert sum(kit["category"] == 0 for kit in DATA["kits"].values()) == 135
    assert len(DATA["passives"]) == 32
    assert not DATA["runtime_verified"]
    assert all(kit["stats"] is None and "owned" not in kit for kit in DATA["kits"].values())
    assert all(p["variant_id"].startswith("passive:") for p in DATA["passives"].values())


@pytest.mark.parametrize("bad", [b"", struct.pack("<I",4097),struct.pack("<I",1)+b"X"*24])
def test_rejects_invalid_binary(bad):
    with pytest.raises(ValueError):
        list(catalog.blocks(bad,catalog.KIT))


def test_schema_rejects_member_drift():
    types={int(desc["type_hash"],16):desc for desc in DATA["types"].values()}
    catalog.validate_schema(types)
    types=catalog.json.loads(catalog.json.dumps(types))
    types={int(k):v for k,v in types.items()}
    types[catalog.KIT]["members"][10]["offset"]=40
    with pytest.raises(ValueError,match="unrecognized schema"):
        catalog.validate_schema(types)


def lua_bytes(value):
    return '"'+''.join(f'\\{byte:03d}' for byte in value)+'"'


def fixture_script(mutation="", status=2, disabled=0, post_ready="", live_passives=False):
    selected=[kit for kit in DATA["kits"].values() if kit["category"]==0][:2]
    reference={"source_commit":"fixture","kits":{k["item_id"]:k for k in selected},
               "passives":{int(k):v for k,v in DATA["passives"].items()}}
    segments=[]
    def put(at,value): segments.append((at,value))
    def p(n): return struct.pack("<Q",n)
    put(0x10000,p(0x20000)); put(0x10008,p(0x40000))
    put(0x20000,p(0x21000)+struct.pack("<I",2))
    put(0x21000,p(0x22000)+p(0x23000))
    if live_passives:
        entries=list(reference["passives"].items())
        put(0x20020,p(0xB00000)+struct.pack("<I",len(entries)))
        index_map=bytearray(b"\xff"*(4*(max(reference["passives"])+1)))
        pointers=[]
        for index,(enum,passive)in enumerate(entries):
            struct.pack_into("<I",index_map,enum*4,index)
            at=0xB10000+index*0x1000;pointers.append(p(at))
            mods=b"".join(bytes.fromhex(x)for x in passive["raw_modifiers"])
            stats=b"".join(bytes.fromhex(x)for x in passive["raw_stat_modifiers"])
            raw=struct.pack("<IIQQQQQI4x",enum,passive["name_loc"],int(passive["icon"],16),
                            at+128,len(mods)//16,at+512,len(stats)//12,passive["behavior_tag"])
            put(at,raw)
            if mods:put(at+128,mods)
            if stats:put(at+512,stats)
        put(0x20030,bytes(index_map));put(0xB00000,b"".join(pointers))
    next_piece=0x200000
    for i,kit in enumerate(selected):
        body_at=0x24000+i*0x1000
        raw=bytes.fromhex(kit["header"])+b"\0"*4+p(body_at)+p(len(kit["bodies"]))
        put(0x22000+i*0x1000,raw)
        for j,body in enumerate(kit["bodies"]):
            put(body_at+j*24,struct.pack("<IIQQ",body["type"],0,next_piece,len(body["pieces"])))
            piecebytes=b"".join(bytes.fromhex(k["raw"]) for k in body["pieces"])
            if piecebytes: put(next_piece,piecebytes)
            next_piece+=0x10000
    progression=bytearray(0xB9CE4+2*24)
    struct.pack_into("<I",progression,0x1CE0,2)
    for i,kit in enumerate(selected):
        struct.pack_into("<III",progression,0xB9CE4+i*24,i,0,kit["item_id"])
        struct.pack_into("<I",progression,0x1CE4+i*184+0x14,status if i==0 else 1)
        progression[0x1CE4+i*184+0xB4]=disabled if i==0 else 0
    put(0x40000,bytes(progression))
    # Avoid embedding a 760KB escaped zero string in every test.
    statements=[]
    for at,raw in segments:
        if at==0x40000:
            statements.append(f"put({at},string.rep('\\0',{len(raw)}))")
            for offset in [0x1CE0,0x1CE4+0x14,0x1CE4+0xB4,0x1CE4+184+0x14,0x1CE4+184+0xB4,0xB9CE4,0xB9CE4+24]:
                length=12 if offset>=0xB9CE4 else 4 if offset not in (0x1CE4+0xB4,0x1CE4+184+0xB4) else 1
                statements.append(f"patch({at+offset},{lua_bytes(raw[offset:offset+length])})")
        else: statements.append(f"put({at},{lua_bytes(raw)})")
    return f"""
local probe=dofile({json.dumps(str(ROOT/'src/catalog_probe.lua'))})
local data={catalog.lua(reference)}
local memory={{}}
local function put(at,value)memory[#memory+1]={{at=at,value=value}}end
local function patch(at,value)
 for _,m in ipairs(memory)do if at>=m.at and at+#value<=m.at+#m.value then
  local o=at-m.at;m.value=m.value:sub(1,o)..value..m.value:sub(o+#value+1);return
 end end
 error('bad fixture patch')
end
{chr(10).join(statements)}
local calls,read_bytes=0,0
local function read(at,n)
 calls=calls+1;read_bytes=read_bytes+n
 for _,m in ipairs(memory)do if at>=m.at and at+n<=m.at+#m.value then return m.value:sub(at-m.at+1,at-m.at+n)end end
 local pieces={{}};local cursor=at
 while cursor<at+n do
  local part
  for _,m in ipairs(memory)do if cursor>=m.at and cursor<m.at+#m.value then
   part=m.value:sub(cursor-m.at+1,math.min(at+n,m.at+#m.value)-m.at);break
  end end
  if not part then return nil end
  pieces[#pieces+1]=part;cursor=cursor+#part
 end
 return table.concat(pieces)
end
local bridge={{read=read,armor_catalog=0x10000,progression=0x10008,verify=function()return true end}}
{mutation}
local observer=probe.new(bridge,data)
local phase,result,frames
for i=1,10000 do
 local before,bytes_before=calls,read_bytes;phase,result=observer:step()
 assert(calls-before<=64,'frame read count budget exceeded')
 assert(read_bytes-bytes_before<=65536,'frame byte budget exceeded');frames=i
 if phase~='resolving'then break end
end
if phase=='ready'then
 {post_ready}
 print('ready '..result.counts.owned_armors..' '..tostring(result.capabilities.numeric_stats_verified)..' '..tostring(result.capabilities.exact_passive_effects_verified))
else print('failed '..tostring(result))end
"""


def run_fixture(tmp_path, **kwargs):
    luajit=shutil.which("luajit")
    if not luajit: pytest.skip("LuaJIT unavailable")
    script=tmp_path/"catalog_fixture.lua"
    script.write_text(fixture_script(**kwargs))
    proc=subprocess.run([luajit,str(script)],capture_output=True,text=True,timeout=10)
    assert proc.returncode==0,proc.stderr
    return proc.stdout


def test_effect_display_strips_native_color_tags_without_modifying_effect_data(tmp_path):
    mutation=r'''
local tested_passive,tested_effect
for _,kit in pairs(data.kits)do
 local passive=data.passives[kit.passive_enum]
 if #passive.modifiers>0 then tested_passive=passive;tested_effect=passive.modifiers[1];break end
end
assert(tested_effect)
local original_value,original_type=tested_effect.value,tested_effect.type
local original_raw=tested_passive.raw_modifiers[1]
bridge.localize=function(loc)
 if loc==tested_effect.description_loc then return 'Armor <c=#COLOR>#SIGN#BONUS</c> / <C=#ffffff>plain</C> <unknown> 4 < 8'end
 return nil
end
'''
    post=r'''
local metadata=result.context.passive_variants[tested_passive.variant_id]
local shown=result.context.details.passive_variant_id[tested_passive.variant_id][1]
assert(not shown:find('<c=',1,true)and not shown:find('</c>',1,true)and not shown:find('<C=',1,true))
assert(not shown:find('#BONUS',1,true)and not shown:find('#SIGN',1,true))
assert(shown:find(' / plain <unknown> 4 < 8',1,true))
assert(metadata.effects[1]==shown and metadata.modifiers==tested_passive.modifiers)
assert(tested_effect.value==original_value and tested_effect.type==original_type)
assert(tested_passive.raw_modifiers[1]==original_raw)
'''
    assert run_fixture(tmp_path,mutation=mutation,post_ready=post).startswith('ready 1')


@pytest.mark.parametrize("status,disabled,expected",[(2,0,1),(4,0,1),(2,1,0),(1,0,0)])
def test_only_fresh_enabled_owned_states_activate(tmp_path,status,disabled,expected):
    assert run_fixture(tmp_path,status=status,disabled=disabled)==f"ready {expected} false false\n"


@pytest.mark.parametrize("mutation,reason",[
    ("patch(0x40000+0xb9ce4,string.char(9,0,0,0))","index rejected"),
    ("bridge.verify=function()return false end","compatibility evidence changed"),
])
def test_rejects_mutated_schema_or_identity(tmp_path,mutation,reason):
    output=run_fixture(tmp_path,mutation=mutation)
    assert output.startswith("failed ") and reason in output


def test_reread_detects_ownership_race(tmp_path):
    mutation="""local base_read=bridge.read;local visits=0
bridge.read=function(at,n)
 local result=base_read(at,n)
 if at==0x40000+0x1ce4+0x14 then
  visits=visits+1;if visits==2 then return string.char(1,0,0,0)end
 end
 return result
end"""
    assert "changed during observation" in run_fixture(tmp_path,mutation=mutation)


def test_native_passive_map_and_exact_effect_bundles_are_verified(tmp_path):
    post="""
local n=0
for id,p in pairs(result.passives)do
 n=n+1
 if result.context.passive_variants[id]then
  assert(result.context.passive_variants[id].live_effects_verified)
  assert(result.context.passive_variants[id].icon_hash==p.reference.icon)
 end
end
assert(n==32 and result.capabilities.exact_passive_effects_verified)
"""
    assert run_fixture(tmp_path,live_passives=True,post_ready=post)=="ready 1 false true\n"


def test_changed_optional_passive_bundle_does_not_revoke_valid_owned_kit_data(tmp_path):
    post="assert(not result.capabilities.exact_passive_effects_verified and next(result.passives)==nil)"
    mutation="patch(0xB10000+128+8,string.char(0,0,0,0))"
    assert run_fixture(tmp_path,live_passives=True,mutation=mutation,post_ready=post)=="ready 1 false false\n"


def test_application_closures_recheck_only_fresh_owned_donors(tmp_path):
    owned=next(k["id"] for k in DATA["kits"].values() if k["category"]==0)
    post=f"""
local ids={{{json.dumps(owned)}}}
assert(result.verify_session())
local before=calls;assert(result.verify_owned(ids));assert(calls-before<16)
assert(result.verify_owned({{{json.dumps(owned)},{json.dumps(owned)}}}))
assert(not result.verify_owned({{}}))
assert(not result.verify_owned({{'armor:unknown'}}))
patch(0x40000+0x1ce4+0x14,string.char(1,0,0,0))
assert(not result.verify_owned(ids));assert(result.verify_session())
patch(0x10008,string.rep('\\0',8))
assert(not result.verify_session())
"""
    assert run_fixture(tmp_path,post_ready=post).startswith("ready 1")


@pytest.mark.parametrize("change",[
    "patch(0x40000+0x1ce0,string.char(3,0,0,0))",
    "patch(0x40000+0xb9ce4+8,string.char(0,0,0,0))",
    "patch(0x40000+0x1ce4+0xb4,string.char(1))",
    "bridge.verify=function()return false end",
])
def test_application_closure_rejects_refresh_or_replaced_evidence(tmp_path,change):
    owned=next(k["id"] for k in DATA["kits"].values() if k["category"]==0)
    post=f"{change}\nassert(not result.verify_owned({{{json.dumps(owned)}}}))"
    assert run_fixture(tmp_path,post_ready=post).startswith("ready 1")


@pytest.mark.parametrize('first_status,second_status,second_disabled,qualifying',[
    (2,1,0,0),  # A later locked offer cannot revoke an owned item.
    (1,4,0,1),  # An earlier locked offer cannot hide a later owned offer.
    (2,4,1,0),  # A disabled offer cannot revoke another valid grant.
    (2,4,0,0),  # Keep a concrete qualifying proof when several grants exist.
])
def test_duplicate_item_offers_union_positive_grants_and_keep_fresh_proof(
        tmp_path,first_status,second_status,second_disabled,qualifying):
    first=next(k for k in DATA['kits'].values() if k['category']==0)
    mutation=f"""
patch(0x40000+0xb9ce4+24+8,{lua_bytes(struct.pack('<I',first['item_id']))})
patch(0x40000+0x1ce4+184+0x14,string.char({second_status},0,0,0))
patch(0x40000+0x1ce4+184+0xb4,string.char({second_disabled}))
"""
    post=f"""
local ids={{{json.dumps(first['id'])}}}
assert(result.verify_owned(ids))
-- Changing an unrelated duplicate cannot revoke the retained positive proof.
patch(0x40000+0x1ce4+{1-qualifying}*184+0x14,string.char(1,0,0,0))
assert(result.verify_owned(ids))
-- Losing the exact qualifying evidence forces a fresh full observation.
patch(0x40000+0x1ce4+{qualifying}*184+0x14,string.char(1,0,0,0))
assert(not result.verify_owned(ids) and result.verify_session())
"""
    assert run_fixture(tmp_path,status=first_status,mutation=mutation,post_ready=post).startswith('ready 1')


@pytest.mark.parametrize("mutation,expected",[
    ("", "B-01 Tactical Armor"),
    ("backend.executable=function()return false end", "unavailable"),
    ("bridge.verify=function()return false end", "unavailable"),
    ("text='#ID[123]\\0'", "missing"),
    ("text=string.rep('x',1024)", "missing"),
    ("after=function()memory[0x10000]=p(0x90000)end", "missing"),
])
def test_localization_only_calls_valid_target_and_returns_bounded_text(tmp_path,mutation,expected):
    luajit=shutil.which("luajit")
    if not luajit: pytest.skip("LuaJIT unavailable")
    script=tmp_path/"localization.lua"
    script.write_text(f"""
local L=dofile({json.dumps(str(ROOT/'src/localization.lua'))})
local function p(n)local t={{}};for i=1,8 do t[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(t)end
local text='B-01 Tactical Armor\\0'
local memory={{[0x10000]=p(0x20000),[0x20010]=p(0x30000),[0x303e8]=p(0x40000)}}
local bridge={{engine_root=0x10000,verify=function()return true end}}
bridge.read=function(at,n)
 if memory[at]then return memory[at]:sub(1,n)end
 if at>=0x50000 and at+n<=0x50000+#text then return text:sub(at-0x50000+1,at-0x50000+n)end
end
local backend={{executable=function(at)return at==0x40000 end,lookup=function(at,key)assert(at==0x40000 and key==123);return 0x50000 end}}
local after
{mutation}
local lookup=L.bind(bridge,backend)
if after then after()end
print(lookup and (lookup(123)or 'missing')or 'unavailable')
""")
    proc=subprocess.run([luajit,str(script)],capture_output=True,text=True,timeout=10)
    assert proc.returncode==0,proc.stderr
    assert proc.stdout.strip()==expected


@pytest.mark.parametrize('change,unknown,changed,reason', [
    ("patch(0x22000,string.char(0x98,0xba,0xdc,0xfe))", 1, 0, 'unknown_reference'),
    ("patch(0x22028,string.char(2,0,0,0))", 0, 1, 'header_mismatch'),
    ("patch(0x22038,string.rep('\\0',8))", 0, 1, 'body_count_mismatch'),
    ("patch(0x24000,string.char(2,0,0,0))", 0, 1, 'body_type_mismatch'),
    ("patch(0x24010,string.rep('\\0',8))", 0, 1, 'piece_count_mismatch'),
    ("patch(0x200000,string.rep('x',8))", 0, 1, 'piece_mismatch'),
])
def test_semantic_drift_excludes_only_changed_item_and_never_authorizes_its_ownership(
        tmp_path, change, unknown, changed, reason):
    first, second = [k for k in DATA['kits'].values() if k['category'] == 0][:2]
    # Both donors have positive native ownership; only a validated kit may expose it.
    mutation = change + "\npatch(0x40000+0x1ce4+184+0x14,string.char(2,0,0,0))"
    post = f'''
local rejected,kept={json.dumps(first['id'])},{json.dumps(second['id'])}
assert(result.counts.observed==2 and result.counts.matched==1 and result.counts.unavailable==1)
assert(result.counts.unknown=={unknown} and result.counts.changed=={changed})
assert(not result.records[rejected] and not result.catalog[rejected] and not result.owned[rejected])
assert(not result.context.labels.appearance_id[rejected])
assert(result.records[kept] and result.catalog[kept] and result.owned[kept])
assert(not result.verify_owned({{rejected}}) and result.verify_owned({{kept}}))
assert(#result.diagnostics==1 and result.diagnostics[1].reason=={json.dumps(reason)})
assert(result.diagnostics[1].id:match('^armor:%x+$'))
assert(result.capabilities.numeric_stats_verified==false and result.capabilities.exact_passive_effects_verified==false)
'''
    assert run_fixture(tmp_path, mutation=mutation, post_ready=post) == 'ready 1 false false\n'


def test_added_unknown_kit_does_not_invalidate_known_donors(tmp_path):
    first = next(k for k in DATA['kits'].values() if k['category'] == 0)
    mutation = '''
patch(0x20008,string.char(3,0,0,0))
put(0x21010,string.char(0,0x80,2,0,0,0,0,0))
put(0x28000,string.char(0x98,0xba,0xdc,0xfe)..read(0x22004,60))
-- A positive offer for the unknown item must not grant a selectable donor.
patch(0x40000+0xb9ce4+24+8,string.char(0x98,0xba,0xdc,0xfe))
patch(0x40000+0x1ce4+184+0x14,string.char(2,0,0,0))
'''
    post = f'''
assert(result.counts.observed==3 and result.counts.matched==2 and result.counts.unknown==1)
assert(result.counts.unavailable==1 and result.counts.changed==0 and result.counts.missing_reference==0)
assert(result.verify_owned({{{json.dumps(first['id'])}}}))
assert(not result.catalog['armor:fedcba98'] and not result.owned['armor:fedcba98'])
assert(not result.verify_owned({{'armor:fedcba98'}}))
'''
    assert run_fixture(tmp_path, mutation=mutation, post_ready=post) == 'ready 1 false false\n'


def test_removed_kit_leaves_other_known_donor_available(tmp_path):
    first, second = [k for k in DATA['kits'].values() if k['category'] == 0][:2]
    post = f'''
assert(result.counts.observed==1 and result.counts.matched==1 and result.counts.missing_reference==1)
assert(result.counts.unavailable==0 and result.counts.unknown==0 and result.counts.changed==0)
assert(result.catalog[{json.dumps(first['id'])}] and not result.catalog[{json.dumps(second['id'])}])
'''
    assert run_fixture(tmp_path, mutation="patch(0x20008,string.char(1,0,0,0))", post_ready=post) == 'ready 1 false false\n'


@pytest.mark.parametrize('mutation,reason', [
    ("patch(0x23000,read(0x22000,4))", 'duplicate kit identity'),
    ("patch(0x22000,string.rep('\\0',4))", 'kit identity'),
    ("patch(0x22000,string.char(0x98,0xba,0xdc,0xfe));patch(0x23000,read(0x22000,4))", 'duplicate kit identity'),
    ("patch(0x21000,string.rep('\\0',8))", 'pointer unavailable'),
    ("patch(0x22038,string.char(9,0,0,0))", 'body bounds rejected'),
    ("patch(0x24010,string.char(65,0,0,0))", 'piece bounds rejected'),
    ("patch(0x24008,string.rep('\\0',8))", 'piece pointer unavailable'),
    ("patch(0x22030,string.char(0,0,0,7,0,0,0,0))", 'unreadable'),
    # A semantic mismatch must not mask structural corruption in the same item.
    ("patch(0x22028,string.char(2,0,0,0));patch(0x22030,string.rep('\\0',8))", 'body pointer unavailable'),
    ("patch(0x20008,string.rep('\\0',4))", 'catalog bounds rejected'),
    ("patch(0x40000+0x1ce0,string.rep('\\0',4))", 'progression count rejected'),
    ("patch(0x22028,string.char(2,0,0,0));patch(0x23028,string.char(2,0,0,0))", 'no verified armor records'),
])
def test_structural_corruption_and_empty_verified_subset_still_fail_provider(tmp_path, mutation, reason):
    output = run_fixture(tmp_path, mutation=mutation)
    assert output.startswith('failed ') and reason in output


def test_replaced_selected_array_slot_invalidates_application_proof(tmp_path):
    first = next(k for k in DATA['kits'].values() if k['category'] == 0)
    post = f'''
assert(result.verify_owned({{{json.dumps(first['id'])}}}))
patch(0x21000,read(0x21008,8))
assert(not result.verify_owned({{{json.dumps(first['id'])}}}))
'''
    assert run_fixture(tmp_path, post_ready=post) == 'ready 1 false false\n'


def test_unknown_record_race_still_invalidates_complete_observation(tmp_path):
    mutation = '''
patch(0x22000,string.char(0x98,0xba,0xdc,0xfe))
local base_read=bridge.read;local visits=0
bridge.read=function(at,n)
 local result=base_read(at,n)
 if at==0x22000 and n==64 then
  visits=visits+1
  if visits==2 then return string.char(0x99)..result:sub(2)end
 end
 return result
end
'''
    assert 'changed during observation' in run_fixture(tmp_path, mutation=mutation)


def large_progression_fixture():
    first, second = [kit for kit in DATA['kits'].values() if kit['category'] == 0][:2]
    return f'''
local function packed(n)
 local b={{}};for i=1,4 do b[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(b)
end
local progression=0x500000
put(progression,string.rep('\\0',0xb9ce4+4096*24))
patch(0x10008,packed(progression)..packed(0))
patch(progression+0x1ce0,packed(4096))
local entries={{}}
for i=0,4095 do
 local item=i==0 and {first['item_id']} or i==1 and {second['item_id']} or 0
 entries[#entries+1]=packed(i)..packed(0)..packed(item)..string.rep('\\0',12)
end
patch(progression+0xb9ce4,table.concat(entries))
patch(progression+0x1ce4+0x14,packed(2))
patch(progression+0x1ce4+184+0x14,packed(1))
local probe_start=calls
'''


def test_large_progression_reads_only_relevant_armor_states_with_bounded_batches(tmp_path):
    mutation=large_progression_fixture()+'''
local base_read=bridge.read;local armor_state_reads=0
bridge.read=function(at,n)
 if at>=progression+0x1ce4 and at<progression+0xb9ce4 then
  assert(at==progression+0x1ce4+0x14 or at==progression+0x1ce4+0xb4
   or at==progression+0x1ce4+184+0x14 or at==progression+0x1ce4+184+0xb4,
   'unrelated inventory item state was inspected')
  armor_state_reads=armor_state_reads+1
 end
 return base_read(at,n)
end
'''
    post='''
assert(result.counts.progression==4096 and result.counts.owned_armors==1)
assert(armor_state_reads==8,'armor state freshness was not checked twice')
assert(calls-probe_start<180,'large inventory work grew per unrelated offer')
'''
    assert run_fixture(tmp_path,mutation=mutation,post_ready=post)=='ready 1 false false\n'


@pytest.mark.parametrize('column,changes_evidence',[(0,True),(8,True),(12,False)])
def test_batched_progression_preserves_known_column_race_detection(tmp_path,column,changes_evidence):
    mutation=large_progression_fixture()+f'''
local base_read=bridge.read;local visits=0
local last_batch=progression+0xb9ce4+3968*24
bridge.read=function(at,n)
 local raw=base_read(at,n)
 if at==last_batch then
  visits=visits+1
  if visits==2 then
   local offset=126*24+{column}
   return raw:sub(1,offset)..string.char(1)..raw:sub(offset+2)
  end
 end
 return raw
end
'''
    output=run_fixture(tmp_path,mutation=mutation)
    if changes_evidence:
        assert 'changed during observation' in output
    else:
        assert output=='ready 1 false false\n'


def test_localized_names_and_shared_passive_details_are_cached_per_observation(tmp_path):
    mutation='''
local localizations={};local misses={}
bridge.localize=function(key)
 localizations[key]=(localizations[key]or 0)+1
 assert(localizations[key]==1,'same localized key repeatedly called native lookup')
 if key%2==0 then misses[key]=true;return nil end
 return 'Localized '..tostring(key)
end
'''
    post='''
assert(next(localizations)and next(misses))
for _,kit in pairs(data.kits)do
 local passive=data.passives[kit.passive_enum]
 assert(result.context.labels.appearance_id[kit.id])
 assert(result.context.labels.passive_variant_id[passive.variant_id])
 assert(result.context.passive_variants[passive.variant_id].effects
  ==result.context.details.passive_variant_id[passive.variant_id])
end
'''
    assert run_fixture(tmp_path,mutation=mutation,post_ready=post)=='ready 1 false false\n'


REFRESH_OWNERSHIP = """
local function refresh()
 for i=1,10000 do
  local before,bytes_before=calls,read_bytes
  local phase,value=result.refresh_ownership()
  assert(calls-before<=64,'ownership refresh read budget exceeded')
  assert(read_bytes-bytes_before<=65536,'ownership refresh byte budget exceeded')
  if phase~='resolving'then return phase,value end
 end
 error('ownership refresh did not finish')
end
"""


def test_live_ownership_refresh_unlocks_and_revokes_without_rereading_composed_records(tmp_path):
    first, second = [k['id'] for k in DATA['kits'].values() if k['category'] == 0][:2]
    post = REFRESH_OWNERSHIP + f"""
local catalog_before,records_before,context_before=result.catalog,result.records,result.context
local raw_read=bridge.read
bridge.read=function(at,n)
 assert(not(at>=0x22000 and at<0x26000),'refresh reread mutable kit/body records')
 assert(not(at>=0x200000 and at<0xB00000),'refresh reread mutable pieces')
 return raw_read(at,n)
end
assert(not result.owned[{json.dumps(second)}])
patch(0x40000+0x1ce4+184+0x14,string.char(4,0,0,0))
local phase,changed=refresh();assert(phase=='ready'and changed)
assert(result.owned[{json.dumps(second)}] and result.counts.owned_armors==2)
assert(result.verify_owned({{{json.dumps(second)}}}))
assert(result.catalog==catalog_before and result.records==records_before and result.context==context_before)
phase,changed=refresh();assert(phase=='ready'and not changed)
patch(0x40000+0x1ce4+0x14,string.char(1,0,0,0))
phase,changed=refresh();assert(phase=='ready'and changed)
assert(not result.owned[{json.dumps(first)}] and result.counts.owned_armors==1)
assert(not result.verify_owned({{{json.dumps(first)}}}))
"""
    assert run_fixture(tmp_path, post_ready=post).startswith('ready 1')


def test_live_ownership_refresh_fails_closed_then_retries(tmp_path):
    first = next(k['id'] for k in DATA['kits'].values() if k['category'] == 0)
    post = REFRESH_OWNERSHIP + f"""
patch(0x40000+0x1ce0,string.char(0,0,0,0))
local phase,reason=refresh();assert(phase=='failed'and reason:find('count rejected'))
assert(next(result.owned)==nil and not result.capabilities.ownership_verified)
assert(not result.verify_owned({{{json.dumps(first)}}}))
patch(0x40000+0x1ce0,string.char(2,0,0,0))
local changed;phase,changed=refresh()
assert(phase=='ready'and changed and result.capabilities.ownership_verified)
assert(result.verify_owned({{{json.dumps(first)}}}))
"""
    assert run_fixture(tmp_path, post_ready=post).startswith('ready 1')


@pytest.mark.parametrize('mutation', [
    "patch(0x10008,string.rep('\\0',8))",
    "patch(0x21000,string.rep('\\0',8))",
])
def test_live_ownership_refresh_rejects_replaced_session_or_kit_slot(tmp_path, mutation):
    post = REFRESH_OWNERSHIP + mutation + """
local phase=refresh();assert(phase=='failed')
assert(next(result.owned)==nil and not result.capabilities.ownership_verified)
"""
    assert run_fixture(tmp_path, post_ready=post).startswith('ready 0')


def test_live_ownership_refresh_updates_count_used_by_application_proofs(tmp_path):
    first, second = [k['id'] for k in DATA['kits'].values() if k['category'] == 0][:2]
    post = REFRESH_OWNERSHIP + f"""
assert(result.counts.progression==1)
patch(0x40000+0x1ce0,string.char(2,0,0,0))
patch(0x40000+0x1ce4+184+0x14,string.char(2,0,0,0))
local phase,changed=refresh();assert(phase=='ready'and changed)
assert(result.counts.progression==2 and result.counts.owned_armors==2)
assert(result.verify_owned({{{json.dumps(first)},{json.dumps(second)}}}))
"""
    assert run_fixture(tmp_path, mutation="patch(0x40000+0x1ce0,string.char(1,0,0,0))", post_ready=post).startswith('ready 2')


def test_live_ownership_refresh_detects_race_before_publishing(tmp_path):
    post = REFRESH_OWNERSHIP + """
local raw_read=bridge.read
local seen=0
bridge.read=function(at,n)
 local value=raw_read(at,n)
 if at==0x40000+0x1ce4+0x14 then
  seen=seen+1
  if seen==1 then patch(at,string.char(1,0,0,0))end
 end
 return value
end
local phase,reason=refresh()
assert(phase=='failed'and reason:find('ownership changed during refresh'))
assert(next(result.owned)==nil and not result.capabilities.ownership_verified)
"""
    assert run_fixture(tmp_path, post_ready=post).startswith('ready 0')


def test_live_ownership_refresh_is_bounded_and_atomic_across_frames(tmp_path):
    post = """
local raw_read=bridge.read
local entry=raw_read(0x40000+0xb9ce4,12)
bridge.read=function(at,n)
 if at>=0x40000+0xb9ce4 and at<0x40000+0xb9ce4+256*24 and n==12 then return entry end
 return raw_read(at,n)
end
patch(0x40000+0x1ce0,string.char(0,1,0,0))
local previous=result.owned
local frames=0
for i=1,10000 do
 local before,bytes_before=calls,read_bytes
 local phase,changed=result.refresh_ownership();frames=frames+1
 assert(calls-before<=64 and read_bytes-bytes_before<=65536)
 if phase=='ready'then assert(not changed);break end
 assert(phase=='resolving'and result.owned==previous,'partial ownership was published')
end
assert(frames>1 and result.counts.progression==256)
"""
    assert run_fixture(tmp_path, post_ready=post).startswith('ready 1')
