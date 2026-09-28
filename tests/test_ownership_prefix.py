"""Ownership refresh with the real main loop, creator, and saved-card prefix."""
from test_creator_failure_main import run

SETUP = '''
refresh_count=0;session_busy=false;session_created=0;unlocked=false;grant_unlock=false
catalog.c={appearance_id='look-c',stats_id='stats-c',passive_variant_id='perk-c'}
result.refresh_ownership=function()
 refresh_count=refresh_count+1
 local changed=unlocked~=grant_unlock;unlocked=grant_unlock
 result.owned={a=true,b=true,c=unlocked}
 result.counts.owned_armors=unlocked and 3 or 2
 return 'ready',changed
end
ArmorRefresh={};ArmorRefreshBridge={}
PlayerCustomizationProbe={new=function()return {}end}
VariantSession={new=function()
 session_created=session_created+1
 return {select=function()return true end,
 view=function()return {native_details=true,can_apply=true,variant_phase='ready'}end,
 is_active=function()return true end,busy=function()return session_busy end,
 cancel_preview=function()return not session_busy end,
 browse=function()return true end,leave=function()return true end,step=function()end}
end}
'''


def test_busy_saved_session_defers_refresh_until_equipment_transaction_finishes():
    run('''
assert(presentation_active and session_created==1)
session_busy=true;grant_unlock=true
for i=1,50 do advance()end
assert(refresh_count==0 and not result.owned.c,'ownership refreshed during equipment transaction')
assert(presentation_builds==1 and presentation_restores==0)
session_busy=false;advance()
assert(refresh_count==1 and result.owned.c)
for i=1,5 do advance()end
assert(presentation_builds==2 and presentation_active and session_created==1)
assert(save_count==0 and logged_count('runtime.error=')==0)
''', automatic=True, setup=SETUP)


def test_creator_receives_new_owned_choices_but_prefix_rebuild_waits_for_close():
    run('''
assert(presentation_active and presentation_builds==1)
assert(command('open_creator') and flow:view().open)
local restores=presentation_restores
assert(not presentation_active and restores==1)
assert(#flow:view().options==2)
grant_unlock=true
for i=1,30 do advance()end
assert(result.owned.c and #flow:view().options==3,'creator did not expand owned choices')
assert(presentation_builds==1 and presentation_restores==restores and flow:view().open)
assert(flow:action{type='select_look',id='look-c'})
assert(flow:view().selection.appearance_id=='look-c')
for i=1,25 do advance()end
assert(flow:view().selection.appearance_id=='look-c'and presentation_builds==1,'refresh disturbed draft')
assert(flow:action{type='cancel'})
for i=1,5 do advance()end
assert(not flow:view().open and presentation_active and presentation_builds==2)
assert(presentation_restores==restores and session_created==1)
assert(save_count==0 and files['transmog.state']==saved_before and logged_count('runtime.error=')==0)
''', automatic=True, setup=SETUP)


def test_debug_catalog_read_uses_ownership_refresh_with_active_saved_session():
    run('''
assert(presentation_active and session_created==1)
grant_unlock=true
assert(command('read_catalog'))
assert(command_result:find('Ownership-only refresh',1,true))
assert(refresh_count==1 and result.owned.c and session_created==1)
for i=1,5 do advance()end
assert(presentation_active and presentation_builds==2 and session_created==1)
assert(save_count==0 and logged_count('runtime.error=')==0)
''', automatic=True, setup=SETUP)


def test_remove_rebuilds_prefix_and_preserves_equipped_session():
    run('''
assert(presentation_active and session_created==1)
assert(flow:view().selected_variant.label=='Existing')
session_busy=true
assert(not host.remove_variant('Existing') and save_count==0)
session_busy=false
assert(flow:action{type='remove_variant',label='Existing'})
assert(save_count==1 and not flow:view().selected_variant)
local payload=files['transmog.state']:match('^HD2TRANSMOG_UI\\t1\\nappearance\\n(.*)$')
local saved=assert(State.decode(payload));assert(not saved.presets.Existing)
assert(saved.requested.appearance_id=='look-a')
for i=1,5 do advance()end
assert(presentation_active and presentation_builds==2 and session_created==1)
assert(logged_count('runtime.error=')==0)
''', automatic=True, setup=SETUP)
