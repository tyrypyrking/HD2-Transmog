"""Shipping composition must never change any armor resource identity."""
from test_variant_patch import DATA, fixture as legacy_fixture, run


def fixture(look='b482b460', stats='1f9bfa78', perk='61b31723'):
    script = legacy_fixture(look, stats, perk)
    script = script.replace("dofile('src/variant_patch.lua')", "dofile('src/armor_composition.lua')")
    script = script.replace(f'local target=records["armor:{stats}"]', f'local stats=records["armor:{stats}"];local target=source')
    script = script.replace('weight_sequence(target,', 'weight_sequence(stats,')
    script = script.replace('B.calculate(target,', 'B.calculate(stats,')
    return script


def test_appearance_remains_its_own_carrier_and_only_stats_and_perk_are_writable():
    run(fixture() + '''
local plan=assert(patch:plan(result,request))
assert(plan.target_id==request.appearance_id and plan.source_id==plan.target_id)
assert(plan.stats_source_id=='armor:1f9bfa78')
local ok,evidence=patch:apply(plan);assert(ok,evidence)
assert(evidence.package_identity_preserved and evidence.appearance_topology_preserved)
for _,write in ipairs(writes)do
 assert(write.at==source.address+28 and #write.bytes==4 or write.at==source.address+48 and #write.bytes==16)
end
assert_clone_matches(0)
assert(read(stats.address,64)==stats.bytes and read(passive.address,64)==passive.bytes)
assert(read(source.address,28)==source.bytes:sub(1,28))
assert(read(source.address+32,16)==source.bytes:sub(33,48))
assert(patch:reset()and read(source.address,64)==source.bytes)
''')


def test_all_uniform_compositions_keep_original_body_topology_and_every_visual_byte():
    looks=[f'{int(key):08x}' for key,value in DATA['kits'].items() if value['category']==0]
    for look in looks:
        for stats,weight in [('1f9bfa78',0),('61b31723',1),('b482b460',2)]:
            run(fixture(look,stats)+f'''
local plan,why=patch:plan(result,request);assert(plan,why)
local ok,evidence=patch:apply(plan);assert(ok,evidence)
assert(plan.target_id==request.appearance_id)
assert_clone_matches({weight})
for _,write in ipairs(writes)do assert(write.at==source.address+28 or write.at==source.address+48)end
assert(patch:reset()and read(source.address,64)==source.bytes)
''')


def test_partial_descriptor_failure_recovers_without_touching_package_or_visual_bytes():
    run(fixture()+'''
local plan=assert(patch:plan(result,request));local wrote=bridge.write;local failed=false
bridge.write=function(at,s)
 if at==source.address+48 and not failed then failed=true;put(at,s:sub(1,3));return false end
 return wrote(at,s)
end
local ok,why=patch:apply(plan);assert(not ok and why:find('rollback verified'),why)
assert(read(source.address,64)==source.bytes and not patch:is_active())
for _,write in ipairs(writes)do assert(write.at==source.address+28 or write.at==source.address+48)end
''')


def test_session_default_uses_appearance_identity_for_target_and_keeps_stats_donor():
    from test_variant_session import FIXTURE
    run(FIXTURE+'''
host.target_for=nil
local observed
host.new_refresh=function()return {begin=function(_,request)
 observed=request;return true
end}end
ready(0);assert(s:apply(2))
assert(observed.target_id==A)
assert(observed.donor_ids[1]==A and observed.donor_ids[2]==B and observed.donor_ids[3]==C)
assert(plans==0 and applies==0)
''')


def test_preflight_never_allocates_writes_or_starts_equipment_for_incompatible_layout():
    run(fixture()+'''
assert(P.compatible(result,request))
assert(allocated==0 and #writes==0)
stats.bodies[1].pieces[1].weight=3
local ok,why=P.compatible(result,request)
assert(not ok and why:find('composition unavailable')and allocated==0 and #writes==0)
''')
    from test_variant_session import FIXTURE
    run(FIXTURE+'''
ready(0)
local refreshes=0
host.new_refresh=function()refreshes=refreshes+1;error('must not begin')end
host.validate_composition=function()return nil,'Choose a standard base profile.'end
assert(not s:apply(2)and refreshes==0 and plans==0 and applies==0 and #commits==0)
assert(s:view().apply_notice=='Choose a standard base profile.')
''')


