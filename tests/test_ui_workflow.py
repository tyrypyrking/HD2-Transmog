from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def run_lua(script):
    result=subprocess.run(['luajit','-'],input=script,text=True,capture_output=True,cwd=ROOT,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


CAPTURE_FIXTURE=r'''
local S=dofile('src/state.lua')
local Wizard=dofile('src/variant_wizard.lua')
local Flow=dofile('src/ui_workflow.lua')
local triple={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
local domain=S.new{catalog={a=triple},owned={a=true}}
domain.requested=triple;domain.selected=triple;domain.presets.Existing=triple
local context={}
local consumed,native_equips,capture_count,cleared,intents= false,0,0,0,0
local capture_ready,capture_error,selected_custom=true,false,false
local target={type='open'}
local checks={}
local panel={draw=function()return true end,clear=function()cleared=cleared+1 end,
 hit=function(_,x,y)if x and x>=100 and x<200 and y>=100 and y<200 then return target end end,
 capture=function(_,x,y)return x and x>=100 and x<200 and y>=100 and y<200 end,
 handle=function()return false end,input_policy=function()return {}end}
local host={current=function()return domain,context end,persist=function()error('Not a save test')end,
 should_capture=function(input)
  checks[#checks+1]=input or 'no-input'
  if capture_error then error('Fresh prefix proof failed')end
  return selected_custom or (input and input.x and input.x>=100 and input.x<200 and input.y>=100 and input.y<200)
 end,
 consume_select=function()capture_count=capture_count+1;consumed=capture_ready;return capture_ready end,
 intent=function(intent)assert(intent.kind=='select_variant');intents=intents+1 end}
local flow=Flow.new(S,Wizard,panel,host)
-- This models the exact host order: before -> game's native update -> draw.
local function frame(input)
 consumed=false
 local ok,why=flow:before(input)
 if input and (input.down or input.confirm_down or input.select_down) and not consumed then native_equips=native_equips+1 end
 if ok then flow:draw({},input)end
 return ok,why
end
assert(frame{x=0,y=0,down=false})
'''


def test_creator_routes_preview_and_create_without_equipping_or_stale_clicks():
    script=r'''
local State=dofile('src/state.lua')
local Wizard=dofile('src/variant_wizard.lua')
local Flow=dofile('src/ui_workflow.lua')
local catalog={a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'},
 b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}}
local domain=State.new{catalog=catalog,owned={a=true,b=true}}
domain.requested={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
local before=State.encode(domain)
local context={stats_profiles={['stats-a']={base_only=true,base_values_verified=true,
 base_values={armor_rating=50,speed=550,stamina_regen=125}},
 ['stats-b']={base_only=true,base_values_verified=true,base_values={armor_rating=100,speed=500,stamina_regen=100}}}}
local target,preview_count,save_count,consumes,can_capture=nil,0,0,0,true
local panel={clear=function()end,draw=function()return true end,capture=function()return target~=nil end,
 hit=function()if target then local t={};for k,v in pairs(target)do t[k]=v end;return t end end,
 handle=function()return false end,input_policy=function()return {}end}
local fail_save=false
local flow=Flow.new(State,Wizard,panel,{
 current=function()return domain,context end,
 consume_select=function()consumes=consumes+1;return can_capture end,
 preview_look=function(id)assert(id=='look-b');preview_count=preview_count+1;return true end,
 persist=function(tx)
  save_count=save_count+1
  if fail_save then return nil,'disk full'end
  domain=tx.candidate;return true,domain
 end,
 verify_create=function()return true end,
})
assert(not flow:action{type='select_look',id='look-b'}and preview_count==0)
can_capture=false;assert(not flow:action{type='open'});assert(not flow:view().open)
can_capture=true;assert(flow:action{type='open'})
assert(not flow:action{type='select_look',id='unowned'}and preview_count==0)
assert(flow:action{type='select_look',id='look-b'}and preview_count==1)
local tuple=flow:view().options[1].id
assert(flow:action{type='select_stats',id=tuple})
assert(flow:action{type='select_passive',id='perk-b'})
assert(flow:view().can_create)
fail_save=true;assert(not flow:action{type='create'})
assert(State.encode(domain)==before and flow:view().open)
fail_save=false
flow:draw({}, {x=1,y=1,down=false})
target={type='create'}
assert(flow:before{x=1,y=1,down=true});flow:draw({}, {x=1,y=1,down=true})
assert(flow:before{x=1,y=1,down=false});flow:draw({}, {x=1,y=1,down=false})
assert(not flow:view().open and save_count==2)
assert(domain.requested.appearance_id=='look-a')
assert(domain.presets['Custom Variant 1'].appearance_id=='look-b')
assert(preview_count==1 and consumes>=3)
'''
    result=subprocess.run(['luajit','-'],input=script,text=True,capture_output=True,cwd=ROOT)
    assert result.returncode==0,result.stdout+result.stderr


def test_first_prefix_mouse_press_is_consumed_before_native_placeholder_can_equip():
    run_lua(CAPTURE_FIXTURE+r'''
local before=S.encode(domain)
assert(not flow:view().open)
assert(frame{x=150,y=150,down=true})
assert(native_equips==0 and capture_count==1 and not flow:view().open)
assert(frame{x=150,y=150,down=false})
assert(native_equips==0 and flow:view().open)
assert(S.encode(domain)==before and domain.selected.appearance_id=='look-a')
''')


def test_first_saved_card_press_routes_intent_without_native_equip_or_domain_mutation():
    run_lua(CAPTURE_FIXTURE+r'''
target={type='select_variant',label='Existing'}
local before=S.encode(domain)
assert(frame{x=150,y=150,down=true})
assert(native_equips==0 and intents==0)
assert(frame{x=150,y=150,down=false})
assert(native_equips==0 and intents==1 and not flow:view().open)
assert(S.encode(domain)==before and domain.selected.appearance_id=='look-a')
''')


def test_prefix_capture_latches_through_drag_off_and_releases_on_neutral_frame():
    run_lua(CAPTURE_FIXTURE+r'''
assert(frame{x=150,y=150,down=true})
assert(frame{x=300,y=300,down=true})
assert(native_equips==0 and capture_count==2)
assert(frame{x=300,y=300,down=false})
assert(capture_count==3 and not flow:view().open) -- Drag-off cancels own action.
assert(frame{x=300,y=300,down=true})
assert(capture_count==3 and native_equips==1) -- Ordinary native input works again.
''')


def test_selected_custom_keyboard_confirmation_is_captured_without_mouse_press():
    run_lua(CAPTURE_FIXTURE+r'''
selected_custom=true
assert(frame{x=0,y=0,down=false,confirm_down=true})
assert(native_equips==0 and capture_count==1)
selected_custom=false -- Native selection can change while the button is held.
assert(frame{x=0,y=0,down=false,confirm_down=true})
assert(native_equips==0 and capture_count==2)
assert(frame{x=0,y=0,down=false,confirm_down=false})
assert(native_equips==0 and capture_count==3)
assert(frame{x=0,y=0,down=false,confirm_down=true})
assert(native_equips==1 and capture_count==3)
assert(not flow:view().open and intents==0)
''')


def test_capture_hook_runs_without_mouse_sample_and_controller_latch_survives_focus_loss():
    run_lua(CAPTURE_FIXTURE+r'''
selected_custom=true
assert(frame(nil))
assert(checks[#checks]=='no-input' and capture_count==1)
selected_custom=false
assert(frame(nil) and capture_count==2) -- Nil does not prove release.
assert(frame{select_down=true} and native_equips==0 and capture_count==3)
assert(frame{select_down=false} and capture_count==4)
assert(frame{select_down=true} and native_equips==1 and capture_count==4)
''')


def test_failed_fresh_capture_check_consumes_defensively_and_reports_failure():
    run_lua(CAPTURE_FIXTURE+r'''
capture_error=true
local ok,why=frame{x=150,y=150,down=true}
assert(not ok and why=='Native input capture check failed')
assert(native_equips==0 and capture_count==1 and cleared==1)
capture_error=false
assert(frame{x=300,y=300,down=true} and native_equips==0 and capture_count==2)
assert(frame{x=300,y=300,down=false} and capture_count==3)
assert(not flow:view().open and intents==0)
''')


def test_unavailable_consumer_reports_failure_retains_latch_and_never_dispatches_ui_action():
    run_lua(CAPTURE_FIXTURE+r'''
capture_ready=false
local ok,why=flow:before{x=150,y=150,down=true}
assert(not ok and why:find('Native input capture is unavailable',1,true) and cleared==1)
assert(not flow:view().open and intents==0)
capture_ready=true
assert(frame{x=300,y=300,down=true} and native_equips==0)
assert(frame{x=300,y=300,down=false} and not flow:view().open)
assert(frame{x=300,y=300,down=true} and native_equips==1)
''')


def test_no_prefix_capture_does_not_steal_normal_native_mouse_or_keyboard_actions():
    run_lua(CAPTURE_FIXTURE+r'''
assert(frame{x=300,y=300,down=true})
assert(frame{x=300,y=300,down=false})
assert(frame{x=300,y=300,down=false,confirm_down=true})
assert(capture_count==0 and native_equips==2 and not flow:view().open)
host.should_capture=nil
assert(frame{x=300,y=300,down=false,select_down=true})
assert(capture_count==0 and native_equips==3)
''')


def test_equipment_workflow_blocks_creator_before_input_capture_or_persistence():
    run_lua(CAPTURE_FIXTURE+r'''
host.allow_create=false
host.begin_creation=function()error('Equipment opened the creator')end
host.intent=function(tx)assert(tx.kind=='select_variant');intents=intents+1;return true end
local equipment=Flow.new(S,Wizard,panel,host)
local before=capture_count
assert(#equipment:view().section.tiles==1)
for _,kind in ipairs({'open','select_look','select_stats','select_passive','create','set_label'})do
 local ok,why=equipment:action{type=kind,label='New'}
 assert(not ok and why:find('ship Armory',1,true))
end
assert(capture_count==before and not equipment:view().open)
assert(equipment:action{type='select_variant',label='Existing'})
assert(equipment:view().selected_variant.label=='Existing')
''')


def test_remove_only_selected_armory_variant_after_preview_and_preserves_failed_save():
    run_lua(CAPTURE_FIXTURE + r'''
local removed=0;local fail=true;local pending=false
host.intent=function()return true end
host.remove_variant=function(name)
 assert(name=='Existing');removed=removed+1
 if fail then return nil,'disk full'end
 domain.presets[name]=nil;return true
end
host.variant_view=function()return {native_details=true,apply_pending=pending}end
assert(not flow:action{type='remove_variant',label='Existing'})
assert(flow:action{type='select_variant',label='Existing'})
assert(flow:view().can_remove)
pending=true;assert(not flow:action{type='remove_variant',label='Existing'}and removed==0)
pending=false;assert(not flow:action{type='remove_variant',label='Other'}and removed==0)
assert(not flow:action{type='remove_variant',label='Existing'}and removed==1)
assert(domain.presets.Existing and flow:view().selected_variant)
fail=false;assert(flow:action{type='remove_variant',label='Existing'})
assert(not domain.presets.Existing and not flow:view().selected_variant)
assert(domain.requested==triple and domain.selected==triple)
host.allow_create=false;domain.presets.Existing=triple
assert(flow:action{type='select_variant',label='Existing'})
assert(not flow:view().can_remove and not flow:action{type='remove_variant',label='Existing'})
assert(domain.presets.Existing and removed==2)
''')
