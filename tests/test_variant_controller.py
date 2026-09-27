"""Real main-controller events with synthetic catalog/patch/input backends."""
from pathlib import Path
from test_runtime import run_lua

ROOT = Path(__file__).resolve().parents[1]


def controller_fixture(body):
    main = (ROOT/'src/main.lua').read_text()
    return '''
local State=dofile('src/state.lua')
local files,logs,events={}, {}, {}
local now=0
local input={x=10,y=10,down=false}
local target,visible,inside=nil,true,true
local consume_ok,reset_ok=true,true
local consumed,applied,resets=0,0,0
local last_view
local catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
 b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}}
local initial=State.new{catalog=catalog,owned={a=true,b=true}}
initial.presets.Alpha={appearance_id='look-a',stats_id='stats-b',passive_variant_id='perk-a'}
initial.presets.Beta={appearance_id='look-b',stats_id='stats-a',passive_variant_id='perk-b'}
initial.requested=initial.presets.Alpha
files['transmog.state']='HD2TRANSMOG_UI\\t1\\nappearance\\n'..assert(State.encode(initial))
local Platform={new=function()return {
 now=function()return now end,sample_input=function()return input end,
 read=function(name)return files[name],files[name]and nil or 'missing'end,
 write_atomic=function(name,value)files[name]=value;return true end,
}end}
local Adapter={new=function()return {
 phase='ready',pe_timestamp=1,step=function()return 'ready'end,
 data_bridge=function()return {}end,debug_bridge=function()return {}end,
 sample=function()if visible then return {kind='armory',token='screen',anchor={x=0,y=0,w=10,h=10}}end end,
}end}
local CatalogData,CatalogCompat={},{}
local CatalogProbe={new=function()return {step=function()return 'ready',{
 catalog=catalog,owned={a=true,b=true},source_commit='fixture',counts={kits=2,owned_armors=2},
 context={labels={appearance_id={},stats_id={},passive_variant_id={}}},
}end}end}
local Panel={new=function()return {
 clear=function()end,hit=function()return target end,capture=function()return inside end,
 draw=function(_,sample,view)
  last_view={open=view.open,label=view.editor.label,dirty=view.editor.dirty,active=view.editor.patch_active}
  return true
 end,
}end}
local NativeGrid={new=function()return {
 phase='ready',snapshot=function()return {native_category=1,identity_mapping_verified=false,appearance_previews={}}end,
 layout_active=function()return false end,release_view=function()return true end,
 consume_select=function()
  consumed=consumed+1;events[#events+1]='consume'
  if not consume_ok then return nil,'fixture input refusal'end
  return true
 end,
}end}
local RuntimeWriter={new=function()return {}end}
local AppearancePatch={new=function()
 local active,name=false,nil
 return {
 plan=function(_,result,request)
  assert(not active);events[#events+1]='plan:'..request.appearance_id
  return {request=request}
 end,
 apply=function(_,plan)
  assert(not active);active=true;name=plan.request.appearance_id;applied=applied+1
  events[#events+1]='apply:'..name
  return true,{status='memory_readback_verified',source_id=name,target_id=plan.request.stats_id}
 end,
 reset=function()
  resets=resets+1;events[#events+1]='reset:'..tostring(name)
  if not reset_ok then return nil,'fixture reset conflict'end
  active=false;return true,{status='original_memory_restored'}
 end,
 is_active=function()return active end,
 }
end}
stingray={Gui={resolution=function()return 1920,1080 end}}
CowboyBingusModLoader={api=1,open_log=function()return {
 write=function(_,line)logs[#logs+1]=line end,flush=function()end,close=function()end,
}end}
local function boot()
''' + main + '''
end
assert(boot().status~='startup_failed')
now=16000;update();update()
local function click(key)
 target=key;input.down=true;update();input.down=false;update();update()
end
''' + body


def test_saved_selection_resets_active_variant_before_switch_and_new_opens_editor():
    run_lua(controller_fixture('''
click(State.variant_action('Alpha'))
assert(applied==1 and resets==0 and last_view.label=='Alpha' and not last_view.open)
click(State.variant_action('Beta'))
assert(applied==2 and resets==1 and last_view.label=='Beta' and not last_view.open)
assert(table.concat(events,'|'):find('reset:look%-a|plan:look%-b|apply:look%-b'))
click(State.variant_action('Beta',true))
assert(applied==2 and resets==2 and last_view.open and not last_view.active)
click('new_variant')
assert(last_view.open and last_view.dirty and applied==2)
'''))


def test_failed_reset_never_applies_new_selection():
    run_lua(controller_fixture('''
click(State.variant_action('Alpha'));reset_ok=false
click(State.variant_action('Beta'))
assert(applied==1 and resets==1 and last_view.active)
assert(table.concat(logs,''):find('variant.select_error',1,true))
'''))


def test_capture_survives_pointer_exit_and_focus_loss_until_release_without_action():
    run_lua(controller_fixture('''
target=State.variant_action('Alpha');input.down=true;update()
local before=consumed
inside=false;target=nil;update()
assert(consumed>before)
input.down=false;before=consumed;update();assert(consumed>before and applied==0)
inside=true;target=State.variant_action('Alpha');input.down=true;update()
input=nil;before=consumed;update();assert(consumed>before)
input={x=10,y=10,down=false};before=consumed;update();update()
assert(consumed>before and applied==0)
'''))


def test_failed_latched_release_cancels_variant_action():
    run_lua(controller_fixture('''
target=State.variant_action('Alpha');input.down=true;update()
consume_ok=false;input.down=false;update()
assert(applied==0,'failed native input capture must cancel the armed action')
consume_ok=true;update();update()
assert(applied==0,'late successful release must not replay the cancelled action')
'''))
