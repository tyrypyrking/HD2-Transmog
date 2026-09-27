"""Double-click confirmation uses the shared validated equip path in both menus."""
import pytest
from test_ui_workflow_apply import APPLY_FIXTURE
from test_ui_workflow import run_lua

SETUP = r'''
local now=0
host.now=function()return now end
local function click(x,y)
 assert(frame(x,y,true));now=now+20;assert(frame(x,y,false));now=now+40
end
local function finish()assert(frame(0,0,false))end
'''

@pytest.mark.parametrize('deployment',[False,True])
@pytest.mark.parametrize('ordinary',[False,True])
def test_double_click_equips_same_ready_card_once_in_both_menus(deployment,ordinary):
    mode='host.allow_create=false;flow=Workflow.new(S,W,panel,host);assert(frame(0,0,false))' if deployment else ''
    native=r'''
host.should_capture=function()return true end
host.browse_look_at=function(x,y)if x==900 then return 'a',12 end end
host.preview_native_look=function(id,index)
 assert(id=='a'and index==12);previews=previews+1;selected_custom=true
 apply_state={native_override=true,native_override_id='a',native_details=true,can_apply=true,apply_pending=false}
 return true
end
local x,y=900,700
''' if ordinary else 'local x,y=230,700'
    run_lua(APPLY_FIXTURE+SETUP+mode+native+r'''
click(x,y);assert(previews==1 and applied==0)
if not apply_state.native_override then ready()end
click(x,y);finish()
assert(applied==1 and previews==1 and native_equips==0 and persisted==0)
finish();assert(applied==1)
''')


def test_double_click_waits_for_preview_without_restarting_it():
    run_lua(APPLY_FIXTURE+SETUP+r'''
click(230,700);click(230,700);finish()
assert(applied==0 and previews==1)
now=300;ready();finish();assert(applied==1 and previews==1)
''')

@pytest.mark.parametrize('cancel',[
 'flow:before(nil)',
 'flow:leave()',
 'flow:clear()',
 'flow:clear_selected_variant()',
 'host.validate_confirm=function()return false end',
 'now=2000',
 'now=0',
 'assert(frame(1000,900,true));assert(frame(1000,900,false))',
 "apply_state.variant_phase='preview_failed'",
])
def test_queued_double_click_cancels_without_later_equipping(cancel):
    run_lua(APPLY_FIXTURE+SETUP+r'''
click(230,700);click(230,700)
'''+cancel+r'''
finish();ready();now=2100;finish();assert(applied==0)
''')


def test_slow_clicks_and_drag_off_do_not_equip():
    run_lua(APPLY_FIXTURE+SETUP+r'''
click(230,700);ready();now=2000;click(230,700);finish();assert(applied==0)
now=2100;assert(frame(230,700,true));assert(frame(1000,900,true))
assert(frame(230,700,false));finish();assert(applied==0)
''')


def test_changed_selected_variant_cannot_receive_queued_confirmation():
    run_lua(APPLY_FIXTURE+SETUP+r'''
state.presets.Another=catalog.b
click(230,700);click(230,700)
assert(flow:action{type='select_variant',label='Another'});ready();finish()
assert(applied==0)
''')


def test_relaxed_double_click_accepts_a_one_second_gap():
    run_lua(APPLY_FIXTURE+SETUP+r'''
click(230,700);ready();now=1020;click(230,700);finish()
assert(applied==1 and previews==1)
''')
