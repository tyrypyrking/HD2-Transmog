"""Native controller focus within a category cannot equip a stale saved card."""
from test_creator_failure_main import run
from test_category_navigation import NAV

PAD=NAV+"\ninput.controller_source='XInput0';input.confirm_down=false\nfunction grid:selection_index()return nav_index end\n"


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
