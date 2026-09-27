"""Pure native Armor-card base values; no game access or donor-passive boosts."""
import json
from pathlib import Path
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r'''
local M=dofile('src/armor_base_stats.lua')
local D=dofile('src/catalog_data.lua')
-- Explicit unverified contract, never a claim about uncaptured operands.
local C={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
local function record(pieces)return {category=0,bodies={{type=3,pieces=pieces}}}end
local function piece(slot,weight,kind)return {slot=slot,weight=weight,kind=kind or 0}end
local function equal(actual,armor,speed,stamina)
 assert(actual.armor_rating==armor and actual.speed==speed and actual.stamina_regen==stamina,
  tostring(actual.armor_rating)..'/'..tostring(actual.speed)..'/'..tostring(actual.stamina_regen))
end
'''


def run(code):
    process = subprocess.run(["luajit", "-"], input=PRELUDE+code, text=True,
                             cwd=ROOT, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stdout+process.stderr


def test_missing_constant_or_rounding_contract_cannot_produce_verified_values():
    run(r'''
local sample=D.kits[0x1f9bfa78]
assert(not M.calculate(sample,0))
local known=M.evidence();assert(not known.verified and known.armor_scale==nil and known.one==nil and known.zero==nil and known.rounding==nil)
assert(known.initial_value==100 and known.speed_scale==5 and #known.missing==4)
assert(not M.calculate(sample,0,known))
for _,key in ipairs(known.missing)do
 local value=C[key];C[key]=nil;assert(not M.calculate(sample,0,C),key);C[key]=value
end
local value=assert(M.calculate(sample,0,C));assert(not value.verified)
C.verified=true;assert(not assert(M.calculate(sample,0,C)).verified,'evidence-free flag must not certify')
C.evidence='synthetic captured-formula fixture';assert(assert(M.calculate(sample,0,C)).verified)
known.coefficients.speed[1]=200
equal(assert(M.calculate(sample,0,C)).base_values,50,550,125)
''')


def test_real_light_heavy_and_extra_padding_donor_have_base_only_values():
    run(r'''
equal(assert(M.calculate(D.kits[0x1f9bfa78],0,C)).base_values,50,550,125)
equal(assert(M.calculate(D.kits[0xb482b460],0,C)).base_values,150,450,50)
local padded=D.kits[0x61b31723]
assert(padded.passive_enum==1)
equal(assert(M.calculate(padded,0,C)).base_values,100,500,100)
padded.passive_enum=999;padded.passive_variant_id='untrusted boost'
equal(assert(M.calculate(padded,0,C)).base_values,100,500,100)
-- Five counted display pieces: two Medium and three Light, independent of
-- the native Cape/Hips or cosmetic pieces in this exact current kit shape.
local mixed=assert(M.calculate(D.kits[0x5bb4bbb0],0,C))
assert(mixed.contributor_count==5)
equal(mixed.base_values,70,530,115)
''')


def test_native_filter_body_choice_and_zero_path_are_preserved():
    run(r'''
local r={category=0,bodies={
 {type=3,pieces={piece(0,2),piece(1,2),piece(3,2),piece(2,2,1),piece(4,2,2)}},
 {type=0,pieces={piece(2,0),piece(4,0)}},
 {type=1,pieces={piece(2,2),piece(4,2)}}}}
r.bodies[2].pieces[1].path='0000000000000000'
local light=assert(M.calculate(r,0,C));assert(light.gathered_count==7 and light.contributor_count==2)
equal(light.base_values,50,550,125)
equal(assert(M.calculate(r,1,C)).base_values,150,450,50)
assert(not M.calculate(r,2,C),'body choice must be explicit 0 or 1')
assert(not M.calculate(record({piece(2,3)}),0,C),'None indexes outside proved UI tables')
-- Native helper returns zero coefficients when no eligible display pieces.
equal(assert(M.calculate(record({piece(1,2),piece(3,2)}),0,C)).base_values,50,0,200)
''')


def test_gather_cap_applies_before_filtering_and_keeps_original_body_order():
    run(r'''
local rows={}
for i=1,29 do rows[i]=piece(1,2)end
rows[30]=piece(2,0);rows[31]=piece(4,2)
local r=record(rows)
local value=assert(M.calculate(r,0,C));assert(value.gathered_count==30 and value.contributor_count==1)
equal(value.base_values,50,550,125)
local early={type=0,pieces={piece(2,2)}}
table.insert(r.bodies,1,early)
value=assert(M.calculate(r,0,C));assert(value.gathered_count==30 and value.contributor_count==1)
equal(value.base_values,150,450,50)
''')


def test_rounding_is_explicit_and_unrounded_values_remain_available():
    run(r'''
local r=record({piece(2,0),piece(4,1),piece(5,1),piece(6,1)})
local away=assert(M.calculate(r,0,C));assert(away.unrounded.armor_rating==87.5 and away.base_values.armor_rating==88)
C.rounding='floor';local down=assert(M.calculate(r,0,C));assert(down.base_values.armor_rating==87 and down.unrounded.armor_rating==87.5)
C.rounding='unknown';assert(not M.calculate(r,0,C))
C.rounding='nearest_ties_even';C.initial_value=99
local even=assert(M.calculate(r,0,C));assert(even.unrounded.armor_rating==86.5 and even.base_values.armor_rating==86)
C.rounding='nearest_ties_away';assert(assert(M.calculate(r,0,C)).base_values.armor_rating==87)
''')


def test_owned_choices_deduplicate_displayed_tuples_and_retain_stable_donors():
    run(r'''
local result={owned={},records={},catalog={},capabilities={kit_records_verified=true,ownership_verified=true}}
local function add(item,owned,source)
 local id=string.format('armor:%08x',item)
 local r=source or D.kits[item];r.item_id=item
 result.records[id]=r;result.owned[id]=owned
 result.catalog[id]={stats_id=string.format('native-stats:%08x',item)}
 return id
end
local heavy=add(0xb482b460,true)
local light=add(0x1f9bfa78,true)
local medium=add(0x61b31723,true)
local other_medium=add(0xdae4a744,true)
add(0x5bb4bbb0,false)
local groups=assert(M.choices(result,0,C));assert(#groups==3)
equal(groups[1].base_values,50,550,125);equal(groups[2].base_values,100,500,100);equal(groups[3].base_values,150,450,50)
assert(#groups[2].donors==2 and groups[2].donor_ids[1]==medium and groups[2].donor_ids[2]==other_medium)
assert(groups[2].representative_kit_id==medium and groups[2].stats_id=='native-stats:61b31723')
assert(not groups[1].verified and groups[1].donor_passive_ignored)
result.owned[medium]=false;groups=assert(M.choices(result,0,C));assert(groups[2].representative_kit_id==other_medium)
result.capabilities.ownership_verified=false;assert(not M.choices(result,0,C))
''')


def test_display_deduplication_keeps_distinct_unrounded_donor_values():
    run(r'''
local result={owned={},records={},catalog={},capabilities={kit_records_verified=true,ownership_verified=true}}
for index,counts in ipairs({{9,4},{16,7}})do
 local pieces={};for i=1,counts[1]do pieces[i]=piece(2,i<=counts[2]and 1 or 0)end
 local r=record(pieces);r.item_id=index
 local id=string.format('armor:%08x',index)
 result.owned[id]=true;result.records[id]=r;result.catalog[id]={stats_id=string.format('native-stats:%08x',index)}
end
local groups=assert(M.choices(result,0,C));assert(#groups==1 and #groups[1].donors==2)
equal(groups[1].base_values,72,528,114)
assert(groups[1].unrounded==nil,'do not pretend rounded-equivalent donors have identical underlying values')
assert(groups[1].donors[1].unrounded.armor_rating~=groups[1].donors[2].unrounded.armor_rating)
result.owned={};assert(not M.choices(result,2,C),'invalid body selection must fail even with no owned donors')
''')


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def test_float32_operations_and_all_current_kit_shapes_match_scalar_reference():
    data=json.loads((ROOT/'reference/current_catalog.json').read_text())
    checks=[]
    coefficients=((0,1,2),(f32(1.1),1,f32(.9)),(.75,1,1.5))
    for key,kit in data['kits'].items():
        if kit['category']!=0:
            continue
        for shape in (0,1):
            gathered=[piece for body in kit['bodies'] if body['type'] in (3,shape)
                      for piece in body['pieces']][:30]
            weights=[piece['weight'] for piece in gathered if piece['type']==0
                     and piece['slot'] in (2,4,5,6,7,8,9)]
            means=[]
            for table in coefficients:
                total=0.0
                for weight in weights:
                    total=f32(total+table[weight])
                means.append(f32(total/len(weights)) if weights else 0.0)
            expected=(f32(f32(f32(means[0]-1)*50)+100),
                      f32(f32(means[1]*5)*100),
                      f32(f32(f32(0-f32(means[2]-1))+1)*100))
            checks.append(f"do local v=assert(M.calculate(D.kits[{key}],{shape},C));"
                          +''.join(f"assert(v.unrounded.{field}=={value!r});"
                                   for field,value in zip(('armor_rating','speed','stamina_regen'),expected))
                          +"end")
    assert len(checks)==270
    run('\n'.join(checks))
