"""Owned original-card browsing is preview-only and leaves native Apply usable."""
from test_ui_workflow import run_lua

FIXTURE=r'''
local State=dofile('src/state.lua')
local Wizard=dofile('src/variant_wizard.lua')
local Workflow=dofile('src/ui_workflow.lua')
local a={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}
local b={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}
local domain=State.new{catalog={a=a,b=b},owned={a=true,b=true}}
domain.requested=a;domain.selected=a;domain.presets.Existing=a
local encoded=State.encode(domain)
local selected_custom,selected_original=false,nil
local consumed,capture_ready=false,true
local previews,lookups,notices,persisted,native_equips=0,0,{},0,0
local last_preview,preview_ok,preview_error=nil,true,nil
local panel_target
local function grid_hit(x,y)
 if not x or not y or y<100 or y>=200 then return nil end
 if x>=100 and x<200 then return 'a' end
 if x>=200 and x<300 then return 'b' end
end
local panel={draw=function()return true end,clear=function()end,handle=function()return false end,
 hit=function()return panel_target end,capture=function()return panel_target~=nil end,
 input_policy=function()return {}end}
local host={current=function()return domain,{}end,
 should_capture=function(input)
  return selected_custom or(input and input.down==true and grid_hit(input.x,input.y)~=nil)
 end,
 consume_select=function()
  consumed=capture_ready;return capture_ready,capture_ready and nil or 'native proof changed'
 end,
 browse_look_at=function(x,y)lookups=lookups+1;return grid_hit(x,y)end,
 preview_native_look=function(id)
  previews=previews+1;last_preview=id
  if not preview_ok then return nil,preview_error end
  selected_original=id;selected_custom=false;return true
 end,
 intent=function(tx)
  assert(tx.kind=='select_variant');selected_custom=true;selected_original=nil;return true
 end,
 persist=function()persisted=persisted+1;error('Native browse must not persist')end,
 notice=function(reason)notices[#notices+1]=reason end}
local flow=Workflow.new(State,Wizard,panel,host)
local function frame(input)
 consumed=false
 local ok,why=flow:before(input)
 if ok then
  if input and(input.down or input.confirm_down or input.select_down)and not consumed then native_equips=native_equips+1 end
  flow:draw({},input)
 end
 return ok,why
end
assert(frame{x=0,y=0,down=false})
'''


def test_original_first_click_is_captured_and_only_release_previews_owned_kit():
    run_lua(FIXTURE+'''
assert(frame{x=250,y=150,down=true})
assert(consumed and native_equips==0 and previews==0)
assert(frame{x=250,y=150,down=false})
assert(previews==1 and last_preview=='b' and selected_original=='b' and native_equips==0)
assert(not flow:view().open and flow:view().selected_variant==nil)
assert(persisted==0 and State.encode(domain)==encoded)
assert(frame{x=900,y=500,down=true}) -- Native Apply, outside the intercepted grid.
assert(not consumed and native_equips==1 and previews==1)
''')


def test_original_selection_clears_saved_review_and_releases_custom_confirmation_latch():
    run_lua(FIXTURE+'''
assert(flow:action{type='select_variant',label='Existing'})
assert(flow:view().selected_variant.label=='Existing' and selected_custom)
assert(frame{x=250,y=150,down=true} and native_equips==0)
assert(frame{x=250,y=150,down=false} and selected_original=='b')
assert(flow:view().selected_variant==nil and not selected_custom)
assert(frame{x=900,y=500,down=false,confirm_down=true})
assert(not consumed and native_equips==1,'stale custom latch swallowed native Apply')
assert(persisted==0 and State.encode(domain)==encoded)
''')


def test_drag_off_or_to_another_original_cancels_even_when_pointer_returns():
    run_lua(FIXTURE+'''
assert(frame{x=250,y=150,down=true})
assert(frame{x=900,y=500,down=true})
assert(frame{x=250,y=150,down=false})
assert(previews==0 and native_equips==0)
assert(frame{x=250,y=150,down=true})
assert(frame{x=150,y=150,down=true})
assert(frame{x=250,y=150,down=false})
assert(previews==0 and native_equips==0 and persisted==0)
''')


