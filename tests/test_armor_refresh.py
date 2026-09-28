"""Frame-separated native refresh with real owned ids and no cache fabrication."""
from test_runtime import run_lua

FIXTURE = '''
local R=dofile('src/armor_refresh.lua')
local A,B,C='armor:00000001','armor:00000002','armor:00000003'
local owned={[A]=true,[B]=true,[C]=true}
local live={session='ship:local1',other_key='helmet,cape,weapon,profile-fields',pending_nonarmor=false,
 controller_armor_id=A,profile_armor_id=A,request_armor_id=A,cache_armor_id=A,cache_passive=20}
local calls={}
local proof=true
local fail_commit=false
local bridge={capabilities={commit_verified=true,cache_layout_verified=true}}
bridge.snapshot=function()local copy={};for k,v in pairs(live)do copy[k]=v end;return copy end
bridge.verify=function(s)
 if not proof then return false end
 for k,v in pairs(s)do if live[k]~=v then return false end end
 return true
end
bridge.verify_owned=function(ids)for _,id in ipairs(ids)do if not owned[id]then return false end end;return #ids>0 end
bridge.owned_armors=function()return {A,B,C}end
bridge.commit_owned=function(id,expected)
 assert(bridge.verify(expected)and owned[id]);calls[#calls+1]=id
 live.controller_armor_id=id
 if fail_commit then return nil,'native commit uncertain'end
 live.profile_armor_id=id;live.request_armor_id=id
 return true
end
local refresh=R.new(bridge)
local function settle(id,passive)live.cache_armor_id=id;live.cache_passive=passive end
local function start(target,extra)
 extra=extra or {};extra.target_id=target;extra.passive_enum=1;extra.donor_ids={target,C};extra.timeout_ms=250
 return refresh:begin(extra,0)
end
'''


def test_same_carrier_waits_for_alternate_then_target_and_exact_passive_cache():
    run_lua(FIXTURE + '''
assert(start(A));assert(#calls==0)
assert(refresh:step(0)=='wait_alternate');assert(calls[1]==B and live.cache_armor_id==A)
assert(refresh:step(1)=='wait_alternate')
settle(B,7);assert(refresh:step(2)=='wait_alternate');assert(refresh:step(3)=='commit_target')
refresh:step(3);assert(#calls==1) -- A repeated frame cannot issue another commit.
assert(refresh:step(4)=='wait_target');assert(calls[2]==A)
settle(A,20);assert(refresh:step(5)=='wait_target') -- Old perk cache is insufficient.
settle(A,1);assert(refresh:step(6)=='wait_target')
local phase,evidence=refresh:step(7)
assert(phase=='complete'and evidence.status=='native_armor_and_passive_cache_verified')
assert(not evidence.visual_verified and not evidence.gameplay_verified and not evidence.needs_recovery)
assert(#calls==2 and live.other_key=='helmet,cape,weapon,profile-fields')
''')


def test_different_carrier_commits_once_and_nonarmor_changes_never_commit():
    run_lua(FIXTURE + '''
assert(start(B));assert(refresh:step(0)=='wait_target');assert(#calls==1 and calls[1]==B)
settle(B,1);refresh:step(1);assert(refresh:step(2)=='complete')
local second=R.new(bridge);live.pending_nonarmor=true
assert(not second:begin({target_id=A,passive_enum=1},3));assert(#calls==1)
''')


def test_alternate_timeout_returns_to_real_target_without_claiming_refresh():
    run_lua(FIXTURE + '''
assert(start(A));refresh:step(0)
assert(refresh:step(251)=='commit_restore'and #calls==1)
assert(refresh:step(252)=='wait_restore'and #calls==2 and calls[2]==A)
refresh:step(253)
local phase,result=refresh:step(254)
assert(phase=='failed'and result.status=='target_committed_refresh_unverified')
assert(not result.needs_recovery and result.reason:find('alternate cache'))
assert(live.profile_armor_id==A and live.request_armor_id==A)
''')


