"""A DiverKit loadout bridge reuses verified Lua plans and protects other gear."""
from test_diverkit_compat import run

FIXTURE = r'''
local B=dofile('src/diverkit_bridge.lua')
local Refresh=dofile('src/armor_refresh.lua')
local Session=dofile('src/variant_session.lua')
local A,C,D='armor:00000001','armor:00000003','armor:00000004'
local token='loadout';local key={}
local live={armor='0x00000001',profile='0x00000001',request=A,cache=A,passive=7,
 primary='0x00000011',helmet='armor:00000021',cape='armor:00000022'}
local native_calls,write_calls=0,0
local authorized=true;local changed=false;local fail_commit=false
local catalog={owned={[A]=true,[C]=true,[D]=true},catalog={
 [A]={appearance_id=A,stats_id='stats-a',passive_variant_id='perk-b'},
 [C]={appearance_id=C,stats_id='stats-c',passive_variant_id='perk-a'},
 [D]={appearance_id=D,stats_id='stats-d',passive_variant_id='perk-b'}},
 context={passive_variants={['perk-a']={enum=1},['perk-b']={enum=7}}}}
function catalog.verify_owned(ids)
 for _,id in ipairs(ids)do if not authorized or not catalog.owned[id]then return false end end;return true
end
local function capture()
 return {armor=live.armor,primary=live.primary,pistol='0x00000012',grenade='0x00000013',
 helmet='0x00000021',cape='0x00000022',title='0x00000000',player_card='0x00000000',booster='0x00000000',
 stratagems={{enum=0,key='none'},{enum=0,key='none'},{enum=0,key='none'},{enum=0,key='none'}}}
end
local function clone(t)local out={};for k,v in pairs(t)do out[k]=v end;return out end
local info={player=1,payload=10000,card=20000,mode=false}
local api={}
function api.session()assert(not changed,'screen changed');return token,info end
function api.profile_differences(_,captured)
 return captured.armor==live.profile and {}or {'profile armor'}
end
function api.bind()
 return {write_gear=function(_,_,id)write_calls=write_calls+1;live.armor=string.format('0x%08x',id)end,
 armor=function(_,player,id)assert(player==1);native_calls=native_calls+1;live.request=string.format('armor:%08x',id)end,
 commit=function()if fail_commit then error('native commit failed')end;live.profile=live.armor end,
 refresh=function()end}
end
function api.preflight(_,_,target,current,mask)
 assert(mask.armor==true and not mask.helmet)
 local gear={}
 if target.armor~=current.armor then gear[1]={spec={name='armor',offset=12},id=tonumber(target.armor:sub(3),16),before=current.armor}end
 return {token=token,info=info,catalog={},weapons={},gear=gear,stratagem_changed=false,extras={changes={}}}
end
local player={}
function player:sample()
 local before=table.concat({live.request,live.cache,live.passive,live.helmet,live.cape},'|')
 local function gear()return {body_type=0,helmet_id=live.helmet,cape_id=live.cape}end
 return {local_player_id=1,session_key=key,request=gear(),current=gear(),request_armor_id=live.request,
 cache_armor_id=live.cache,cache_passive_enum=live.passive,settled=live.request==live.cache,
 verify=function()return before==table.concat({live.request,live.cache,live.passive,live.helmet,live.cape},'|')end}
end
local driver={context={},apply=api,model={copy_snapshot=clone},capture=capture,report=function()end}
local bridge=B.new(driver,player,catalog)
local applied,patch_resets=nil,0
local host={catalog=function()return catalog end,player=function()return player:sample()end,
 validate_composition=function()return true end,
 new_refresh=function(background,external)assert(background and external==bridge);return Refresh.new(external)end,
 new_patch=function()
  local active=false
  return {plan=function(_,_,r)return {request=clone(r),target_id=r.appearance_id,source_id=r.appearance_id}end,
   apply=function(_,plan)
    assert(live.request~=plan.target_id and live.cache~=plan.target_id,'rewrote a worn carrier')
    applied=clone(plan.request);active=true;return true
   end,
   reset=function()
    assert(not applied or live.request~=applied.appearance_id and live.cache~=applied.appearance_id,'reset a worn carrier')
    applied=nil;active=false;patch_resets=patch_resets+1;return true
   end,is_active=function()return active end}
 end}
local session=Session.new(host)
local function settle(now)
 live.cache=live.request
 live.passive=applied and applied.appearance_id==live.cache and catalog.context.passive_variants[applied.passive_variant_id].enum
  or catalog.context.passive_variants[catalog.catalog[live.cache].passive_variant_id].enum
 session:step(now)
end
local function apply(label,r,start,original)
 assert(session:external_begin(label,r,start,bridge,original))
 for n=1,10 do settle(start+n)end
 assert(session.external_status=='complete',session.external_error)
end
'''


