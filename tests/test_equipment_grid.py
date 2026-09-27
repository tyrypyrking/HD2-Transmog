"""Equipment picker identity and current-image native setter evidence."""
from pathlib import Path
import subprocess
import pytest
from test_native_grid import FIXTURE, SELECTION, COMMIT

ROOT=Path(__file__).resolve().parents[1]
ROUTE="8b8f1c28000085c9743e83e901741f83f9017578488b0d2d800300448bc2418992280100008bd3e8d40f0000eb5e488b0d13800300448bc2418992240100008bd3e8ba0f0000eb44488b0df97f0300448bc24189922c0100008bd3e8a00f0000eb2a"
SETTER="40574883ec203b1578dbc002488bf90f8425010000448b99380900004533c948895c2430458bd18b99400900000fafda4c89742448458d73ff4585db0f84ee00000048896c24388ba93c0900004889742440488bb1300900000f1f8000000000418bc6418d0c1a4823c88b04ce488d0cce3bc574113bc2741541ffc2453bd372dfe9a00000003bc20f85980000008b410483f8ff0f848c0000008bf08be848c1e6064439843e880a0000747a4c8b1d9503ab02418bc9418b530885d27468498b1b448bd14a8b04d34439007408ffc13bca72eeeb09493bc1752585d274484d8b034b8b04c881382317b361740a41ffc1443bca72eceb2f4885c0742a448b004489843e880a0000baeca2d3b7488b84ef480900004c8d87880a00004c03c68b4810e80a367600488b742440488b6c2438488b5c24304c8b7424484883c420"


def run(body, commit=False):
    fixture=FIXTURE.replace('region(manager,0x1800)', 'region(manager,0x6400)').replace('region(owner,1200000)', 'region(owner,0x280000)')
    fixture=fixture.replace('local grid=owner+523752','local grid=owner+0xd2f20')
    additions=r'''
local real=dofile('src/debug_armory.lua').decode
local old_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva,limit)
 if rva==0x18000 or rva==0x19000 then return real(raw,rva,limit)end
 return old_decode(raw,rva)
end
local function hex(s)return(s:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
put(base+0x18000,hex(ROUTE));put(base+0x19000,hex(SETTER))
bridge.deployment_picker_proven=true;bridge.session_global=base+0x50030
local session=0x700000;region(session,0x19000)
put(base+0x50030,b(session,8));put(session+0xb398,b(12345,8))
put(menu+0x4294,b(14,4));put(menu+0x429c,b(14,4))
put(manager+0x62a0,b(1,4)..b(0,4)..b(owner,8)..b(229,4))
put(owner+8,b(1,4));put(owner+0x273990,'\1');put(owner+0x2808,'\0')
put(owner+0x2818,b(3,4));put(owner+0x281c,b(0,4))
put(owner+0x9f8,b(12345,8))
put(owner+0x53a78+0x1edf0,b(owner+0x10,8)..b(5,4)..b(0,4))
put(grid+602052,b(4,4))
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
'''.replace('ROUTE','"'+ROUTE+'"').replace('SETTER','"'+SETTER+'"')
    extra=''
    if commit:
        fixture+=SELECTION+COMMIT.replace('region(players,512)','region(players,1024)')
        extra=r'''
put(local_player+8,b(5,4));put(base+0x50048,b(settings,8))
put(owner+0x10+0x12c,b(0x1234,4))
put(grid+0x92988,b(77,4));put(grid-0x6d0+0x178c88,b(0,4))
backend.executable=function()return true end
backend.write_armor=function(at,id)
 assert(at==owner+0x10+0x12c);armor_assignments=armor_assignments+1;put(at,b(id,4));return true
end
backend.deployment_commit=function(at,profile,player,id)
 assert(at==base+0x19000 and profile==settings and player==5 and id==0x5678)
 commits=commits+1;return true
end
'''
    result=subprocess.run(['luajit','-'],input=fixture+additions+extra+body,text=True,capture_output=True,cwd=ROOT)
    assert result.returncode==0,result.stdout+result.stderr


def test_equipment_picker_requires_local_identity_and_armor_context():
    run(r'''
local s,e=g:snapshot();assert(s and s.kind==4,e)
for _,change in ipairs({
 {owner+0x273990,'\0','\1'},
 {owner+0x2808,'\1','\0'},
 {owner+0x281c,b(1,4),b(0,4)},
 {owner+0x27d4,b(1,4),b(0,4)},
 {owner+0x9f8,b(333,8),b(12345,8)},
 {menu+0x429c,b(5,4),b(14,4)},
})do
 put(change[1],change[2]);assert(not g:snapshot(),'accepted changed Equipment identity')
 put(change[1],change[3]);assert(g:snapshot())
end
bridge.deployment_picker_proven=false;assert(not g:snapshot())
''')


def test_equipment_code_change_rejects_existing_picker():
    run(r'''
assert(g:snapshot())
put(base+0x19000,'\0');assert(not g:snapshot(),'changed native setter proof accepted')
''')


def test_equipment_commit_protects_payload_and_uses_native_armor_setter():
    run(r'''
local before=read(owner+0x10,0x9e0)
local snapshot,e=g:commit_snapshot(catalog);assert(snapshot,e)
assert(snapshot.local_player_id==5 and snapshot.controller_armor_id=='armor:00001234')
assert(g:commit_owned('armor:00005678',snapshot,catalog))
assert(commits==1 and armor_assignments==1)
assert(read(owner+0x10,0x9e0)==before:sub(1,0x12c)..b(0x5678,4)..before:sub(0x131))
''', commit=True)