def test_user_equipment_change_or_lost_donor_blocks_further_mutation():
    run_lua(FIXTURE + '''
assert(start(A));refresh:step(0)
live.other_key='user changed helmet'
local phase,result=refresh:step(1)
assert(phase=='blocked'and result.needs_recovery and #calls==1)
assert(not refresh:recover_target()and #calls==1)
live.other_key='helmet,cape,weapon,profile-fields';owned[C]=false
-- Explicit target recovery requires only the real target's ownership.
assert(refresh:recover_target());refresh:step(2)
assert(#calls==2 and calls[2]==A)
''')


def test_uncertain_native_commit_is_not_retried_until_explicit_guarded_recovery():
    run_lua(FIXTURE + '''
assert(start(A));fail_commit=true
local phase,result=refresh:step(0)
assert(phase=='blocked'and result.needs_recovery and #calls==1)
refresh:step(1);assert(#calls==1)
fail_commit=false;assert(refresh:recover_target())
assert(refresh:step(2)=='wait_restore'and calls[2]==A)
refresh:step(3);assert(refresh:step(4)=='failed')
''')


def test_capability_ownership_and_session_guards_and_cancel_before_first_mutation():
    run_lua(FIXTURE + '''
bridge.capabilities.commit_verified=false;assert(not start(A));assert(#calls==0)
bridge.capabilities.commit_verified=true;owned[B]=false
assert(not start(A,{alternate_id=B}));assert(#calls==0)
owned[B]=true;assert(start(A));assert(refresh:cancel());assert(refresh:step(0)=='cancelled'and #calls==0)
assert(start(A));refresh:step(0);live.session='different local player'
assert(refresh:step(1)=='blocked'and #calls==1)
assert(not refresh:recover_target())
''')


def test_unchanged_original_armor_is_observed_without_alternate_or_native_commit():
    run_lua(FIXTURE+'''
settle(A,1);assert(start(A,{accept_current=true}))
assert(refresh:step(0)=='wait_target'and #calls==0)
local phase,evidence=refresh:step(1)
assert(phase=='complete'and evidence.commits==0 and not evidence.target_prepared)
assert(evidence.status=='native_armor_and_passive_cache_verified')
''')


def test_unchanged_path_cannot_bypass_patch_preparation_or_wrong_passive_cache():
    run_lua(FIXTURE+'''
assert(not start(A,{accept_current=true,prepare_target=function()error('must not run')end}))
assert(#calls==0)
assert(start(A,{accept_current=true})) -- Current cached passive is 20, desired is 1.
assert(refresh:step(0)=='wait_alternate'and calls[1]==B)
''')



def test_restoring_old_carrier_can_release_directly_to_an_unchanged_vanilla_target():
    run_lua(FIXTURE+r"""
owned[C]=nil
bridge.owned_armors=function()return {A,B}end
local restored=0
assert(refresh:begin({target_id=B,passive_enum=7,donor_ids={A,B},mutation_ids={A},
 target_unchanged=true,prepare_target=function()
  assert(live.request_armor_id==B and live.cache_armor_id==B)
  restored=restored+1;return true
 end},0))
assert(refresh:step(0)=='wait_alternate'and calls[1]==B and restored==0)
assert(refresh:step(1)=='wait_alternate'and restored==0)
settle(B,7);refresh:step(2);refresh:step(3);refresh:step(4)
assert(restored==1 and calls[2]==B)
refresh:step(5);assert(refresh:step(6)=='complete')
""")


def test_unchanged_target_flag_cannot_hide_a_target_mutation_or_missing_plan():
    run_lua(FIXTURE+r"""
for _,extra in ipairs({
 {target_unchanged=true},
 {target_unchanged=true,prepare_target=function()return true end},
 {target_unchanged=true,mutation_ids={A},prepare_target=function()return true end},
})do assert(not start(A,extra))end
assert(#calls==0)
""")
