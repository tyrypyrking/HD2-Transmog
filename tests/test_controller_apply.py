"""Controller A acts on semantic focus, never the cursor or a stale selection."""
from test_ui_workflow_apply import APPLY_FIXTURE
from test_ui_workflow import run_lua

PAD=r'''
local source='XInput0'
local function pad(down)
 local input={x=-1,y=-1,down=false,confirm_down=down,controller_source=source}
 consumed=false;local ok,why=flow:before(input)
 if ok then flow:draw(sample,input)end
 return ok,why
end
assert(flow:action{type='select_variant',label='Existing'});ready()
'''


def run(code):
    run_lua(APPLY_FIXTURE+PAD+code)


def test_a_equips_current_ready_saved_card_once_after_release():
    run(r'''
local confirmed=0
host.controller_confirmed=function(source)assert(source=='XInput0');confirmed=confirmed+1 end
assert(pad(false));assert(pad(true)and consumed and applied==0)
for i=1,20 do assert(pad(true)and consumed and applied==0)end
assert(pad(false)and consumed and applied==1)
assert(pad(false)and applied==1 and persisted==0 and native_equips==0 and confirmed==1)
''')


def test_a_equips_original_armor_using_the_same_verified_path():
    run(r'''
flow:clear_selected_variant()
apply_state.native_override=true;apply_state.native_override_id='look-a'
host.should_capture=function()return true end
assert(pad(false));assert(pad(true));assert(pad(false))
assert(applied==1 and persisted==0 and native_equips==0)
''')


def test_initial_held_a_pending_preview_and_new_device_do_not_equip():
    run(r'''
assert(pad(true));assert(pad(false)and applied==0)
apply_state.apply_pending=true;apply_state.can_apply=false
assert(pad(true));ready();assert(pad(true));assert(pad(false)and applied==0)
assert(pad(true));source='XInput1';assert(pad(false)and applied==0)
assert(pad(true));assert(pad(false)and applied==1)
''')


def test_focus_loss_disconnect_or_capture_failure_cancels_armed_a():
    for interruption in [
        'assert(flow:before(nil))',
        'source=nil;assert(pad(false));source="XInput0"',
        'capture_ready=false;assert(not pad(false));capture_ready=true',
        'flow:clear()',
    ]:
        run('assert(pad(false));assert(pad(true))\n'+interruption+r'''
assert(pad(false)and applied==0)
assert(pad(true));assert(pad(false)and applied==1)
''')


def test_native_focus_change_while_a_is_held_cancels_confirmation():
    run(r'''
local matches=true
host.validate_confirm=function(action)return matches and action.label=='Existing'end
assert(pad(false));assert(pad(true))
matches=false;assert(pad(true));matches=true
assert(pad(false)and applied==0)
assert(pad(true));assert(pad(false)and applied==1)
''')


def test_a_in_creator_or_simultaneous_mouse_gesture_does_not_apply():
    run(r'''
assert(pad(false));assert(flow:action{type='open'})
assert(pad(true));assert(pad(false)and applied==0)
assert(flow:action{type='cancel'})
assert(flow:action{type='select_variant',label='Existing'});ready()
assert(frame(1800,130,true));assert(pad(true));assert(pad(false))
assert(applied==0)
''')


def test_disconnect_seen_only_before_native_update_still_cancels_confirmation():
    run(r'''
assert(pad(false));assert(pad(true))
assert(flow:before{x=0,y=0,down=false})
assert(pad(false)and applied==0)
''')
