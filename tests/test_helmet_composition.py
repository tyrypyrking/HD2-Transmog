from test_variant_patch import DATA, fixture, run

IDS=[f'{k["item_id"]:08x}' for k in DATA['kits'].values() if k['category']==1]
def helmet_fixture():
    code=fixture(*IDS[:3]).replace("dofile('src/variant_patch.lua')","dofile('src/armor_composition.lua')")
    return code+'''
result.category=1;result.capabilities.helmet_transmog_enabled=true
local function perk(record,enum)
 record.bytes=record.bytes:sub(1,28)..string.char(enum,0,0,0)..record.bytes:sub(33)
 put(record.address,record.bytes)
 result.catalog[record.reference.id].passive_variant_id='live:'..enum
end
perk(source,7);perk(target,8);perk(passive,9);request.passive_variant_id='live:9'
'''

def test_helmet_uses_own_look_identity_and_copies_only_weights_and_passive():
    run(helmet_fixture()+'''
local plan,why=patch:plan(result,request);assert(plan,why)
assert(plan.target_id==request.appearance_id)
assert(patch:apply(plan))
assert(read(source.address+28,4)==passive.bytes:sub(29,32))
assert(read(source.address,28)==source.bytes:sub(1,28))
assert(read(source.address+32,16)==source.bytes:sub(33,48))
local at=ptr(read(source.address+48,8),0)
for i=0,1 do
 local body=read(at+i*24,24);local pieces=ptr(body,8);local count=u32(body,16)
 local expected={}
 for _,b in ipairs(source.bodies)do if b.type==3 or b.type==i then
  for _,p in ipairs(b.pieces)do expected[#expected+1]=p end
 end end
 assert(count==#expected)
 for j,p in ipairs(expected)do
  local bytes=read(pieces+(j-1)*96,96)
  assert(bytes:sub(1,16)==p.bytes:sub(1,16)and bytes:sub(21)==p.bytes:sub(21))
 end
end
assert(patch:reset());assert(read(source.address,64)==source.bytes)
''')

def test_helmet_composition_requires_capability_and_same_slot_donors():
    run(helmet_fixture()+'''
result.capabilities.helmet_transmog_enabled=false
assert(not patch:plan(result,request)and #writes==0)
result.capabilities.helmet_transmog_enabled=true
passive.category=0
assert(not patch:plan(result,request)and #writes==0)
''')

def test_helmet_composition_rejects_unowned_donor_and_late_ownership_loss():
    run(helmet_fixture()+'''
result.owned[passive.reference.id]=nil
assert(not patch:plan(result,request))
result.owned[passive.reference.id]=true
local plan=assert(patch:plan(result,request))
authorized[passive.reference.id]=nil
assert(not patch:apply(plan)and #writes==0)
''')

def test_helmet_descriptor_failure_rolls_back_to_live_provider_baseline():
    run(helmet_fixture()+'''
local plan=assert(patch:plan(result,request))
local writer=bridge.write;local fail=true
bridge.write=function(at,s)
 if at==source.address+48 and fail then fail=false;put(at,s:sub(1,3));return false end
 return writer(at,s)
end
local applied,why=patch:apply(plan)
assert(not applied and why:find('rollback verified'),why)
assert(read(source.address,64)==source.bytes and not patch:is_active())
''')
