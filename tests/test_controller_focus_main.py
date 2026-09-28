"""Native controller focus within a category cannot equip a stale saved card."""
from test_creator_failure_main import run
from test_category_navigation import NAV

PAD=NAV+"\ninput.controller_source='XInput0';input.confirm_down=false;input.nav_y=-1\nfunction grid:selection_index()return nav_index end\n"


def test_controller_follows_card_changes_without_category_change_and_clears_plus():
    run('''
advance();assert(flow:view().selected_variant.label=='Existing')
assert(host.validate_confirm{label='Existing'})
nav_index=2;advance()
assert(browses==1 and not flow:view().selected_variant)
assert(not host.validate_confirm{label='Existing'})
assert(host.validate_confirm{id='b'})
for i=1,5 do advance()end
assert(browses==1)
nav_index=0;advance()
assert(flow:view().selected_variant.label=='Existing'and selects==2)
nav_index=1;advance()
assert(not flow:view().selected_variant and not host.validate_confirm{label='Existing'})
assert(save_count==0 and logged_count('runtime.error=')==0)
''',automatic=True,setup=PAD)


def test_controller_focus_waits_for_transaction_and_verified_card_binding():
    run('''
advance();session_busy=true;nav_index=2;advance()
assert(browses==0 and flow:view().selected_variant.label=='Existing')
session_busy=false;nav_missing=true;advance()
assert(browses==0 and not host.validate_confirm{id='b'})
nav_missing=false;advance()
assert(browses==1 and host.validate_confirm{id='b'})
assert(save_count==0 and logged_count('runtime.error=')==0)
''',automatic=True,setup=PAD)


def test_actual_create_card_controller_a_opens_creator_and_preserves_armor():
    run('''
advance();nav_index=1;advance()
assert(not flow:is_open()and not flow:view().selected_variant)
local action=host.controller_action()
assert(action.type=='open'and host.validate_confirm(action))
input.confirm_down=true;advance()
assert(not flow:is_open())
input.confirm_down=false;advance()
assert(flow:is_open()and flow:view().step==1)
assert(save_count==0 and files['transmog.state']==saved_before)
assert(logged_count('runtime.error=')==0)
''',automatic=True,setup=PAD)


def test_controller_navigation_cancels_queued_preview_before_it_can_rewind_focus():
    setup=PAD+r'''
local factory=VariantSession.new
preview_pending=false;rewinds=0
VariantSession.new=function(...)
 local s=factory(...)
 local cancel=s.cancel_preview
 s.cancel_preview=function(...)preview_pending=false;return cancel(...)end
 s.view=function()return {native_details=not preview_pending,can_apply=not preview_pending,apply_pending=preview_pending}end
 s.step=function()if preview_pending then nav_index=0;rewinds=rewinds+1 end end
 return s
end
'''
    run(r'''
advance();assert(flow:view().selected_variant.label=='Existing')
preview_pending=true;nav_index=2;advance()
assert(browses==1 and rewinds==0 and nav_index==2)
assert(not flow:view().selected_variant and save_count==0)
''',automatic=True,setup=setup)


def test_idle_connected_controller_does_not_reclaim_mouse_selection():
    run(r'''
input.nav_y=0
advance();assert(flow:view().selected_variant.label=='Existing')
assert(flow:action{type='select_native_look',id='b',index=2})
assert(not flow:view().selected_variant)
for i=1,5 do advance()end
assert(browses==1 and selects==1 and not flow:view().selected_variant)
input.nav_y=-1;advance()
assert(flow:view().selected_variant.label=='Existing')
input.nav_y=0;input.down=true;advance();input.down=false
assert(flow:action{type='select_native_look',id='b',index=2})
for i=1,5 do advance()end
assert(browses==2 and selects==2 and not flow:view().selected_variant)
''',automatic=True,setup=PAD+'\ninput.nav_y=0\n')


def test_open_creator_cancels_preview_without_waiting_for_timeout():
    setup=PAD+r'''
local factory=VariantSession.new
local waiting=true
VariantSession.new=function(...)
 local s=factory(...)
 s.cancel_preview=function()waiting=false;return true end
 s.browse=function()assert(not waiting,'creator waited on obsolete preview');return true end
 return s
end
'''
    run(r'''
advance();assert(flow:action{type='open'})
assert(flow:is_open()and save_count==0 and logged_count('runtime.error=')==0)
assert(flow:action{type='cancel'})
for i=1,10 do advance()end
assert(not flow:is_open()and presentation_active and logged_count('runtime.error=')==0)
''',automatic=True,setup=setup)


def test_quick_controller_focus_change_refreshes_throttled_thumbnail_observation():
    run(r'''
advance();assert(flow:view().selected_variant.label=='Existing')
nav_index=2
-- Do not reach the ordinary 100ms sample deadline.
now=now+1;update()
assert(browses==1 and not flow:view().selected_variant)
assert(host.validate_confirm{id='b'})
assert(save_count==0 and logged_count('runtime.error=')==0)
''',automatic=True,setup=PAD)
