"""Actual main + workflow + wizard regression for a failed native input guard."""
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''
local State=dofile('src/state.lua')
local RealWizard=dofile('src/variant_wizard.lua')
local RealWorkflow=dofile('src/ui_workflow.lua')
local ArmorySection=dofile('src/armory_section.lua')
local now=0
local files,logs={},{}
local input={x=100,y=100,down=false}
local command_name,command_payload,command_ok,command_result
local consume_mode='ok';local consume_count=0;local native_updates=0;local polls=0
local save_count,cancel_count,leave_count,before_count,preview_count=0,0,0,0,0
local legacy_draws,wizard_draws=0,0
local presentation_active=false;local presentation_builds,presentation_restores=0,0
local restore_mode='ok';local panel_target
local sample_mode,grid_mode,presentation_attempt_mode='ready','ready','ok'
local inspect_mode,select_mode,menu_token='ready','ready','menu-one'
local release_views=0
local flow,host
local triple_a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
local triple_b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}
local catalog={a=triple_a,b=triple_b}
local domain=State.new{catalog=catalog,owned={a=true,b=true}}
domain.requested=triple_a;domain.selected=triple_a;domain.presets.Existing=triple_a
local saved_before='HD2TRANSMOG_UI\t1\nappearance\n'..assert(State.encode(domain))
files['transmog.state']=saved_before
local result={catalog=catalog,owned={a=true,b=true},source_commit='fixture',counts={kits=2,owned_armors=2},
 verify_owned=function()return true end,
 context={labels={appearance_id={},stats_id={},passive_variant_id={}},passive_variants={},
  stats_profiles={['stats-a']={base_only=true,base_values_verified=true,base_values={armor_rating=50,speed=550,stamina_regen=125}},
   ['stats-b']={base_only=true,base_values_verified=true,base_values={armor_rating=100,speed=500,stamina_regen=100}}}}}
local Platform={new=function()return {
 now=function()return now end,sample_input=function()return input end,
 read=function(name)return files[name],files[name]and nil or 'missing'end,
 write_atomic=function(name,value)
  if name=='transmog.state'then save_count=save_count+1 end
  files[name]=value;return true
 end}end}
local Adapter={new=function()return {
 phase='ready',pe_timestamp=1,step=function()return 'ready'end,data_bridge=function()return {}end,
 debug_bridge=function()return {}end,
 sample=function()
  if sample_mode=='unreadable'then return nil,'Armory state unreadable'end
  if sample_mode=='exit'then presentation_active=false;return nil,'not ship Armory'end
  return {kind='armory',token=menu_token,anchor={x=0,y=0,w=10,h=10}}
 end}end}
local CatalogData,CatalogCompat={},{}
local CatalogProbe={new=function()return {step=function()return 'ready',result end}end}
local Panel={new=function()return {
 clear=function()end,draw=function()legacy_draws=legacy_draws+1;return true end,
 capture=function()return false end,hit=function()return nil end}end}
local WizardPanel={new=function()return {
 clear=function()end,draw=function()wizard_draws=wizard_draws+1;return true end,
 hit=function()return panel_target end,capture=function()return panel_target~=nil end,
 handle=function()return false end,input_policy=function()return {}end}end}
local VariantWizard={display_name=RealWizard.display_name,new=function(api,policy)
 local wizard=RealWizard.new(api,policy);local action=wizard.action
 wizard.action=function(self,domain,context,value)
  if value and value.type=='cancel'then cancel_count=cancel_count+1 end
  return action(self,domain,context,value)
 end
 return wizard
end}
local UiWorkflow={new=function(state,wizard,panel,actual_host)
 host=actual_host;flow=RealWorkflow.new(state,wizard,panel,actual_host)
 local before,leave=flow.before,flow.leave
 flow.before=function(self,value)before_count=before_count+1;return before(self,value)end
 flow.leave=function(self)leave_count=leave_count+1;return leave(self)end
 return flow
end}
local grid={phase='ready'}
function grid:input_scope()return sample_mode~='exit'and grid_mode~='other_kind'and grid_mode~='other_mode'end
function grid:snapshot()
 if grid_mode=='unreadable'then return nil,'fixture grid observation changed'end
 if grid_mode=='other_kind'or grid_mode=='other_mode'then presentation_active=false end
 return {kind=grid_mode=='other_kind'and 5 or 4,native_view_mode=grid_mode=='other_mode'and 1 or 0,
  identity_mapping_verified=grid_mode~='mapping'and grid_mode~='other_mode',selected_kit_id='a',
  appearance_previews={},widgets={},headers={},scroll=0,logical_selected_index=0,
  item_count=presentation_active and 4 or 2}
end
function grid:consume_select()
 consume_count=consume_count+1
 if consume_mode=='throw'then error('proof span consume changed')end
 if consume_mode=='refuse'then return nil,'proof span consume changed'end
 return true