def test_equipment_commit_refuses_readiness_and_stale_nonarmor_payload():
    run(r'''
put(players+0x3ac,b(8,4));assert(not g:commit_snapshot(catalog))
put(players+0x3ac,b(0,4))
local snapshot,e=g:commit_snapshot(catalog);assert(snapshot,e)
put(owner+0x10+0x124,b(123,4))
assert(not g:commit_owned('armor:00005678',snapshot,catalog))
assert(commits==0 and armor_assignments==0)
''', commit=True)


@pytest.mark.parametrize('replacement', [
    "put(session+0xb398,b(99999,8));put(owner+0x9f8,b(99999,8))",
    "local other=session+0x20000;region(other,0x19000);put(other+0xb398,b(12345,8));put(base+0x50030,b(other,8))",
    "put(owner+0x53a78+0x1edf0+8,b(6,4));put(local_player+8,b(6,4))",
    "put(players+0xe8,b(local_player+0x100,8))",
    "put(base+0x50048,b(settings+0x100,8))",
])
def test_equipment_rollback_refuses_reused_addresses_after_identity_changes(replacement):
    run(r'''
local snapshot,e=g:commit_snapshot(catalog);assert(snapshot,e)
local original_write=backend.write_armor
backend.write_armor=function(at,id)
 local result=original_write(at,id)
 if armor_assignments==1 then
 REPLACEMENT
 end
 return result
end
local ok,why=g:commit_owned('armor:00005678',snapshot,catalog)
assert(not ok and commits==0)
assert(armor_assignments==1,'rollback wrote into changed Equipment identity')
assert(read(owner+0x10+0x12c,4)==b(0x5678,4))
assert(why:find('recovery refused or unverified',1,true))
'''.replace('REPLACEMENT', replacement), commit=True)


def test_equipment_rollback_restores_assignment_when_original_identity_is_current():
    run(r'''
local snapshot,e=g:commit_snapshot(catalog);assert(snapshot,e)
local original_write=backend.write_armor
backend.write_armor=function(at,id)
 local result=original_write(at,id)
 if armor_assignments==1 then return false end
 return result
end
local ok,why=g:commit_owned('armor:00005678',snapshot,catalog)
assert(not ok and commits==0 and armor_assignments==2)
assert(read(owner+0x10+0x12c,4)==b(0x1234,4))
assert(not why:find('recovery refused or unverified',1,true))
''', commit=True)


def test_equipment_rollback_reports_failed_readback():
    run(r'''
local snapshot,e=g:commit_snapshot(catalog);assert(snapshot,e)
local original_write=backend.write_armor
backend.write_armor=function(at,id)
 if armor_assignments==0 then original_write(at,id);return false end
 armor_assignments=armor_assignments+1;return true -- Refused write despite successful return.
end
local ok,why=g:commit_owned('armor:00005678',snapshot,catalog)
assert(not ok and commits==0 and armor_assignments==2)
assert(read(owner+0x10+0x12c,4)==b(0x5678,4))
assert(why:find('recovery refused or unverified',1,true)and why:find('Equipment recovery failed',1,true))
''', commit=True)


def test_startup_refresh_uses_native_player_setter_without_menu_or_persistent_profile_writes():
    run(r'''
put(menu+0x4294,string.rep('\0',32))
local A,B='armor:00001234','armor:00005678'
local actor={session_key={},local_player_id=5,request_armor_id=A,cache_armor_id=A,cache_passive_enum=7,
 request={body_type=0,helmet_id='helmet',cape_id='cape'},current={body_type=0,helmet_id='helmet',cape_id='cape'}}
local player={sample=function()
 local out={};for k,v in pairs(actor)do out[k]=v end
 local id=actor.request_armor_id;out.verify=function()return actor.request_armor_id==id end
 return out
end}
local scene=true
local data={armor_catalog=base+0x50048,verify=function()return true end}
local parent_profile=read(owner+0x10,0x140)
backend.deployment_commit=function(at,profile,player_id,item)
 assert(at==base+0x19000 and profile==settings and player_id==5 and item==0x5678)
 commits=commits+1;actor.request_armor_id=B;return true
end
local runtime,why=g:player_refresh_bridge(player,catalog,data,function()return scene end)
assert(runtime,why)
local state=assert(runtime.snapshot());assert(runtime.verify(state))
assert(runtime.commit_owned(B,state))
assert(commits==1 and armor_assignments==0 and read(owner+0x10,0x140)==parent_profile)
assert(not runtime.verify(state))
local current=assert(runtime.snapshot());assert(current.profile_armor_id==B and current.cache_armor_id==A)
scene=false;assert(not runtime.verify(current)and not runtime.snapshot())
''',commit=True)


def test_startup_setter_refuses_manager_mismatch_or_open_menu():
    run(r'''
local data={armor_catalog=base+0x50040,verify=function()return true end}
assert(not g:player_refresh_bridge({},catalog,data,function()return true end))
data.armor_catalog=base+0x50048
local runtime=assert(g:player_refresh_bridge({},catalog,data,function()return true end))
assert(not runtime.snapshot(),'an open Equipment menu must block startup changes')
assert(commits==0 and armor_assignments==0)
''',commit=True)


def test_inactive_deployment_picker_is_outside_input_scope_not_a_capture_failure():
    run(r'''
put(grid-0x6d0+0x178c88,string.rep('\0',16))
assert(g:input_scope()==true)
put(owner+0x2818,b(0,4));assert(g:input_scope()==false)
assert(not g:snapshot(),'normal native operations must still reject inactive equipment')
put(owner+0x2818,b(3,4));assert(g:input_scope()==true)
put(manager+0x62a0,b(0,4));assert(g:input_scope()==false)
''')
