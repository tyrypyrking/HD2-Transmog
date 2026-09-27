"""Controller-level checks for durable saves and fresh catalog authorization."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_editor_save_is_transactional_and_catalog_refresh_gates_creation():
    main = (ROOT / "src/main.lua").read_text()
    script = r"""
local now, target, held, reject_save = 0,nil,false,false
local files,last_view={},nil
local State=dofile('src/state.lua')
local CatalogData,CatalogCompat={},{}
local result={
 catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
          b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}},
 owned={a=true,b=true},context={},source_commit='fixture',
 counts={kits=2,owned_armors=2}}
local probe_ready=false
local CatalogProbe={new=function()return {step=function()
 if probe_ready then return 'ready',result end
 return 'resolving'
end}end}
local Adapter={new=function(_,_,_,_,kind)
 if kind=='catalog' then return {
   step=function()return 'ready'end,data_bridge=function()return {}end,pe_timestamp=1}end
 return {phase='ready',sample=function()return {token='armory'}end}
end}
local Panel={new=function()return {
 clear=function()end,hit=function()return target end,
 draw=function(_,_,view)last_view=view;return true end}end}
local Platform={new=function()return {
 now=function()return now end,
 read=function(name)return files[name],files[name] and nil or 'missing'end,
 sample_input=function()return {x=0,y=0,down=held}end,
 write_atomic=function(name,bytes)
  if name=='transmog.state' and reject_save then return nil,'disk rejected'end
  files[name]=bytes;return true
 end}end}
stingray={}
CowboyBingusModLoader={api=1}
local function boot()
""" + main + r"""
end
boot();now=16000;update()
assert(last_view.editor.can_new==false)
probe_ready=true;update()
assert(last_view.editor.can_new==true)
local function click(key)
 target=key;held=true;update();held=false;update();update()
end
click('new_variant')
assert(last_view.editor.can_save)
local label=last_view.editor.label
reject_save=true;click('save_variant')
assert(not files['transmog.state'])
assert(last_view.editor.dirty and last_view.editor.saved_count==0)
reject_save=false;click('save_variant')
assert(not last_view.editor.dirty and last_view.editor.saved_count==1)
local payload=assert(files['transmog.state']:match('^HD2TRANSMOG_UI\t1\n[a-z]+\n(.*)$'))
local saved=assert(State.decode(payload))
assert(saved.presets[label] and saved.requested)
assert(not saved.ownership_verified and saved.selected==nil)
local before=files['transmog.state']
click('duplicate_variant');reject_save=true;click('save_variant')
assert(files['transmog.state']==before and last_view.editor.saved_count==1)
"""
    result = subprocess.run(["luajit", "-"], input=script, text=True,
                            capture_output=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


def test_debug_catalog_cannot_skip_fresh_armory_entry_or_activate_hidden_controls():
    main = (ROOT / 'src/main.lua').read_text()
    script = r'''
local now,target,held,active=0,nil,false,false
local files,last_view={},nil
local request,ack,request_error
local real_state=dofile('src/state.lua')
local domain
local State=setmetatable({},{__index=real_state})
State.new=function(...)
 domain=real_state.new(...);return domain
end
local generation,probe_ready,draws,apply_calls=0,true,0,0
local patch_applied=false
local CatalogData,CatalogCompat={},{}
local CatalogLabels={strings={[123]='English fallback',[124]='English duplicate'}}
local Localization={bind=function()return function(key)if key==124 then return 'Native name'end end end}
local function observation(generation)
 return {
  generation=generation,source_commit='fixture',counts={kits=2,owned_armors=2},
  catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
           b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}},
  owned={a=true,b=true},
  context={labels={appearance_id={},stats_id={},passive_variant_id={}}},
 }
end
local CatalogProbe={new=function(bridge)
 assert(bridge.localize(123)=='English fallback')
 assert(bridge.localize(124)=='Native name')
 assert(bridge.localize(125)==nil)
 generation=generation+1
 local result=observation(generation)
 return {step=function()if probe_ready then return 'ready',result end return 'resolving'end}
end}
local Adapter={new=function(_,_,_,_,kind)
 if kind=='catalog' then return {
  step=function()return 'ready'end,data_bridge=function()return {}end,pe_timestamp=1}end
 return {phase='ready',sample=function()if active then return {token='native-armory'}end return nil,'not ship Armory'end}
end}
local DebugBridge={new=function()return {poll=function(_,handlers)
 if request then
  local command=request;request=nil
  local ok,value=pcall(handlers[command]);ack=ok and value or nil;request_error=not ok and value or nil
 end
end}end}
local RuntimeWriter={new=function(_,result)return {generation=result.generation}end}
local AppearancePatch={new=function(writer)return {
 plan=function(_,result)
  assert(result.generation==writer.generation)
  assert(domain.ownership_verified)
  return {generation=result.generation}
 end,
 apply=function(_,plan)
  assert(active,'hidden UI activated a preview')
  assert(plan.generation==generation,'old catalog activated a preview')
  apply_calls=apply_calls+1;patch_applied=true
  return true,{status='memory_readback_verified',source_id='a',target_id='b'}
 end,
 is_active=function()return patch_applied end,
 reset=function()patch_applied=false;return true,{status='original_memory_restored'}end,
}end}
local Panel={new=function()return {
 clear=function()end,hit=function()return target end,
 draw=function(_,_,view)draws=draws+1;last_view=view;return true end,
}end}
local Platform={new=function()return {
 now=function()return now end,
 read=function(name)return files[name],files[name] and nil or 'missing'end,
 sample_input=function()return {x=0,y=0,down=held}end,
 write_atomic=function(name,bytes)files[name]=bytes;return true end,
}end}
stingray={};CowboyBingusModLoader={api=1}
local function boot()
''' + main + r'''
end
boot();now=16000
request='read_catalog';update()
assert(ack and not request_error and generation==1 and draws==0 and apply_calls==0)
assert(files['catalog-observed.txt'],'debug diagnostic was not published')
-- Entering the native Armory must discard that diagnostic snapshot and reacquire.
probe_ready=false;active=true;update()
assert(generation==2 and not domain.ownership_verified and last_view.editor.can_new==false)
probe_ready=true;update()
assert(domain.ownership_verified and last_view.editor.can_new)
local function click(key)
 target=key;held=true;update();held=false;update();update()
end
click('new_variant');assert(last_view.editor.can_apply)
-- An armed press followed by leaving Armory cannot apply on release.
target='apply_variant';held=true;update();active=false;held=false;update()
assert(apply_calls==0)
-- A fresh entry invalidates the previous plan and waits for a new catalog.
probe_ready=false;active=true;update()
assert(generation==3 and not domain.ownership_verified and not last_view.editor.can_apply)
probe_ready=true;update();assert(last_view.editor.can_apply)
click('apply_variant');assert(apply_calls==1 and last_view.editor.patch_active)
-- Preserve active rollback evidence across screen changes; block catalog refresh.
active=false;update();active=true;update();assert(generation==3)
request='read_catalog';update()
assert(not ack and request_error:find('Reset the preview') and generation==3)
click('reset_variant');assert(not patch_applied)
'''
    process = subprocess.run(['luajit','-'], input=script, text=True,
                             capture_output=True, cwd=ROOT, timeout=10)
    assert process.returncode == 0, process.stdout + process.stderr
