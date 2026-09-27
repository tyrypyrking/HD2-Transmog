"""Carrier changes wait for native release and never replay preparation."""
from test_runtime import run_lua
from test_armor_refresh import FIXTURE as REFRESH_FIXTURE
from test_variant_session import FIXTURE as SESSION_FIXTURE


def test_same_worn_target_stays_unmodified_until_alternate_cache_is_stable():
    run_lua(SESSION_FIXTURE + '''
live.controller_armor_id=B;live.profile_armor_id=B;live.request_armor_id=B;live.cache_armor_id=B
ready(0)
assert(s:apply(2)and plans==0 and applies==0 and resets==0)
s:step(2)
assert(#commits==1 and commits[1]==A and plans==0 and applies==0 and resets==0)
for now=3,10 do s:step(now)end
assert(plans==0 and applies==0 and resets==0 and live.cache_armor_id==B)
live.cache_armor_id=A;s:step(11);s:step(11)
assert(plans==0 and #commits==1)
s:step(12);assert(plans==0 and #commits==1)
s:step(13)
assert(plans==1 and applies==1 and resets==0 and #commits==2 and commits[2]==B)
live.cache_armor_id=B;live.cache_passive=1;s:step(14);s:step(15)
assert(s.phase=='equipped'and #previews==1 and count('variant.equipped')==1)
''')


def test_replacing_worn_patch_excludes_both_carriers_before_resetting_previous():
    run_lua(SESSION_FIXTURE + '''
ready(0);equip(2)
local next_request={appearance_id=A,stats_id='native-stats:00000003',passive_variant_id='perk-b'}
ready(10,'Different carrier',next_request)
assert(s:apply(12)and active_request.stats_id==request.stats_id and resets==0)
s:step(12)
assert(#commits==2 and commits[2]==A and applies==1 and resets==0)
live.cache_armor_id=A;s:step(13);s:step(14)
assert(applies==1 and resets==0 and active_request.stats_id==request.stats_id)
s:step(15)
assert(#commits==3 and commits[3]==C and applies==2 and resets==1)
assert(active_request.stats_id==next_request.stats_id)
live.cache_armor_id=C;live.cache_passive=7;s:step(16);s:step(17)
assert(s.phase=='equipped'and s:verify_composition(C)and not s:verify_composition(B))
assert(#previews==2)
''')


def test_mutation_carrier_cannot_be_an_explicit_alternate():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
local request={mutation_ids={A,B},alternate_id=A,prepare_target=function()prepared=prepared+1;return true end}
assert(not start(B,request)and #calls==0 and prepared==0)
request.alternate_id=B
assert(not start(B,request)and #calls==0 and prepared==0)
request.alternate_id=C
assert(start(B,request));assert(refresh:step(0)=='wait_alternate')
assert(calls[1]==C and prepared==0)
''')


def test_alternate_timeout_and_restoration_never_prepare_target():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
assert(start(A,{prepare_target=function()prepared=prepared+1;return true end}))
refresh:step(0)
assert(refresh:step(251)=='commit_restore'and prepared==0)
assert(refresh:step(252)=='wait_restore'and prepared==0)
refresh:step(253)
local phase,evidence=refresh:step(254)
assert(phase=='failed'and prepared==0 and #calls==2 and calls[2]==A)
assert(not evidence.preparation_attempted and not evidence.target_prepared)
''')


def test_unprepared_timeout_does_not_remember_a_custom_variant_as_equipped():
    run_lua(SESSION_FIXTURE + '''
live.controller_armor_id=B;live.profile_armor_id=B;live.request_armor_id=B;live.cache_armor_id=B
ready(0);assert(s:apply(2));s:step(2)
assert(commits[1]==A and plans==0)
s:step(5002);s:step(5003);s:step(5004);s:step(5005)
assert(s.phase=='apply_failed'and not s:busy()and not s:has_committed())
assert(#commits==2 and commits[2]==B and plans==0 and applies==0 and resets==0)
assert(not s:is_active()and count('variant.equipped')==0)
assert(s:leave()and not s:has_committed())
''')


def test_cancel_before_or_after_alternate_never_prepares_target():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
local request={prepare_target=function()prepared=prepared+1;return true end}
assert(start(A,request));assert(refresh:cancel())
assert(refresh:step(0)=='cancelled'and #calls==0 and prepared==0)
assert(start(A,request));refresh:step(0);settle(B,7)
refresh:step(1);assert(refresh:step(2)=='commit_target')
assert(refresh:cancel());assert(refresh:step(3)=='wait_restore')
settle(A,20);refresh:step(4)
local phase,evidence=refresh:step(5)
assert(phase=='cancelled'and #calls==2 and prepared==0)
assert(not evidence.preparation_attempted and not evidence.target_prepared)
''')


def test_cache_returning_to_affected_carrier_blocks_preparation():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
assert(start(A,{prepare_target=function()prepared=prepared+1;return true end}))
refresh:step(0);settle(B,7);refresh:step(1);refresh:step(2)
-- Cached IDs were stable, but fresh evidence on the preparation tick wins.
settle(A,20)
local phase,evidence=refresh:step(3)
assert(phase=='blocked'and prepared==0 and #calls==1)
assert(evidence.reason:find('transitioning')and not evidence.preparation_attempted)
for now=4,30 do refresh:step(now)end
assert(prepared==0 and #calls==1)
''')


def test_failed_preparation_runs_once_and_never_commits_selected_target():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
assert(start(A,{prepare_target=function()prepared=prepared+1;return nil,'composition rejected' end}))
refresh:step(0);settle(B,7);refresh:step(1);refresh:step(2)
local phase,evidence=refresh:step(3)
assert(phase=='blocked'and prepared==1 and #calls==1 and calls[1]==B)
assert(evidence.preparation_attempted and not evidence.target_prepared)
assert(evidence.reason:find('composition rejected'))
for now=4,30 do refresh:step(now)end
assert(prepared==1 and #calls==1)
assert(refresh:recover_target());refresh:step(31)
assert(prepared==1 and #calls==2 and calls[2]==A)
''')


def test_preparation_that_changes_equipment_cannot_trigger_a_native_commit():
    run_lua(REFRESH_FIXTURE + '''
local prepared=0
assert(start(B,{prepare_target=function()
 prepared=prepared+1;live.other_key='equipment changed during preparation';return true
end}))
local phase,evidence=refresh:step(0)
assert(phase=='failed'and #calls==0 and prepared==1)
assert(evidence.target_prepared and evidence.reason:find('equipment changed'))
for now=1,30 do refresh:step(now)end
assert(#calls==0 and prepared==1)
''')
