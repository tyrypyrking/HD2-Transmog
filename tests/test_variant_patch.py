"""Independent three-donor composition with real current kit shapes and fake memory."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("catalog_tools",ROOT/"tools/armor_catalog.py")
catalog_tools=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog_tools)
DATA=json.loads((ROOT/"reference/current_catalog.json").read_text())


def literal(data):return '"'+''.join(f'\\{byte:03d}'for byte in data)+'"'


def fixture(look="b482b460",stats="1f9bfa78",perk="61b31723"):
    records={};puts=[]
    for index,key in enumerate(dict.fromkeys([look,stats,perk])):
        kit=DATA["kits"][str(int(key,16))];at=100000+index*100000;body_at=at+128
        raw=bytes.fromhex(kit["header"])+b"\0"*4+struct.pack("<QQ",body_at,len(kit["bodies"]))
        record={"address":at,"item_id":kit["item_id"],"category":kit["category"],"bodies":[],"reference":kit}
        puts.append((at,raw));record["bytes_token"]=literal(raw)
        for j,body in enumerate(kit["bodies"]):
            piece_at=at+1024+j*10000
            body_raw=struct.pack("<IIQQ",body["type"],0,piece_at,len(body["pieces"]))
            item={"address":body_at+j*24,"type":body["type"],"pieces":[],"bytes_token":literal(body_raw)}
            puts.append((body_at+j*24,body_raw))
            for k,piece in enumerate(body["pieces"]):
                b=bytes.fromhex(piece["raw"]);puts.append((piece_at+k*96,b))
                item["pieces"].append({"address":piece_at+k*96,"slot":piece["slot"],"kind":piece["type"],"weight":piece["weight"],"path":piece["path"],"bytes_token":literal(b)})
            record["bodies"].append(item)
        records[kit["id"]]=record
    # Preserve binary byte strings directly, with all remaining fields data-only.
    def lua(value):
        if isinstance(value,dict):return "{"+",".join("["+catalog_tools.lua("bytes"if k=="bytes_token"else k)+"]="+(v if k=="bytes_token"else lua(v))for k,v in value.items())+"}"
        if isinstance(value,list):return "{"+",".join(lua(v)for v in value)+"}"
        return catalog_tools.lua(value)
    domain={key:{"appearance_id":key,"stats_id":"native-stats:"+key.split(":")[1],"passive_variant_id":r["reference"]["passive_variant_id"]}for key,r in records.items()}
    req={"appearance_id":"armor:"+look,"stats_id":"native-stats:"+stats,"passive_variant_id":records["armor:"+perk]["reference"]["passive_variant_id"]}
    return r'''
local P=dofile('src/variant_patch.lua')
local memory,writes={},{}
local function put(at,s)for i=1,#s do memory[at+i-1]=s:sub(i,i)end end
local function read(at,n)local t={};for i=1,n do if not memory[at+i-1]then return nil end;t[i]=memory[at+i-1]end;return table.concat(t)end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function ptr(s,o)return u32(s,o)+u32(s,o+4)*4294967296 end
''' + "\n".join(f"put({at},{literal(raw)})"for at,raw in puts)+f'''
local records={lua(records)}
local result={{records=records,catalog={lua(domain)},owned={{}},capabilities={{kit_records_verified=true,ownership_verified=true}}}}
for id in pairs(records)do result.owned[id]=true end
local request={lua(req)}
local source=records[{json.dumps('armor:'+look)}]
local target=records[{json.dumps('armor:'+stats)}]
local passive=records[{json.dumps('armor:'+perk)}]
''' + r'''
local authorized={};for id in pairs(records)do authorized[id]=true end
local next_at,allocated=1000000,0
local bridge={read=read,write=function(at,s)writes[#writes+1]={at=at,bytes=s};put(at,s);return true end,
 allocate=function(bytes)local at=next_at;next_at=next_at+#bytes+16;allocated=allocated+1;put(at,bytes);return {address=at,size=#bytes,bytes=bytes}end,
 verify=function(_,_,_,_,phase,ids)
  if phase=='reset'or phase=='rollback'then return true end
  assert(#ids==3,'three independent donors must be checked')
  for _,id in ipairs(ids)do if not authorized[id]then return false end end
  return true
 end}
local patch=P.new(bridge)
local function weight_sequence(record,body_type)
 local out={}
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==body_type then
  for _,piece in ipairs(body.pieces)do if piece.kind==0 and piece.weight~=3 then out[#out+1]=piece.weight end end
 end end
 return table.concat(out,',')
end
local function assert_clone_matches(uniform)
 local header=read(target.address,64)
 assert(header:sub(1,12)==target.bytes:sub(1,12),'carrier identity/DLC/set changed')
 assert(header:sub(13,24)==source.bytes:sub(13,24),'appearance localization changed')
 assert(header:sub(25,28)==target.bytes:sub(25,28),'carrier rarity changed')
 assert(header:sub(29,32)==passive.bytes:sub(29,32),'wrong independent passive')
 assert(header:sub(33,40)==source.bytes:sub(33,40),'wrong appearance package')
 assert(header:sub(41,48)==target.bytes:sub(41,48),'carrier category changed')
 local body_at=ptr(header,48);assert(body_at~=ptr(source.bytes,48)and body_at~=ptr(target.bytes,48),'body arrays were not cloned')
 local observed={category=0,bodies={}}
 for i=0,u32(header,56)-1 do
  local body=read(body_at+i*24,24);local p={type=u32(body,0),pieces={}}
  for j=0,u32(body,16)-1 do
   local raw=read(ptr(body,8)+j*96,96)
   p.pieces[#p.pieces+1]={slot=u32(raw,8),kind=u32(raw,12),weight=u32(raw,16),raw=raw}
  end
  observed.bodies[#observed.bodies+1]=p
 end
 for _,kind in ipairs({0,1})do
  if uniform==nil then
   assert(weight_sequence(observed,kind)==weight_sequence(target,kind),'base stats sequence changed')
  else
   local B=dofile('src/armor_base_stats.lua')
   local C={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
   local before,after=assert(B.calculate(target,kind,C)),assert(B.calculate(observed,kind,C))
   for _,field in ipairs({'armor_rating','speed','stamina_regen'})do
    assert(before.base_values[field]==after.base_values[field],'uniform native displayed stats changed')
    -- Uniform float32 summation can vary in its last bits with piece count;
    -- equality of rounded values must not be presented as bitwise equality.
    assert(math.abs(before.coefficients[field]-after.coefficients[field])<0.000001)
   end
   local torso=false
   for _,body in ipairs(observed.bodies)do if body.type==3 or body.type==kind then
    for _,piece in ipairs(body.pieces)do if piece.kind==0 then
     assert(piece.weight==uniform,'uniform donor weight not preserved')
     if piece.slot==2 then torso=true end
    end end
   end end
   assert(torso,'native torso class is missing')
  end
  local visible={}
  for _,body in ipairs(source.bodies)do if body.type==3 or body.type==kind then
   for _,piece in ipairs(body.pieces)do
    local visual=piece.bytes:sub(1,16)..piece.bytes:sub(21);visible[visual]=(visible[visual]or 0)+1
   end
  end end
  local count=0
  for _,body in ipairs(observed.bodies)do if body.type==3 or body.type==kind then
   count=count+#body.pieces
   for _,piece in ipairs(body.pieces)do if piece.raw:sub(1,8)~=string.rep('\0',8)then
    local visual=piece.raw:sub(1,16)..piece.raw:sub(21)
    assert(visible[visual]and visible[visual]>0,'visual piece changed');visible[visual]=visible[visual]-1
   end end
  end end
  assert(count<=20,'native piece gather limit exceeded')
  for _,left in pairs(visible)do assert(left==0,'visual piece missing')end
 end
 if uniform~=nil then
  assert(#observed.bodies==#source.bodies,'uniform composition changed body topology')
  for index,body in ipairs(observed.bodies)do
   local original=source.bodies[index]
   assert(body.type==original.type and #body.pieces==#original.pieces)
   for piece_index,piece in ipairs(body.pieces)do
    local wanted=original.pieces[piece_index].bytes
    assert(piece.raw:sub(1,16)..piece.raw:sub(21)==wanted:sub(1,16)..wanted:sub(21),'uniform visual order changed')
    if piece.kind~=0 then assert(piece.raw==wanted,'non-Armor piece was modified')end
   end
  end
 end
 return observed
end
'''


def run(script):
    p=subprocess.run(["luajit","-"],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    assert p.returncode==0,p.stdout+p.stderr


def test_heavy_appearance_light_base_and_third_armor_passive_are_independent_and_reversible():
    run(fixture()+r'''
local plan=assert(patch:plan(result,request));assert(#writes==0 and allocated>0)
assert(plan.passive_source_id~=plan.source_id and plan.passive_source_id~=plan.target_id)
plan.request.passive_variant_id='tampered'
local ok,evidence=patch:apply(plan);assert(ok)
assert(#writes==5 and #writes[1].bytes==4 and #writes[2].bytes==8 and #writes[3].bytes==16)
assert(writes[4].at==target.address+12 and #writes[4].bytes==8)
assert(writes[5].at==target.address+20 and #writes[5].bytes==4 and evidence.appearance_labels_preserved)
assert(evidence.base_weight_sequence_preserved and not evidence.passive_bytes_unchanged)
assert_clone_matches()
assert(read(source.address,64)==source.bytes and read(passive.address,64)==passive.bytes)
authorized[plan.source_id]=false
assert(patch:reset());assert(read(target.address,64)==target.bytes)
assert(not patch:is_active())
''')


def test_native_medium_extra_padding_donor_does_not_carry_old_perk_into_ballistic_variant():
    run(fixture("f4598295","61b31723","f4598295")+r'''
local plan=assert(patch:plan(result,request));assert(patch:apply(plan));assert_clone_matches()
assert(read(target.address+28,4)~=target.bytes:sub(29,32),'old Extra Padding was retained')
assert(patch:reset())
''')


def test_same_appearance_and_stat_carrier_can_change_only_selected_perk_and_private_weights():
    run(fixture("1f9bfa78","1f9bfa78","61b31723")+r'''
assert(patch:apply(assert(patch:plan(result,request))));assert_clone_matches()
assert(#writes==2,'unchanged package should not be written')
assert(patch:reset())
''')


def test_fresh_perk_ownership_and_partial_perk_write_rollback():
    run(fixture()+r'''
local plan=assert(patch:plan(result,request));authorized[plan.passive_source_id]=false
assert(not patch:apply(plan)and #writes==0)
authorized[plan.passive_source_id]=true
local calls=0;bridge.write=function(at,s)calls=calls+1;if calls==1 then put(at,s:sub(1,2));return false end;put(at,s);return true end
local ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok and why:find('rollback verified'),why)
assert(read(target.address,64)==target.bytes and not patch:is_active())
''')


def test_mixed_donor_surplus_visual_and_stat_only_representations_remain_guarded():
    run(fixture("b482b460","5bb4bbb0","61b31723")+r'''
local plan,why=patch:plan(result,request);assert(not plan and why:find('weight%-None'))
result.render_trial=true
assert(patch:apply(assert(patch:plan(result,request))));assert_clone_matches();assert(patch:reset())
''')
    run(fixture("dae4a744","b92e1781","61b31723")+r'''
local plan,why=patch:plan(result,request);assert(not plan and why:find('stat%-only'))
result.render_trial=true
assert(patch:apply(assert(patch:plan(result,request))));assert_clone_matches();assert(patch:reset())
''')


def test_exact_render_trial_is_explicit_and_does_not_claim_render_verification():
    run(fixture("b482b460","5bb4bbb0","61b31723")+r'''
result.render_trial='true'
assert(not patch:plan(result,request),'string must not enable rendering trial')
result.render_trial=true
local plan=assert(patch:plan(result,request));assert(plan.render_trial and plan.weight_none)
local ok,evidence=patch:apply(plan);assert(ok and evidence.render_trial)
assert(not evidence.appearance_verified and not evidence.numeric_stats_verified)
assert(result.capabilities.weight_none_render_verified==nil)
assert_clone_matches();assert(patch:reset())
''')


def test_uniform_donors_preserve_every_current_look_topology_and_native_display_for_both_bodies():
    looks = sorted(f'{kit["item_id"]:08x}' for kit in DATA['kits'].values()
                   if kit['category'] == 0)
    assert len(looks) == 135
    for look in looks:
        for weight, stats in enumerate(('1f9bfa78', '61b31723', 'b482b460')):
            run(fixture(look, stats)+f'''
local plan,why=patch:plan(result,request);assert(plan,why)
assert(plan.uniform_weight=={weight} and plan.appearance_topology_preserved)
assert(not plan.weight_none and not plan.stat_only_pieces and not plan.render_trial)
local ok,evidence=patch:apply(plan);assert(ok,evidence)
assert(evidence.uniform_weight=={weight} and evidence.appearance_topology_preserved)
assert(not evidence.appearance_verified and not evidence.numeric_stats_verified)
local observed=assert_clone_matches({weight})
local sequence=weight_sequence(observed,0)==weight_sequence(target,0)
 and weight_sequence(observed,1)==weight_sequence(target,1)
assert(plan.base_weight_sequence_preserved==sequence and evidence.base_weight_sequence_preserved==sequence)
assert(patch:reset()and read(target.address,64)==target.bytes)
''')


def test_uniform_topology_evidence_does_not_claim_identical_unrounded_float32_stats():
    # This light look has three display contributors; Lawmaker has seven. Heavy-speed
    # coefficient summation differs in its low bits, but both display450.
    run(fixture('c71dbba4', 'b482b460')+r'''
local plan=assert(patch:plan(result,request))
assert(plan.uniform_weight==2 and not plan.base_weight_sequence_preserved)
local ok,evidence=patch:apply(plan);assert(ok and not evidence.numeric_stats_verified)
local observed=assert_clone_matches(2)
local B=dofile('src/armor_base_stats.lua')
local C={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
for _,body_type in ipairs({0,1})do
 local before,after=assert(B.calculate(target,body_type,C)),assert(B.calculate(observed,body_type,C))
 assert(before.unrounded.speed~=after.unrounded.speed)
 assert(before.base_values.speed==450 and after.base_values.speed==450)
end
assert(patch:reset())
''')


def test_uniform_donor_requires_a_real_torso_in_both_body_shapes():
    run(fixture()+r'''
local function word(n)return string.char(n%256,math.floor(n/256)%256,0,0)end
for _,body in ipairs(target.bodies)do if body.type==1 then
 for _,piece in ipairs(body.pieces)do if piece.kind==0 and piece.slot==2 then
  piece.slot=42;piece.bytes=piece.bytes:sub(1,8)..word(42)..piece.bytes:sub(13)
  put(piece.address,piece.bytes)
 end end
end end
local plan,why=patch:plan(result,request)
assert(not plan and why:find('contributing torso',1,true),tostring(why))
assert(#writes==0 and allocated==0)
''')


def test_uniform_qualification_cannot_ignore_an_unknown_ui_weight():
    run(fixture()+r'''
local piece=target.bodies[1].pieces[1]
assert(piece.kind==0)
piece.weight=3;piece.bytes=piece.bytes:sub(1,16)..string.char(3,0,0,0)..piece.bytes:sub(21)
put(piece.address,piece.bytes)
local plan=patch:plan(result,request)
assert(not plan,'unknown fourth coefficient must not use uniform composition')
assert(#writes==0)
''')


def test_uniform_donor_is_rejected_instead_of_truncated_at_twenty_pieces():
    run(fixture()+r'''
local function word(n)return string.char(n%256,math.floor(n/256)%256,0,0)end
local body=target.bodies[1];local template=body.pieces[2]
for i=1,5 do
 local raw=template.bytes:sub(1,8)..word(40+i)..word(2)..template.bytes:sub(17)
 local piece={slot=40+i,kind=2,weight=template.weight,bytes=raw,
  address=ptr(body.bytes,8)+#body.pieces*96}
 body.pieces[#body.pieces+1]=piece;put(piece.address,raw)
end
body.bytes=body.bytes:sub(1,16)..word(#body.pieces)..body.bytes:sub(21);put(body.address,body.bytes)
local plan,why=patch:plan(result,request)
assert(not plan and why:find('collection capacity',1,true),tostring(why))
assert(#writes==0 and allocated==0)
''')


def test_native_name_and_description_use_appearance_hashes_and_reset_reverses_them():
    run(fixture()+r'''
local plan=assert(patch:plan(result,request));assert(plan.appearance_labels_preserved)
local ok,evidence=patch:apply(plan);assert(ok and evidence.appearance_labels_preserved)
assert(read(target.address+12,12)==source.bytes:sub(13,24))
assert(read(target.address,12)==target.bytes:sub(1,12))
assert(read(target.address+24,4)==target.bytes:sub(25,28))
assert(read(target.address+40,8)==target.bytes:sub(41,48))
assert(read(source.address,64)==source.bytes)
assert(patch:reset()and read(target.address,64)==target.bytes)
''')


def test_localization_mutation_requires_matching_reference_fields():
    run(fixture()+r'''
source.reference.description_loc=source.reference.description_loc+1
local plan,why=patch:plan(result,request)
assert(not plan and why:find('localization fields',1,true))
assert(#writes==0 and allocated==0)
''')


def test_partial_name_write_rolls_back_every_changed_range():
    run(fixture()+r'''
local calls=0
bridge.write=function(at,bytes)
 calls=calls+1
 if at==target.address+12 and calls==4 then put(at,bytes:sub(1,3));return false end
 put(at,bytes);return true
end
local ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok and why:find('rollback verified',1,true),tostring(why))
assert(read(target.address,64)==target.bytes and not patch:is_active())
''')


def test_reset_keeps_independently_changed_localization_bytes():
    run(fixture()+r'''
assert(patch:apply(assert(patch:plan(result,request))))
local old=read(target.address+20,4);local replacement
for byte=0,255 do
 local candidate=string.char(byte)..old:sub(2)
 if candidate:sub(1,1)~=source.bytes:sub(21,21)and candidate:sub(1,1)~=target.bytes:sub(21,21)then replacement=candidate;break end
end
put(target.address+20,replacement)
local ok,why=patch:reset()
assert(not ok and read(target.address+20,4)==replacement,'reset overwrote unrelated localization change')
assert(why:find('conflicts with retained evidence',1,true))
''')
