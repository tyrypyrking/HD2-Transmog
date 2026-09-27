"""Saved-card preview stays separate from explicit, verified native Apply."""
from test_wizard_panel import FIXTURE, RENDER_FIXTURE, PREFIX_FIXTURE
from test_ui_workflow import run_lua


APPLY_FIXTURE = FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local Workflow=dofile('src/ui_workflow.lua')
local applied,persisted,previews,consumed,native_equips=0,0,0,false,0
local selected_custom,capture_ready=false,true
local apply_state={native_details=false,can_apply=false,apply_pending=true,variant_phase='previewing'}
local notices={}
local host={
 current=function()return state,context end,
 persist=function(tx)persisted=persisted+1;state=tx.candidate;return true,state end,
 intent=function(tx)assert(tx.kind=='select_variant');selected_custom=true;previews=previews+1;return true end,
 variant_view=function()return apply_state end,
 apply_variant=function()
  applied=applied+1;apply_state.can_apply=false;apply_state.apply_pending=true;return true
 end,
 consume_select=function()consumed=capture_ready;return capture_ready end,
 should_capture=function(input)
  return selected_custom or(input and input.x>=172 and input.x<816 and input.y>=104 and input.y<842)
 end,
 preview_look=function()previews=previews+1;return true end,
 notice=function(reason)notices[#notices+1]=reason;apply_state.apply_notice=reason end,
}
local flow=Workflow.new(S,W,panel,host)
local function frame(x,y,down)
 local input={x=x,y=y,down=down};consumed=false
 local ok,why=flow:before(input)
 if ok then
  if down and not consumed then native_equips=native_equips+1 end
  flow:draw(sample,input)
 end
 return ok,why
end
local function ready()
 apply_state={native_details=true,can_apply=true,apply_pending=false,variant_phase='ready'}
end
assert(frame(0,0,false))
'''


def test_apply_requires_a_selected_variant_and_strict_verified_ready_flags():
    run_lua(APPLY_FIXTURE + r'''
ready();assert(not flow:action{type='apply_variant'} and applied==0)
assert(flow:action{type='select_variant',label='Existing'} and previews==1)
local view=flow:view()
assert(view.native_details==true and view.can_apply==true and view.variant_phase=='ready')
for _,flags in ipairs({{},
 {native_details=false,can_apply=true},
 {native_details='true',can_apply=true},
 {native_details=true,can_apply='true'},
 {native_details=true,can_apply=false},
 {native_details=true,can_apply=true,apply_pending=true},
})do
 apply_state=flags
 assert(not flow:action{type='apply_variant'} and applied==0)
end
apply_state=nil;assert(not flow:action{type='apply_variant'} and applied==0)
ready();host.apply_variant=nil
assert(not flow:action{type='apply_variant'} and applied==0)
''')


def test_selected_card_only_previews_then_apply_mouse_release_dispatches_once():
    run_lua(APPLY_FIXTURE + r'''
local before=S.encode(state)
assert(frame(230,700,true) and previews==0 and applied==0 and native_equips==0)
assert(frame(230,700,false) and previews==1 and applied==0)
assert(flow:view().selected_variant.label=='Existing' and S.encode(state)==before)
ready();assert(frame(0,0,false))
assert(frame(1800,130,true) and applied==0 and native_equips==0)
assert(frame(1800,130,true) and applied==0)
assert(frame(1800,130,false) and applied==1)
assert(frame(1800,130,false) and applied==1)
assert(frame(1800,130,true));assert(frame(1800,130,false))
assert(applied==1 and persisted==0 and native_equips==0 and S.encode(state)==before)
''')


def test_footer_apply_is_explicit_and_readiness_changes_cancel_a_pressed_button():
    run_lua(APPLY_FIXTURE + r'''
assert(flow:action{type='select_variant',label='Existing'});ready()
assert(frame(1800,20,true))
apply_state.can_apply=false
assert(frame(1800,20,false) and applied==0)
ready();assert(frame(1800,20,true));assert(frame(1800,20,false))
assert(applied==1 and native_equips==0 and persisted==0)
''')


def test_apply_drag_off_focus_loss_and_failed_capture_never_replay_equipment():
    run_lua(APPLY_FIXTURE + r'''
assert(flow:action{type='select_variant',label='Existing'});ready()
assert(frame(1800,130,true));assert(frame(1400,750,false))
assert(applied==0)
assert(frame(1800,130,true));flow:clear()
assert(frame(1800,130,false) and applied==0)
assert(frame(1800,130,true));capture_ready=false
assert(not frame(1800,130,false) and applied==0)
capture_ready=true;assert(frame(1800,130,false) and applied==0)
assert(native_equips==0 and persisted==0)
''')


def test_creation_save_and_cancel_never_inherit_native_apply_authority():
    run_lua(APPLY_FIXTURE + r'''
assert(flow:action{type='select_variant',label='Existing'});ready()
assert(flow:action{type='open'})
assert(flow:view().open and flow:view().native_details==nil and flow:view().selected_variant==nil)
assert(not flow:action{type='apply_variant'})
assert(flow:action{type='select_look',id='look-b'})
assert(flow:action{type='select_stats',id='base:50/550/125'})
assert(flow:action{type='select_passive',id='perk-b'})
assert(flow:action{type='create'})
assert(persisted==1 and applied==0 and not flow:view().open)
assert(flow:view().selected_variant==nil and not flow:action{type='apply_variant'})
assert(state.presets['Beta - Padding'].appearance_id=='look-b')
assert(state.requested.appearance_id=='look-a' and state.selected.appearance_id=='look-a')
assert(flow:action{type='open'});assert(flow:action{type='cancel'})
assert(applied==0 and persisted==1)
''')


def test_failed_explicit_apply_reports_reason_without_persisting_or_replacing_selection():
    run_lua(APPLY_FIXTURE + r'''
assert(flow:action{type='select_variant',label='Existing'});ready()
host.apply_variant=function()applied=applied+1;return nil,'Armor refresh could not be verified.'end
assert(frame(1800,130,true));assert(frame(1800,130,false))
assert(applied==1 and notices[#notices]=='Armor refresh could not be verified.')
assert(flow:view().selected_variant.label=='Existing' and flow:view().apply_notice==notices[#notices])
assert(persisted==0 and native_equips==0)
assert(frame(1800,130,false) and applied==1)
''')


def test_apply_press_is_bound_to_the_saved_variant_that_was_visible_when_pressed():
    run_lua(APPLY_FIXTURE + r'''
state.presets.Another=state.presets.Existing
assert(flow:action{type='select_variant',label='Existing'});ready()
assert(frame(1800,130,true))
assert(flow:action{type='select_variant',label='Another'});ready()
assert(frame(1800,130,false) and applied==0)
assert(not flow:action{type='apply_variant',label='Existing'} and applied==0)
assert(frame(1800,130,true));assert(frame(1800,130,false))
assert(applied==1 and native_equips==0 and persisted==0)
''')


def test_original_same_carrier_override_captures_apply_without_saved_card_or_prefix():
    run_lua(APPLY_FIXTURE + r'''
local id='armor:00000001'
state.catalog[id]=catalog.a;state.owned[id]=true
host.preview_native_look=function(selected)
 assert(selected==id);selected_custom=true;previews=previews+1
 apply_state={native_override=true,native_override_id=id,native_details=false,can_apply=false,apply_pending=true}
 return true
end
assert(flow:action{type='select_native_look',id=id})
assert(flow:view().selected_variant==nil and flow:view().native_override==true and applied==0)
sample.native_prefix=nil;texts={};rects={}
assert(frame(0,0,false))
assert(shown('Loading preview…') and #rects==0 and panel:hit(1800,130).type=='panel_background')
apply_state.native_details=true;apply_state.can_apply=true;apply_state.apply_pending=false
texts={};assert(frame(0,0,false))
local action=panel:hit(1800,130)
assert(action.type=='apply_variant' and action.id==id and action.label==nil)
assert(panel:hit(1800,20).id==id and #texts==0 and #rects==0)
assert(frame(1800,130,true) and applied==0);assert(frame(1800,130,false) and applied==1)
assert(frame(1800,130,false) and applied==1 and native_equips==0 and persisted==0)
''')


def test_original_override_identity_change_cancels_press_and_failures_remain_visible():
    run_lua(APPLY_FIXTURE + r'''
selected_custom=true;sample.native_prefix=nil
apply_state={native_override=true,native_override_id='armor:00000001',native_details=true,can_apply=true}
assert(frame(1800,130,true))
apply_state.native_override_id='armor:00000002'
assert(frame(1800,130,false) and applied==0)
assert(panel:hit(1800,130).id=='armor:00000002')
assert(not flow:action{type='apply_variant',id='armor:00000001'} and applied==0)
apply_state.native_details=false;apply_state.can_apply=false;apply_state.apply_pending=false
apply_state.apply_notice='Original armor refresh could not be verified.'
texts={};rects={};assert(frame(0,0,false))
assert(shown(apply_state.apply_notice) and #rects==0 and not shown('Saved variant'))
assert(panel:hit(1800,130).type=='panel_background' and not panel:capture(1000,350))
assert(flow:view().selected_variant==nil and native_equips==0 and persisted==0)
''')
