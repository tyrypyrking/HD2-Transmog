"""Native request/cache reader, with synthetic memory and real catalog IDs."""
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
PRELUDE=r'''local P=dofile('src/player_customization_probe.lua')
local data=dofile('src/catalog_data.lua')
local memory={}
local function word(n)local out={};for i=1,4 do out[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(out)end
local function pointer(n)return word(n)..word(0)end
local function put(at,s)for i=1,#s do memory[at+i-1]=s:sub(i,i)end end
local function read(at,n)local out={};for i=1,n do if not memory[at+i-1]then return nil end;out[i]=memory[at+i-1]end;return table.concat(out)end
local armor=0x1f9bfa78;local helmet,cape
for id,kit in pairs(data.kits)do if kit.category==1 then helmet=id elseif kit.category==2 then cape=id end end
local manager,players,player,entries,info=0x20000,0x30000,0x40000,0x50000,0x60000
put(0x10000,pointer(manager));put(0x10008,pointer(players))
put(players+0x84,word(1)..word(1));put(players+0xe8,pointer(player));put(player+8,word(0xfffffffd))
put(manager+0x930,pointer(entries)..word(8)..word(0xffffffff)..word(0xfffffffb))
-- Large uint32 hash product reduced modulo eight equals seven.
put(entries+56,word(0xfffffffd)..word(2));put(manager+0x948+16,pointer(info));put(info+16,word(77))
local request=word(0)..word(helmet)..word(cape)..word(armor)
put(manager+0xa7c+128,request)
put(manager+0x96c+136,request..string.rep('\0',40)..word(0)..word(data.kits[armor].passive_enum)..word(0))
local valid=true
local bridge={read=read,verify=function()return valid end,armor_catalog=0x10000,players=0x10008}
local observer=P.new(bridge,data)
'''
def run(code):
 p=subprocess.run(['luajit','-'],input=PRELUDE+code,text=True,cwd=ROOT,capture_output=True,timeout=10)
 assert p.returncode==0,p.stdout+p.stderr

def test_request_cache_snapshot_is_fresh_and_semantic():
 run(r'''
local a=assert(observer:sample());assert(a.slot==2 and a.local_player_id==0xfffffffd and a.settled)
assert(a.request_armor_id=='armor:1f9bfa78' and a.cache_passive_enum==data.kits[armor].passive_enum)
local b=assert(observer:sample());assert(a.session_key==b.session_key and a.verify())
local text=P.format(a);assert(not text:find('address')and not text:find('0x'))
put(manager+0xa7c+128+12,word(0x61b31723));assert(not a.verify())
local c=assert(observer:sample());assert(not c.settled and c.request_armor_id=='armor:61b31723')
valid=false;assert(not c.verify()and not observer:sample())
''')

def test_invalid_local_identity_or_layout_fails_closed():
 run(r'''
put(manager+0x938,word(7));assert(not observer:sample())
put(manager+0x938,word(8));put(players+0x88,word(2));assert(not observer:sample())
put(players+0x88,word(1));put(manager+0x96c+136+0x3c,word(0xffffffff));assert(not observer:sample())
put(manager+0x96c+136+0x3c,word(data.kits[armor].passive_enum));put(info+16,word(0x7fff));assert(not observer:sample())
''')

def test_session_key_changes_when_entity_identity_changes_and_race_rejects():
 run(r'''
local a=assert(observer:sample());put(info+16,word(78));local b=assert(observer:sample())
assert(a.session_key~=b.session_key and not a.verify())
local reads=0;bridge.read=function(at,n)
 local value=read(at,n);if at==player+8 then reads=reads+1;if reads==2 then return word(22)end end;return value
end
assert(not observer:sample())
''')


def test_creator_body_type_does_not_depend_on_cached_passive_or_equipment_ids():
 run(r'''
put(manager+0x96c+136+0x3c,word(0xffffffff))
put(manager+0x96c+136+4,word(0xffffffff))
assert(not observer:sample(),'Apply must still reject unverified equipment/passive')
local body=assert(observer:sample_body_type())
assert(body.body_type==0 and body.request_body_type==0 and body.verify())
put(manager+0x96c+136,word(1))
assert(not body.verify())
assert(observer:sample_body_type().body_type==1)
put(manager+0x96c+136,word(2));assert(not observer:sample_body_type())
''')


def test_creator_body_read_still_rejects_changed_identity_and_compatibility():
 run(r'''
local body=assert(observer:sample_body_type())
put(player+8,word(123));assert(not body.verify()and not observer:sample_body_type())
put(player+8,word(0xfffffffd));valid=false;assert(not observer:sample_body_type())
''')


def test_invalid_equipment_error_identifies_source_slot_and_value():
 run(r'''
put(manager+0x96c+136+4,word(0xffffffff))
local value,why=observer:sample()
assert(not value and why:find('cache.helmet id=ffffffff category=unknown expected=1',1,true))
put(manager+0xa7c+128+12,word(helmet))
value,why=observer:sample()
assert(not value and why:find('request.armor',1,true)and why:find('category=1 expected=0',1,true))
''')


def test_existing_body_armor_in_helmet_slot_is_observed_without_rewriting():
 run(r'''
put(manager+0xa7c+128+4,word(armor))
put(manager+0x96c+136+4,word(armor))
local observed=assert(observer:sample())
assert(observed.request.helmet_id==observed.request_armor_id)
assert(observed.current.helmet_id==observed.cache_armor_id)
assert(observed.settled and observed.verify())
assert(read(manager+0xa7c+128+4,4)==word(armor))
put(manager+0x96c+136+4,word(helmet))
assert(not observed.verify())
assert(not observer:sample().settled)
''')


def test_helmet_exception_does_not_admit_cape_or_unknown_ids_or_wrong_body_category():
 run(r'''
put(manager+0x96c+136+4,word(cape));assert(not observer:sample())
put(manager+0x96c+136+4,word(0xffffffff));assert(not observer:sample())
put(manager+0x96c+136+4,word(armor))
put(manager+0x96c+136+8,word(armor));assert(not observer:sample())
put(manager+0x96c+136+8,word(cape))
put(manager+0x96c+136+12,word(helmet));assert(not observer:sample())
''')


def test_headless_equipment_through_commit_bridge_preserves_helmet_and_checks_freshness():
 run(r'''
put(manager+0xa7c+128+4,word(armor));put(manager+0x96c+136+4,word(armor))
local Bridge=dofile('src/armor_refresh_bridge.lua')
local target='armor:61b31723';local current='armor:1f9bfa78';local commits=0
local grid={commit_capabilities=function()return {commit_verified=true}end,
 commit_snapshot=function()return {session='armory',local_player_id=0xfffffffd,
  other_key='native-protected-fields',pending_nonarmor=false,controller_armor_id=current,profile_armor_id=current}end,
 verify_commit=function()return true end,
 commit_owned=function(_,id)
  assert(id==target);commits=commits+1
  put(manager+0xa7c+128+12,word(0x61b31723));put(manager+0x96c+136+12,word(0x61b31723))
  current=target;return true
 end}
local catalog={owned={[target]=true},verify_owned=function()return true end}
local bridge=assert(Bridge.new(grid,observer,catalog))
local before=assert(bridge.snapshot());assert(bridge.commit_owned(target,before))
local after=assert(bridge.snapshot());assert(after.other_key==before.other_key)
assert(after.request_armor_id==target and commits==1)
assert(read(manager+0xa7c+128+4,4)==word(armor)and read(manager+0x96c+136+4,4)==word(armor))
put(manager+0x96c+136+4,word(helmet))
assert(not bridge.commit_owned(target,after)and commits==1)
''')