def test_custom_variant_four_maps_reordered_parts_to_129_base_plus_extra_padding():
    run(fixture('2521d401','803276ce','d2c578e1')+'''
assert(P.compatible(result,request))
local plan,why=patch:plan(result,request);assert(plan,why)
local ok,evidence=patch:apply(plan);assert(ok,evidence)
assert(evidence.package_identity_preserved and evidence.appearance_topology_preserved and evidence.slot_weights_preserved)
assert(not evidence.base_weight_sequence_preserved,'different storage order was reported as an identical sequence')
local live={category=0,bodies={}}
local header=read(source.address,64)
assert(header:sub(1,28)==source.bytes:sub(1,28)and header:sub(33,48)==source.bytes:sub(33,48))
assert(u32(header,28)==1,'Extra Padding enum was not selected')
for i,body in ipairs(source.bodies)do
 local raw=read(ptr(header,48)+(i-1)*24,24)
 assert(u32(raw,0)==body.type and u32(raw,16)==#body.pieces)
 local actual={type=body.type,pieces={}};live.bodies[i]=actual
 local donor;for _,b in ipairs(stats.bodies)do if b.type==body.type then donor=b end end
 for j,p in ipairs(body.pieces)do
  local piece=read(ptr(raw,8)+(j-1)*96,96)
  assert(piece:sub(1,16)..piece:sub(21)==p.bytes:sub(1,16)..p.bytes:sub(21),'visual bytes or original piece order changed')
  local expected;for _,d in ipairs(donor.pieces)do if d.slot==p.slot and d.kind==p.kind then expected=d end end
  local weight=u32(piece,16)
  assert(weight==(p.kind==0 and expected.weight or p.weight))
  actual.pieces[j]={slot=p.slot,kind=p.kind,weight=weight}
 end
end
local B=dofile('src/armor_base_stats.lua')
local c={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
for _,body in ipairs({0,1})do
 local wanted=assert(B.calculate(stats,body,c));local observed=assert(B.calculate(live,body,c))
 assert(observed.base_values.armor_rating==129)
 for _,field in ipairs({'armor_rating','speed','stamina_regen'})do
  assert(observed.base_values[field]==wanted.base_values[field],field)
 end
 assert(math.floor(observed.unrounded.armor_rating+50+0.5)==179)
end
for _,write in ipairs(writes)do assert(write.at==source.address+28 or write.at==source.address+48)end
assert(read(stats.address,64)==stats.bytes)
assert(patch:reset()and read(source.address,64)==source.bytes)
''')


def test_mixed_mapping_rejects_unknown_native_slots_before_any_write():
    run(fixture('2521d401','803276ce','d2c578e1')+'''
local p=stats.bodies[1].pieces[1]
p.slot=99;p.bytes=p.bytes:sub(1,8)..string.char(99,0,0,0)..p.bytes:sub(13);put(p.address,p.bytes)
assert(not P.compatible(result,request))
local plan,why=patch:plan(result,request)
assert(not plan and why:find('unsupported native piece fields',1,true),tostring(why))
assert(#writes==0 and read(source.address,64)==source.bytes)
''')


def test_ie57_64_democracy_protects_is_reversible_with_both_owned_stat_donors():
    for donor in ('d52bb413', '5a17d6d6'):
        run(fixture('e1d53693', donor, 'b513fd54')+'''
assert(P.compatible(result,request))
assert(allocated==0 and #writes==0)
local plan,why=patch:plan(result,request);assert(plan,why)
local ok,evidence=patch:apply(plan);assert(ok,evidence)
assert(evidence.stat_only_pieces and not evidence.weight_none and not evidence.reclassified_pieces)
assert(evidence.package_identity_preserved and not evidence.appearance_topology_preserved)
local header=read(source.address,64)
assert(header:sub(1,28)==source.bytes:sub(1,28)and header:sub(33,48)==source.bytes:sub(33,48))
assert(header:sub(29,32)==passive.bytes:sub(29,32))
local live={category=0,bodies={}}
for i=0,u32(header,56)-1 do
 local raw=read(ptr(header,48)+i*24,24)
 local b={type=u32(raw,0),pieces={}};live.bodies[#live.bodies+1]=b
 for j=0,u32(raw,16)-1 do
  local p=read(ptr(raw,8)+j*96,96)
  b.pieces[#b.pieces+1]={slot=u32(p,8),kind=u32(p,12),weight=u32(p,16),raw=p}
 end
end
local B=dofile('src/armor_base_stats.lua')
local c={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
for _,body_type in ipairs({0,1})do
 local base=assert(B.calculate(live,body_type,c))
 assert(base.base_values.armor_rating==64 and base.base_values.speed==536 and base.base_values.stamina_regen==118)
 local visible={};local count=0
 for _,b in ipairs(source.bodies)do if b.type==3 or b.type==body_type then
  for _,p in ipairs(b.pieces)do visible[p.bytes:sub(1,16)..p.bytes:sub(21)]=true end
 end end
 for _,b in ipairs(live.bodies)do if b.type==3 or b.type==body_type then
  for _,p in ipairs(b.pieces)do
   count=count+1
   if p.raw:sub(1,8)==string.rep('\\0',8)then assert(p.slot==8 or p.slot==9)
   else local key=p.raw:sub(1,16)..p.raw:sub(21);assert(visible[key]);visible[key]=nil end
  end
 end end
 assert(count==17 and next(visible)==nil)
end
for _,write in ipairs(writes)do assert(write.at==source.address+28 or write.at==source.address+48)end
assert(read(stats.address,64)==stats.bytes)
assert(patch:reset()and read(source.address,64)==source.bytes)
''')
