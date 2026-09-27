"""Refresh ownership in the running main loop while preserving an applied patch."""
from test_variant_controller import controller_fixture
from test_runtime import run_lua


def run(body):
    script=controller_fixture(body)
    script=script.replace("local State=dofile('src/state.lua')", """
local State=dofile('src/state.lua')
local reconciled,observations,refreshes,unlock,fail_refresh,pending=nil,0,0,false,false,false
local stat_calls,stat_unlocked=0,false
local original_reconcile=State.reconcile_owned
State.reconcile_owned=function(st,cat,owned)
 reconciled=owned
 return original_reconcile(st,cat,owned)
end
""")
    script=script.replace("end end,\n}end}\nlocal CatalogData", "end;return nil,'not ship Armory'end,\n}end}\nlocal CatalogData")
    a=script.index('local CatalogProbe={new=function()')
    b=script.index('local Panel=',a)
    script=script[:a]+"""
catalog.c={appearance_id='look-c',stats_id='stats-c',passive_variant_id='perk-c'}
local live={catalog=catalog,owned={a=true,b=true},source_commit='fixture',counts={kits=3,owned_armors=2},
 context={labels={appearance_id={},stats_id={},passive_variant_id={}},stats_profiles={}},capabilities={ownership_verified=true}}
function live.refresh_ownership()
 refreshes=refreshes+1
 if fail_refresh then live.owned={};live.capabilities.ownership_verified=false;return 'failed','fixture race'end
 if not pending then pending=true;return 'resolving'end
 pending=false
 local changed=live.owned.c~=unlock or not live.capabilities.ownership_verified
 live.owned={a=true,b=true,c=unlock};live.counts.owned_armors=unlock and 3 or 2
 live.capabilities.ownership_verified=true
 return 'ready',changed
end
local ArmorStatResolver={new=function()return {step=function()
 return 'ready',{contract={},verify=function()return true end}
end}end}
local PlayerCustomizationProbe={new=function()return {sample=function()
 return {current={body_type=0}}
end}end}
local ArmorBaseStats={choices=function(result)
 assert(result.capabilities.ownership_verified,'base stats called without ownership')
 stat_calls=stat_calls+1;stat_unlocked=result.owned.c==true
 local ids={};for id,owned in pairs(result.owned)do
  if owned then ids[#ids+1]=result.catalog[id].stats_id end
 end
 return {{stats_ids=ids,verified=true,base_values={armor_rating=50,speed=550,stamina_regen=125}}}
end}
local CatalogProbe={new=function()
 observations=observations+1
 return {step=function()return 'ready',live end}
end}
"""+script[b:]
    run_lua(script)


def test_unlock_refreshes_allowed_list_in_same_menu_without_resetting_applied_patch():
    run("""
click(State.variant_action('Alpha'))
assert(applied==1 and resets==0 and observations==1)
local records=live.catalog;local context=live.context
unlock=true;now=now+2001;update()
assert(refreshes==1 and not reconciled.c,'partial observation published')
now=now+16;update()
assert(reconciled.c and live.counts.owned_armors==3)
assert(observations==1 and resets==0 and applied==1 and last_view.active)
assert(live.catalog==records and live.context==context)
local before=refreshes;now=now+100;update();assert(refreshes==before,'polling every frame')
""")


def test_menu_reentry_refreshes_active_variant_ownership_before_next_poll_deadline():
    run("""
click(State.variant_action('Alpha'))
now=now+2001;update();now=now+16;update()
local before=refreshes
visible=false;update()
unlock=true;visible=true;now=now+16;update();now=now+16;update()
assert(refreshes==before+2 and reconciled.c,'reentry kept old ownership')
assert(observations==1 and resets==0 and last_view.active)
""")


def test_failed_refresh_revokes_ui_authorization_then_recovers_without_restart():
    run("""
click(State.variant_action('Alpha'))
fail_refresh=true;now=now+2001;update()
assert(reconciled==nil and next(live.owned)==nil)
assert(applied==1 and resets==0)
fail_refresh=false;unlock=true;now=now+2001;update();now=now+16;update()
assert(reconciled.c and observations==1 and last_view.active)
""")


def test_failed_refresh_does_not_permanently_disable_base_stat_resolution():
    run("""
click(State.variant_action('Alpha'))
assert(stat_calls>0 and not stat_unlocked)
local before=stat_calls
fail_refresh=true;now=now+2001;update()
assert(reconciled==nil and stat_calls==before,'unavailable ownership reached stat formula')
fail_refresh=false;unlock=true;now=now+2001;update();now=now+16;update()
assert(reconciled.c and stat_unlocked and stat_calls>before,'stats stayed disabled after recovery')
assert(live.context.stats_profiles['stats-c'].base_values_verified)
assert(observations==1 and resets==0 and last_view.active)
""")