def test_focus_loss_or_changed_release_identity_cancels_browse_intent():
    run_lua(FIXTURE+'''
assert(frame{x=250,y=150,down=true});assert(frame(nil))
assert(frame{x=250,y=150,down=false})
assert(previews==0 and native_equips==0)
assert(frame{x=250,y=150,down=true})
host.browse_look_at=function()return 'a'end
assert(frame{x=250,y=150,down=false})
assert(previews==0 and persisted==0)
''')


def test_failed_preview_keeps_saved_review_and_propagates_reason_without_state_change():
    run_lua(FIXTURE+'''
assert(flow:action{type='select_variant',label='Existing'})
preview_ok=false;preview_error='fresh original-row identity changed'
assert(frame{x=250,y=150,down=true});assert(frame{x=250,y=150,down=false})
assert(previews==1 and selected_original==nil and flow:view().selected_variant.label=='Existing')
assert(notices[#notices]==preview_error and State.encode(domain)==encoded and persisted==0)
''')


def test_owned_kit_guard_and_creator_open_guard_prevent_native_preview():
    run_lua(FIXTURE+'''
assert(not flow:action{type='select_native_look',id='unowned'})
assert(not flow:action{type='select_native_look',id='look-b'},'appearance id is not the owned native kit key')
domain.ownership_verified=false;assert(not flow:action{type='select_native_look',id='b'})
domain.ownership_verified=true;domain.owned.b=false;assert(not flow:action{type='select_native_look',id='b'})
domain.owned.b=true
assert(flow:action{type='open'});assert(not flow:action{type='select_native_look',id='b'})
local before=lookups;assert(frame{x=250,y=150,down=true});assert(frame{x=250,y=150,down=false})
assert(lookups==before and previews==0 and persisted==0)
''')


def test_own_panel_target_takes_precedence_over_native_browse_hit():
    run_lua(FIXTURE+'''
panel_target={type='open'};local before=lookups
assert(frame{x=250,y=150,down=true});assert(frame{x=250,y=150,down=false})
assert(flow:view().open and previews==0 and lookups==before and native_equips==0)
''')


def test_failed_capture_cancels_armed_original_click_without_later_replay():
    run_lua(FIXTURE+'''
assert(frame{x=250,y=150,down=true})
capture_ready=false
local ok,why=frame{x=250,y=150,down=false}
assert(not ok and why:find('native proof changed',1,true))
capture_ready=true;assert(frame{x=250,y=150,down=false})
assert(previews==0 and persisted==0 and native_equips==0)
''')


def test_explicit_review_clear_is_pure_and_keyboard_hold_keeps_capture_until_release():
    run_lua(FIXTURE+'''
assert(flow:action{type='select_variant',label='Existing'})
assert(flow:clear_selected_variant() and flow:view().selected_variant==nil)
assert(State.encode(domain)==encoded and previews==0 and persisted==0)
assert(frame{x=250,y=150,down=true,confirm_down=true})
assert(frame{x=250,y=150,down=false,confirm_down=true})
assert(previews==1 and selected_original=='b')
assert(frame{x=900,y=500,down=false,confirm_down=true} and consumed)
assert(frame{x=900,y=500,down=false,confirm_down=false} and consumed)
assert(frame{x=900,y=500,down=false,confirm_down=true} and not consumed)
assert(native_equips==1)
''')


def test_neutral_closed_frames_do_not_repeatedly_sample_native_browse_targets():
    run_lua(FIXTURE+'''
local before=lookups
for i=1,100 do assert(frame{x=250,y=150,down=false})end
assert(lookups==before and previews==0 and persisted==0)
''')


def test_original_click_retains_exact_index_and_same_id_relayout_cancels_release():
    run_lua(FIXTURE+'''
local index=17
host.browse_look_at=function()return 'a',index end
host.preview_native_look=function(id,at)assert(id=='a'and at==17);previews=previews+1;return true end
assert(frame{x=150,y=150,down=true});assert(frame{x=150,y=150,down=false})
assert(previews==1)
assert(frame{x=150,y=150,down=true});index=18
assert(frame{x=150,y=150,down=false})
assert(previews==1,'same kit in a changed logical card accepted the old press')
''')
