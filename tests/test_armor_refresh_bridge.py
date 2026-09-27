"""Armor commit snapshots preserve actor identity, ownership and immutability."""
from test_runtime import run_lua

FIXTURE = r'''
local Bridge=dofile('src/armor_refresh_bridge.lua')
local A,B='armor:00000001','armor:00000002'
local live={session='armory',local_player_id=17,other_key='weapons|boosters',pending_nonarmor=false,
 controller_armor_id=A,profile_armor_id=A}
local actor={session_key='actor1',local_player_id=17,request_armor_id=A,cache_armor_id=A,cache_passive_enum=7,
 request={body_type=1,helmet_id=2,cape_id=3},current={body_type=1,helmet_id=2,cape_id=3}}
local native_valid,actor_valid,owned,commit_cap=true,true,true,true
local native_error,actor_error
local calls={}
local function copy(t)local out={};for k,v in pairs(t)do out[k]=v end;return out end
local catalog={owned={[A]=true,[B]=true}}
catalog.verify_owned=function(ids)
 if not owned then return false end
 for _,id in ipairs(ids)do if not catalog.owned[id]then return false end end;return true
end
local grid={}
function grid:commit_capabilities()return {commit_verified=commit_cap}end
function grid:commit_snapshot()
 if native_error then return nil,native_error end
 local snap=copy(live);snap.private_native=true;return snap
end
function grid:verify_commit(snapshot)
 if not native_valid or not snapshot.private_native then return false end
 for k,v in pairs(live)do if snapshot[k]~=v then return false end end;return true
end
function grid:commit_owned(id,snapshot,actual_catalog)
 assert(actual_catalog==catalog and snapshot.private_native)
 calls[#calls+1]=id;return true
end
local player={}
function player:sample()
 if actor_error then return nil,actor_error end
 local snap=copy(actor);snap.verify=function()
  if not actor_valid then return false end
  for k,v in pairs(actor)do if snap[k]~=v then return false end end;return true
 end;return snap
end
local b=assert(Bridge.new(grid,player,catalog))
'''


def test_snapshot_combines_commit_and_cache_evidence_and_protected_other_equipment():
    run_lua(FIXTURE + '''
local s=assert(b.snapshot());assert(b.verify(s))
assert(s.session=='armory:actor1'and s.controller_armor_id==A and s.profile_armor_id==A)
assert(s.request_armor_id==A and s.cache_armor_id==A and s.cache_passive==7)
assert(s.other_key=='weapons|boosters|1|2|3|1|2|3'and s.pending_nonarmor==false)
assert(b.capabilities.commit_verified and b.capabilities.cache_layout_verified)
assert(b.commit_owned(B,s)and calls[1]==B)
''')


def test_mutated_or_fabricated_observation_cannot_authorize_native_commit():
    run_lua(FIXTURE + '''
for _,field in ipairs({'session','other_key','controller_armor_id','profile_armor_id',
 'request_armor_id','cache_armor_id','cache_passive','pending_nonarmor'})do
 local s=assert(b.snapshot());s[field]='forged'
 assert(not b.verify(s)and not b.commit_owned(B,s))
end
local s=b.snapshot();s.extra='forged';assert(not b.verify(s))
assert(not b.verify(copy(b.snapshot()))and #calls==0)
''')


def test_native_or_actor_changes_revoke_commit_snapshot():
    run_lua(FIXTURE + '''
local s=b.snapshot();native_valid=false;assert(not b.verify(s)and not b.commit_owned(B,s))
native_valid=true;actor_valid=false;assert(not b.verify(s)and not b.commit_owned(B,s))
actor_valid=true;actor.session_key='actor2';assert(not b.verify(s))
assert(#calls==0)
''')


def test_fresh_ownership_is_checked_again_immediately_before_commit():
    run_lua(FIXTURE + '''
local s=b.snapshot();owned=false
assert(not b.verify_owned({B})and not b.commit_owned(B,s)and #calls==0)
owned=true;catalog.owned[B]=false
assert(not b.commit_owned(B,s)and #calls==0)
catalog.owned[B]=true;assert(b.commit_owned(B,s)and #calls==1)
local ids=b.owned_armors();table.sort(ids);assert(#ids==2 and ids[1]==A and ids[2]==B)
''')


def test_missing_proof_actor_mismatch_and_unreadable_snapshots_never_commit():
    run_lua(FIXTURE + '''
commit_cap=false;assert(not Bridge.new(grid,player,catalog));commit_cap=true
actor_error='actor unavailable';assert(not Bridge.new(grid,player,catalog));actor_error=nil
actor.local_player_id=99;assert(not b.snapshot());actor.local_player_id=17
native_error='menu gone';assert(not b.snapshot());native_error=nil
actor_error='actor vanished';assert(not b.snapshot())
assert(#calls==0)
''')