end
function grid:select_kit()
 preview_count=preview_count+1
 if select_mode~='ready'then return nil,'native selection not ready'end
 return {status='native_highlight_readback_verified'}
end
grid.preview_kit=grid.select_kit
grid.preview_variant_details=grid.select_kit
function grid:selection_index()return 0 end
function grid:release_view()release_views=release_views+1;return true end
function grid:inspect_model()
 if inspect_mode~='ready'then return nil,'native list not ready'end
 return {item_count=2,offers={{kit_id='look-a',owned=true},{kit_id='look-b',owned=true}}}
end
function grid:presentation_bridge()return {}end
local NativeGrid={new=function()return grid end}
local NativeGridPresentation={new=function()
 local object={phase='idle'}
 function object:attempt(cards)
  presentation_builds=presentation_builds+1
  if presentation_attempt_mode=='fail'then
   presentation_active=false;self.phase='restored';return {phase='restored',error='fixture construction verification failed'}
  end
  if presentation_attempt_mode=='waiting'then
   presentation_active=false;self.phase='waiting';return {phase='waiting',error='native row not ready',retryable=true}
  end
  presentation_active=true;self.phase='active'
  assert(#cards==2);return {phase='active'}
 end
 function object:restore()
  presentation_restores=presentation_restores+1
  if restore_mode=='throw'then error('fixture restoration refusal')end
  if restore_mode=='refuse'then self.phase='restore_failed';return {phase='restore_failed',error='fixture restoration refusal'}end
  presentation_active=false;self.phase='restored';return {phase='restored'}
 end
 return object
end}
local DebugBridge={new=function()return {
 inspect=function()return 'debug still usable'end,
 poll=function(_,handlers)
  polls=polls+1
  if command_name then
   local name,payload=command_name,command_payload;command_name=nil
   command_ok,command_result=pcall(handlers[name],payload or '')
  end
 end}end}
stingray={Gui={resolution=function()return 1920,1080 end}}
CowboyBingusModLoader={api=1,open_log=function()return {
 write=function(_,line)logs[#logs+1]=line end,flush=function()end,close=function()end}end}
update=function()native_updates=native_updates+1;return 'native',nil,42 end
local function logged_count(fragment)
 local total=0;for _,line in ipairs(logs)do if line:find(fragment,1,true)then total=total+1 end end;return total
end
local function advance()
 now=now+100
 return update()
end
local function command(name,payload)
 command_name,command_payload=name,payload;advance();return command_ok,command_result
end
'''


def run(body, *, automatic=False, setup='', stats_follow_look=False, passive_icons=True, helmet_transmog=False):
    main=(ROOT/'src/main.lua').read_text()
    if helmet_transmog:
        main=main.replace('local HELMET_TRANSMOG = false', 'local HELMET_TRANSMOG = true', 1)
    if stats_follow_look:
        main=main.replace('local STATS_FOLLOW_LOOK = false', 'local STATS_FOLLOW_LOOK = true', 1)
    if not passive_icons:
        main=main.replace('local PASSIVE_PREVIEW_ICONS = true', 'local PASSIVE_PREVIEW_ICONS = false', 1)
    script=HARNESS+'\nlocal function boot()\n'+main+'''
end
local runtime=boot();assert(runtime.status~='startup_failed',runtime.status)
runtime.automatic_custom_ui='''+('true' if automatic else 'false')+'\n'+setup+'''
now=16000;update();update()
''' + body
    proc=subprocess.run(['luajit','-'],input=script,text=True,capture_output=True,cwd=ROOT,timeout=15)
    assert proc.returncode==0,proc.stdout+proc.stderr


@pytest.mark.parametrize('failure',['refuse','throw'])
def test_capture_failure_on_armed_create_release_cancels_once_and_does_not_persist(failure):
    run('''
assert(command('open_creator'));assert(flow:view().open)
assert(flow:action{type='select_look',id='look-b'})
assert(flow:action{type='select_stats',id=flow:view().options[1].id})
assert(flow:action{type='select_passive',id='perk-b'})
assert(flow:view().can_create and save_count==0)
panel_target={type='create'};input.down=true;advance() -- Arm actual workflow's Create.
local old_native,old_polls=native_updates,polls
command_name='ui_status';command_payload=''
consume_mode='''+repr(failure)+''';input.down=false
assert(advance()==nil,'failed release should cancel this native frame')
assert(native_updates==old_native and polls==old_polls)
assert(leave_count==1 and cancel_count==1 and not flow:view().open)
assert(files['transmog.state']==saved_before and save_count==0)
assert(logged_count('creator.input_error=')==1 and logged_count('proof span consume changed')==1)
assert(runtime.status:find('CREATOR PAUSED',1,true))
local stopped_before,stopped_consumes=before_count,consume_count
local a,b,c=advance()
assert(a=='native' and b==nil and c==42 and native_updates==old_native+1)
assert(command_ok and files['debug-ui-status.txt'],'queued debug request was stranded')
for i=1,1000 do advance()end
assert(before_count==stopped_before and consume_count==stopped_consumes,'failed creator guard repeated')
assert(leave_count==1 and cancel_count==1 and logged_count('creator.input_error=')==1)
assert(save_count==0 and files['transmog.state']==saved_before)
assert(command('inspect_api') and command_result=='debug still usable')
assert(legacy_draws>1000 and runtime.profile.frames>1000)
assert(logged_count('runtime.error=')==0 and logged_count('creator.saved=')==0)
''')


def test_same_actual_create_path_saves_when_capture_is_healthy():
    run('''
assert(command('open_creator'))
assert(flow:action{type='select_look',id='look-b'})
assert(flow:action{type='select_stats',id=flow:view().options[1].id})
assert(flow:action{type='select_passive',id='perk-b'})
assert(flow:view().can_create)
panel_target={type='create'};input.down=true;advance();input.down=false;advance()
assert(save_count==1 and files['transmog.state']~=saved_before and not flow:view().open)
local payload=files['transmog.state']:match('^HD2TRANSMOG_UI\\t1\\nappearance\\n(.*)$')
local saved=assert(State.decode(payload));assert(saved.presets['Custom Variant 1'].appearance_id=='look-b')
assert(saved.presets.Existing and logged_count('creator.saved=Custom Variant 1')==1)
assert(logged_count('creator.input_error=')==0)
''')


@pytest.mark.parametrize('restore_mode',['ok','refuse','throw'])
def test_prefix_capture_failure_attempts_restore_once_and_never_rebuilds_or_blocks_debug(restore_mode):
    run('''
assert(command('presentation_trial','on'));assert(presentation_active and flow)
assert(not flow:view().open and presentation_builds==1)
restore_mode='''+repr(restore_mode)+'''
consume_mode='refuse';input.down=true
local old_native=native_updates
advance()
assert(native_updates==old_native and presentation_restores==1)
assert(leave_count==1 and cancel_count==1 and save_count==0)
assert(logged_count('creator.input_error=')==1)
input.down=false
local stopped_before,stopped_consumes=before_count,consume_count
for i=1,1000 do advance()end
assert(native_updates==old_native+1000,'normal native callback remained blocked')
assert(before_count==stopped_before and consume_count==stopped_consumes)
assert(presentation_restores==1 and presentation_builds==1,'recovery restarted the presentation loop')
assert(command('ui_status') and files['debug-ui-status.txt'])
assert(command('variant_status') and files['debug-variant-status.txt'])
assert(files['transmog.state']==saved_before and save_count==0)
assert(logged_count('creator.input_error=')==1 and logged_count('runtime.error=')==0)
if restore_mode=='ok'then assert(host.should_capture(input)==false,'dirty/rebuild flags survived cancellation')end
''')


def test_sound_reference_mode_yields_native_input_and_resumes_only_on_request():
    run('''
assert(command('open_creator') and flow:view().open)
assert(command('sound_reference','on') and runtime.sound_reference)
local guarded=before_count;local native=native_updates;local drawn=wizard_draws
input.down=true
for i=1,5 do advance()end
input.down=false;advance()
assert(before_count==guarded and wizard_draws==drawn and native_updates==native+6)
assert(not command('sound_reference','guess'))
assert(command('sound_reference','off') and not runtime.sound_reference)
assert(command('open_creator') and flow:view().open)
assert(save_count==0 and logged_count('runtime.error=')==0)
''')


def test_optional_two_stage_mode_is_wired_through_main_and_persists_native_stats():
    run(r'''
assert(command('open_creator'))
assert(host.stats_follow_look==true and flow:view().step_count==2)
assert(flow:action{type='select_look',id='look-b'})
assert(flow:view().step_number==2 and flow:view().selection.stats_id=='stats-b')
assert(not flow:action{type='select_stats',id='base:50/550/125'})
assert(flow:action{type='select_passive',id='perk-a'})
panel_target={type='create'};input.down=true;advance();input.down=false;advance()
assert(save_count==1 and not flow:view().open)
local payload=files['transmog.state']:match('^HD2TRANSMOG_UI\t1\nappearance\n(.*)$')
local saved=assert(State.decode(payload))
assert(saved.presets['Custom Variant 1'].appearance_id=='look-b')
assert(saved.presets['Custom Variant 1'].stats_id=='stats-b')
assert(saved.presets['Custom Variant 1'].passive_variant_id=='perk-a')
assert(saved.presets.Existing.stats_id=='stats-a')
assert(logged_count('runtime.error=')==0)
''', stats_follow_look=True)


def test_passive_preview_setting_reaches_display_without_changing_saved_armor():
    for enabled in (True,False):
        run("assert(result.context.passive_preview_icons=="+str(enabled).lower()+")\n"
            "assert(files['transmog.state']==saved_before and save_count==0)",passive_icons=enabled)