def test_same_look_switch_releases_carrier_and_verifies_full_composition():
    run(FIXTURE+r'''
local first={appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'}
apply('First',first,0)
assert(native_calls==2 and applied.stats_id=='stats-c'and live.passive==1)
local saved=assert(session:export_equipped(A));assert(saved.label=='First')
local second={appearance_id=A,stats_id='stats-d',passive_variant_id='perk-b'}
apply('Second',second,20)
assert(native_calls==4 and patch_resets==1 and applied.stats_id=='stats-d'and live.passive==7)
assert(session:export_equipped(A).label=='Second')
assert(live.primary=='0x00000011'and live.helmet=='armor:00000021'and live.cape=='armor:00000022')
''')


def test_different_look_then_ordinary_armor_restores_original_records():
    run(FIXTURE+r'''
apply('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},0)
apply('Other',{appearance_id=D,stats_id='stats-c',passive_variant_id='perk-a'},20)
assert(applied.appearance_id==D and live.request==D and live.passive==1)
assert(session:export_equipped(D).label=='Other')
apply(nil,catalog.catalog[D],40,true)
assert(applied==nil and live.request==D and live.passive==7)
assert(session:export_equipped(D)==false)
''')


def test_tampered_snapshot_or_changed_ownership_cannot_commit():
    run(FIXTURE+r'''
local s=assert(bridge.snapshot());s.profile_armor_id=D
assert(not bridge.verify(s))
assert(not pcall(bridge.commit_owned,D,s)and write_calls==0)
s=assert(bridge.snapshot());authorized=false
assert(not pcall(bridge.commit_owned,D,s)and write_calls==0)
''')


def test_context_change_and_commit_failure_fail_without_false_equipped_state():
    run(FIXTURE+r'''
local recipe={appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'}
assert(session:external_begin('First',recipe,0,bridge))
changed=true;session:step(1)
assert(session.external_status=='failed'and native_calls==0 and applied==nil)
changed=false;fail_commit=true
assert(session:external_begin('First',recipe,2,bridge))
session:step(3)
assert(session.external_status=='failed'and native_calls==1 and applied==nil)
assert(not session:export_equipped(A))
''')


def test_other_equipment_change_during_operation_stops_before_patch():
    run(FIXTURE+r'''
assert(session:external_begin('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},0,bridge))
session:step(1);assert(native_calls==1)
live.primary='0x00000099';settle(2)
assert(session.external_status=='failed'and applied==nil)
''')


def test_cancelled_external_operation_is_not_advanced_or_reset_when_worn():
    run(FIXTURE+r'''
assert(session:external_begin('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},0,bridge))
session:external_cancel('left loadout')
settle(1);assert(native_calls==0 and applied==nil and session.external_status=='failed')
apply('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},10)
local record=session:export_equipped(A);assert(record.label=='First')
assert(session:external_begin('Other',{appearance_id=D,stats_id='stats-c',passive_variant_id='perk-a'},30,bridge))
session:external_cancel('left loadout')
assert(applied.appearance_id==A and live.request==A and not session:busy())
''')



def test_external_bridge_failure_does_not_leave_the_session_locked():
    run(FIXTURE+r"""
local original=host.new_refresh
host.new_refresh=function()error('bridge unavailable')end
local ok,why=session:external_begin('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},0,bridge)
assert(not ok and why:find('bridge unavailable')and session.external_status=='failed')
assert(not session:busy()and not session:restoring()and native_calls==0)
host.new_refresh=original
apply('First',{appearance_id=A,stats_id='stats-c',passive_variant_id='perk-a'},1)
assert(session:export_equipped(A).label=='First')
""")
