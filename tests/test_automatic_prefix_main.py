"""Actual main-loop menu epochs survive transient observation failures."""
import pytest

from test_creator_failure_main import run


@pytest.mark.parametrize('transient',["sample_mode='unreadable'", "grid_mode='unreadable'", "grid_mode='mapping'"])
def test_failed_automatic_build_does_not_retry_on_unreadable_recovery_but_confirmed_exit_rearms(transient):
    run('''
assert(presentation_builds==1 and not presentation_active)
assert(logged_count('presentation.rebuild_failed')==1)
local previews_before=preview_count
'''+transient+'''
for i=1,50 do advance()end
sample_mode='ready';grid_mode='ready'
for i=1,100 do advance()end
assert(presentation_builds==1 and preview_count==previews_before,'transient observation retried the automatic build')
assert(logged_count('presentation.rebuild_failed')==1 and release_views==0)
assert(command('ui_status') and files['debug-ui-status.txt'])
assert(save_count==0 and files['transmog.state']==saved_before)
-- Same controller token is deliberately reused: only the confirmed departure
-- establishes that returning Armor is a new entry.
sample_mode='exit';advance();assert(release_views==1)
sample_mode='ready';presentation_attempt_mode='ok'
advance();advance()
assert(presentation_builds==2 and presentation_active,'confirmed exit did not allow a new entry attempt')
for i=1,100 do advance()end
assert(presentation_builds==2 and save_count==0 and logged_count('runtime.error=')==0)
''', automatic=True, setup="presentation_attempt_mode='fail'")


def test_automatic_capture_failure_stays_paused_through_unreadable_frames_until_confirmed_exit():
    run('''
assert(presentation_builds==1 and presentation_active)
consume_mode='refuse';advance()
assert(logged_count('creator.input_error=')==1 and presentation_restores==1)
assert(not presentation_active and cancel_count==1)
sample_mode='unreadable';consume_mode='ok'
for i=1,25 do advance()end
sample_mode='ready'
for i=1,100 do advance()end
assert(presentation_builds==1 and logged_count('creator.input_error=')==1)
assert(command('inspect_api') and command_result=='debug still usable')
sample_mode='exit';advance();sample_mode='ready'
advance();advance()
assert(presentation_builds==2 and presentation_active)
assert(save_count==0 and files['transmog.state']==saved_before)
''', automatic=True)


def test_adapter_observation_gap_preserves_an_open_draft_without_rebuilding_or_cancelling():
    run('''
assert(presentation_builds==1 and presentation_active)
assert(command('open_creator'))
assert(flow:action{type='select_look',id='look-b'})
local before=flow:view();assert(before.open and before.step==2 and before.selection.appearance_id=='look-b')
local cancelled=cancel_count;local left=leave_count;local builds=presentation_builds
sample_mode='unreadable'
for i=1,20 do advance()end
assert(flow:view().open and flow:view().step==2 and cancel_count==cancelled and leave_count==left)
sample_mode='ready';advance()
assert(flow:view().selection.appearance_id=='look-b' and flow:view().open)
assert(presentation_builds==builds and save_count==0 and release_views==0)
assert(files['transmog.state']==saved_before)
''', automatic=True)


@pytest.mark.parametrize('departure',['other_kind','other_mode'])
def test_confirmed_different_native_category_allows_one_fresh_armor_attempt(departure):
    run('''
assert(presentation_builds==1 and not presentation_active)
grid_mode='''+repr(departure)+'''
for i=1,25 do advance()end
assert(presentation_builds==1,'automatic build ran in another native category')
grid_mode='ready';presentation_attempt_mode='ok'
advance();advance()
assert(presentation_builds==2 and presentation_active)
for i=1,100 do advance()end
assert(presentation_builds==2 and save_count==0 and files['transmog.state']==saved_before)
''', automatic=True, setup="presentation_attempt_mode='fail'")


@pytest.mark.parametrize('unready', ['inspect_mode', 'select_mode'])
def test_transient_readiness_retries_without_reopening_armory(unready):
    run('''
assert(presentation_builds==0)
for i=1,20 do advance()end
assert(presentation_builds==0)
'''+unready+'''='ready'
for i=1,10 do advance()end
assert(presentation_builds==1 and presentation_active)
for i=1,20 do advance()end
assert(presentation_builds==1 and save_count==0)
''', automatic=True, setup=unready+"='waiting'")


def test_first_row_readiness_failure_retries_without_spending_construction_budget():
    run('''
assert(presentation_builds==1 and not presentation_active)
presentation_attempt_mode='ok'
for i=1,10 do advance()end
assert(presentation_builds==2 and presentation_active)
''', automatic=True, setup="presentation_attempt_mode='waiting'")


def test_same_menu_native_list_repopulation_reinjects_custom_section():
    run('''
assert(presentation_builds==1 and presentation_active)
presentation_active=false -- Native population replaced the logical list.
for i=1,10 do advance()end
assert(presentation_builds==2 and presentation_active)
for i=1,20 do advance()end
assert(presentation_builds==2 and save_count==0)
''', automatic=True)


def test_replaced_menu_token_rebuilds_even_without_a_departure_observation():
    run('''
assert(presentation_builds==1 and presentation_active)
menu_token='replacement-menu';presentation_active=false
for i=1,10 do advance()end
assert(presentation_builds==2 and presentation_active)
''', automatic=True)


def test_reentry_explicitly_reselects_saved_card_instead_of_inheriting_native_details():
    run('''
assert(presentation_active and #selections==1 and selections[1]=='Existing')
assert(flow:view().selected_variant.label=='Existing')
sample_mode='exit';advance()
sample_mode='ready';advance();advance();advance()
assert(presentation_active and #selections==2 and selections[2]=='Existing')
assert(flow:view().selected_variant.label=='Existing')
assert(save_count==0 and files['transmog.state']==saved_before)
''', automatic=True, setup='''
selections={}
ArmorRefresh={};ArmorRefreshBridge={}
PlayerCustomizationProbe={new=function()return {}end}
VariantSession={new=function()
 return {select=function(_,label)selections[#selections+1]=label;return true end,
 view=function()return {native_details=true,can_apply=true,variant_phase='ready'}end,
 is_active=function()return false end,leave=function()return true end,step=function()end}
end}
''')
