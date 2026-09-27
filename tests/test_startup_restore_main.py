"""Actual main + session startup restoration with a synthetic native backend."""
from pathlib import Path
import subprocess
from test_creator_failure_main import HARNESS, ROOT

SEED=r'''
local A,B,C='armor:00000001','armor:00000002','armor:00000003'
local recipe={appearance_id=A,stats_id='stats-b',passive_variant_id='perk-a'}
catalog={[A]={appearance_id=A,stats_id='stats-a',passive_variant_id='perk-b'},
 [B]={appearance_id=B,stats_id='stats-b',passive_variant_id='perk-b'},
 [C]={appearance_id=C,stats_id='stats-c',passive_variant_id='perk-a'}}
result.catalog=catalog;result.owned={[A]=true,[B]=true,[C]=true};result.counts.owned_armors=3
result.context.passive_variants={['perk-a']={enum=1},['perk-b']={enum=7}}
result.verify_owned=function(ids)for _,id in ipairs(ids)do if not result.owned[id]then return false end end;return true end
local saved=State.new{catalog=catalog,owned=result.owned};saved.presets.Saved=recipe
files['transmog.state']='HD2TRANSMOG_UI\t1\nappearance\n'..assert(State.encode(saved))
local E=dofile('src/equipped_state.lua')
files['equipped.state']=assert(E.encode(State,'Saved',recipe))
local persisted_ordinary_armor=A
local active_ship=true;local commits,patches=0,0
local live={session='actor',other_key='helmet/cape',pending_nonarmor=false,
 controller_armor_id=A,profile_armor_id=A,request_armor_id=A,cache_armor_id=A,cache_passive=7}
local player={sample=function()return {request_armor_id=live.request_armor_id,cache_armor_id=live.cache_armor_id,
 cache_passive_enum=live.cache_passive,settled=live.request_armor_id==live.cache_armor_id}end}
PlayerCustomizationProbe={new=function()return player end}
ArmorRefresh=dofile('src/armor_refresh.lua');ArmorRefreshBridge={}
VariantSession=dofile('src/variant_session.lua')
RuntimeWriter={new=function()return {}end}
local compatible=true
AppearancePatch={compatible=function()return compatible, 'changed definition'end,
 new=function()
  local patch={active=false}
  function patch:plan(_,r)return {source_id=A,target_id=A,request=r}end
  function patch:apply()assert(live.request_armor_id~=A and live.cache_armor_id~=A);patch.active=true;patches=patches+1;return true end
  function patch:reset()patch.active=false;return true end
  function patch:is_active()return patch.active end
  return patch
 end}
local runtime_bridge={capabilities={commit_verified=true,cache_layout_verified=true}}
function runtime_bridge.snapshot()local out={};for k,v in pairs(live)do out[k]=v end;return out end
function runtime_bridge.verify(snapshot)for k,v in pairs(snapshot)do if live[k]~=v then return false end end;return active_ship end
runtime_bridge.verify_owned=result.verify_owned
function runtime_bridge.owned_armors()return {A,B,C}end
function runtime_bridge.commit_owned(id,snapshot)
 assert(runtime_bridge.verify(snapshot))
 assert(E.decode(State,files['equipped.state'])==false,'startup intent was not durably cleared before mutation')
 commits=commits+1;live.controller_armor_id=id;live.profile_armor_id=id;live.request_armor_id=id;return true
end
function grid:idle_menu()return active_ship end
function grid:player_refresh_bridge(_,_,_,guard)assert(guard());return runtime_bridge end
stingray.Application={main_world=function()return 'ship'end,worlds=function()return {'ship'}end}
stingray.World={units_by_resource=function()return active_ship and {'unit'}or{}end}
stingray.IdString64={from_hex=function(v)return v end};stingray.Unit={alive=function()return true end}
sample_mode='exit'
local function tick_ship()
 now=now+100;update()
 live.cache_armor_id=live.request_armor_id;live.cache_passive=live.request_armor_id==A and 1 or 7
end
'''


def run(body, before=''):
    script=HARNESS+SEED+before+'\nlocal function boot()\n'+(ROOT/'src/main.lua').read_text()+'''
end
local runtime=boot();assert(runtime.status~='startup_failed',runtime.status)
now=16000
'''+body
    p=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=15)
    assert p.returncode==0,p.stdout+p.stderr


def test_startup_restores_without_opening_armory_and_keeps_an_uninstall_safe_native_id():
    run(r'''
for i=1,30 do tick_ship()end
assert(commits==2 and patches==1 and runtime.armor_writes)
assert(logged_count('variant.restored=')==1 and logged_count('restore.result=complete')==1)
assert(logged_count('screen.detected=')==0 and wizard_draws==0)
assert(E.decode(State,files['equipped.state']).label=='Saved')
assert(persisted_ordinary_armor==A,'startup changed persistent native armor identity')
assert(logged_count('runtime.error=')==0)
''')


def test_unknown_broken_deleted_or_unowned_variant_never_changes_native_armor():
    for before in [
        "compatible=false",
        "result.owned[B]=false",
        "saved.presets.Saved=nil;files['transmog.state']='HD2TRANSMOG_UI\\t1\\nappearance\\n'..assert(State.encode(saved))",
        "files['equipped.state']='corrupt'",
        "live.request_armor_id=B;live.controller_armor_id=B;live.profile_armor_id=B;live.cache_armor_id=B",
    ]:
        # Lua source needs real escape sequences, not doubled Python escaping.
        run(r'''
for i=1,30 do tick_ship()end
assert(commits==0 and patches==0 and persisted_ordinary_armor==A)
assert(logged_count('runtime.error=')==0)
''',before.replace('\\\\','\\')+'\n')


def test_leaving_ship_during_restore_stops_once_without_persistent_replay():
    run(r'''
for i=1,30 do tick_ship();if commits==1 then break end end
assert(commits==1);active_ship=false
for i=1,5 do tick_ship()end
assert(commits==1 and patches==0 and E.decode(State,files['equipped.state'])==false)
assert(logged_count('restore.result=failed')==1 and logged_count('runtime.error=')==0)
active_ship=true;for i=1,30 do tick_ship()end
assert(commits==1 and patches==0)
''')


def test_broken_restore_adapter_is_isolated_from_normal_mod_runtime():
    run(r'''
for i=1,30 do tick_ship()end
assert(commits==0 and patches==0 and logged_count('restore.skipped=')==1)
assert(logged_count('runtime.error=')==0)
''',"AppearancePatch.compatible=function()error('unsupported composition evidence')end\n")
