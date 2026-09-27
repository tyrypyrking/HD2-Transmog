"""Synthetic memory tests for narrowly scoped visual writes and verified reset."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run_lua(code):
    result = subprocess.run(
        ['luajit', '-'], input=code, text=True, cwd=ROOT,
        capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


FIXTURE = '''
local Patch=dofile('src/appearance_patch.lua')
local memory, writes={},{}
local function u32(n)
 local out={};for i=1,4 do out[i]=string.char(n%256);n=math.floor(n/256) end
 return table.concat(out)
end
local function ptr(n) return u32(n)..u32(0) end
local function put(address,bytes)
 for i=1,#bytes do memory[address+i-1]=bytes:sub(i,i) end
end
local function get(address,size)
 local out={};for i=1,size do if not memory[address+i-1] then return nil end;out[i]=memory[address+i-1] end
 return table.concat(out)
end
local function record(address,item,package,reversed)
 local bodies_at,pieces_at=address+128,address+256
 local raw=u32(item)..string.rep('I',24)..u32(item+20)..package..u32(0)..string.rep('P',4)..ptr(bodies_at)..u32(1)..u32(0)
 local bodyraw=u32(1)..string.rep('B',4)..ptr(pieces_at)..u32(2)..u32(0)
 local pieces={}
 for i=1,2 do
  local slot=reversed and 3-i or i
  local piece=u32(item)..u32(slot)..u32(slot)..u32(0)..u32(2)..string.rep(string.char(65+item),76)
  pieces[i]={address=pieces_at+(i-1)*96,bytes=piece,slot=slot,kind=0,weight=2,path='fixture'}
  put(pieces[i].address,piece)
 end
 put(address,raw);put(bodies_at,bodyraw)
 return {address=address,bytes=raw,item_id=item,category=0,
  bodies={{address=bodies_at,bytes=bodyraw,type=1,pieces=pieces}}}
end
local source=record(100000,1,'SOURCEPK',true)
local target=record(200000,2,'TARGETPK',false)
local result={
 catalog={a={appearance_id='look-a',stats_id='native-stats:00000001',passive_variant_id='passive-a'},
          b={appearance_id='look-b',stats_id='native-stats:00000002',passive_variant_id='passive-b'}},
 owned={a=true,b=true},records={a=source,b=target},
 capabilities={kit_records_verified=true,ownership_verified=true},
}
local request={appearance_id='look-a',stats_id='native-stats:00000002',passive_variant_id='passive-b'}
local fresh=true
local bridge={read=get,write=function(address,bytes)
 writes[#writes+1]={address=address,bytes=bytes};put(address,bytes);return true
end,verify=function(_,_,source_id,target_id,phase)
 assert(source_id=='a' and target_id=='b')
 return fresh or phase=='rollback' or phase=='reset'
end}
local patch=Patch.new(bridge)
'''


def test_visual_swap_changes_only_two_ranges_and_reset_restores_original_bytes():
    run_lua(FIXTURE + '''
local plan=assert(patch:plan(result,request))
assert(plan.source_id=='a' and plan.target_id=='b' and plan.address==nil)
assert(#writes==0)
-- Exposed labels cannot change the privately retained write proposal.
plan.target_id='evil';plan.request.stats_id='wrong'
local ok,evidence=patch:apply(plan);assert(ok)
assert(evidence.status=='memory_readback_verified' and evidence.appearance_verified==false)
assert(#writes==2 and writes[1].address==target.address+32 and #writes[1].bytes==8)
assert(writes[2].address==target.address+48 and #writes[2].bytes==16)
local applied=get(target.address,64)
assert(applied:sub(1,32)==target.bytes:sub(1,32)) -- identity and passive untouched
assert(applied:sub(41,48)==target.bytes:sub(41,48))
assert(get(source.address,64)==source.bytes)
assert(patch:is_active())
assert(not patch:plan(result,request))
local restored,reset=patch:reset();assert(restored and reset.status=='original_memory_restored')
assert(get(target.address,64)==target.bytes and #writes==4)
assert(not patch:is_active())
assert(not patch:apply(plan)) -- Plans are single-use.
''')


def test_rejects_stale_ownership_changed_observations_aliases_and_extra_passives():
    run_lua(FIXTURE + '''
result.owned.a=false;assert(not patch:plan(result,request));result.owned.a=true
request.passive_variant_id='passive-a';assert(not patch:plan(result,request));request.passive_variant_id='passive-b'
result.records.alias={address=target.address};assert(not patch:plan(result,request));result.records.alias=nil
fresh=false;assert(not patch:plan(result,request));fresh=true
local plan=assert(patch:plan(result,request))
fresh=false;assert(not patch:apply(plan));assert(#writes==0)
fresh=true;plan=assert(patch:plan(result,request))
put(source.bodies[1].pieces[1].address,string.rep('X',96))
assert(not patch:apply(plan) and #writes==0)
''')


def test_rejects_profile_changes_and_duplicate_piece_keys_despite_equal_counts():
    run_lua(FIXTURE + '''
local piece=target.bodies[1].pieces[1]
piece.weight=1
piece.bytes=piece.bytes:sub(1,16)..u32(1)..piece.bytes:sub(21)
put(piece.address,piece.bytes)
local plan,why=patch:plan(result,request)
assert(not plan and why:find('profiles differ'))
piece.weight=2;piece.bytes=piece.bytes:sub(1,16)..u32(2)..piece.bytes:sub(21);put(piece.address,piece.bytes)
piece.slot=2;piece.bytes=piece.bytes:sub(1,8)..u32(2)..piece.bytes:sub(13);put(piece.address,piece.bytes)
plan,why=patch:plan(result,request)
assert(not plan and why:find('duplicate'))
assert(#writes==0)
''')


def test_partial_failure_rolls_back_both_changed_ranges_and_verifies():
    run_lua(FIXTURE + '''
local calls=0
bridge.write=function(address,bytes)
 calls=calls+1
 if calls==2 then put(address,bytes:sub(1,5));return false end
 put(address,bytes);return true
end
local ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok and why:find('rollback verified'))
assert(calls==4 and get(target.address,64)==target.bytes)
assert(not patch:is_active())
''')


def test_throw_after_write_and_readback_failure_are_rolled_back():
    run_lua(FIXTURE + '''
local calls=0
bridge.write=function(address,bytes)
 calls=calls+1;put(address,bytes)
 if calls==1 then error('writer failed after copying') end
 return true
end
local ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok and why:find('rollback verified'))
assert(get(target.address,64)==target.bytes and not patch:is_active())
local fail_next=false
bridge.write=function(address,bytes) put(address,bytes);fail_next=true;return true end
bridge.read=function(address,size)
 if fail_next then fail_next=false;return nil end
 return get(address,size)
end
ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok)
-- Restoration itself also triggers this fixture's unreadable readback. The
-- bytes are restored but retained evidence permits an explicit later reset.
bridge.read=get;bridge.write=function(address,bytes)put(address,bytes);return true end
assert(patch:reset())
assert(get(target.address,64)==target.bytes and not patch:is_active())
''')


def test_reset_does_not_overwrite_conflicting_changes_and_retains_recovery_evidence():
    run_lua(FIXTURE + '''
local plan=assert(patch:plan(result,request));assert(patch:apply(plan))
put(target.address+32,'FOREIGN!')
local ok,why=patch:reset()
assert(not ok and why:find('conflict'))
assert(get(target.address+32,8)=='FOREIGN!')
assert(not patch:plan(result,request))
local active,reason=patch:is_active();assert(active==nil and reason:find('attention'))
-- Resolve only the conflicting bytes; the original evidence is still kept.
put(target.address+32,source.bytes:sub(33,40))
assert(patch:reset())
assert(get(target.address,64)==target.bytes)
''')


def test_freshness_change_after_first_write_restores_even_when_ownership_is_lost():
    run_lua(FIXTURE + '''
local calls=0
bridge.write=function(address,bytes)
 calls=calls+1;put(address,bytes);fresh=false;return true
end
local ok,why=patch:apply(assert(patch:plan(result,request)))
assert(not ok and why:find('rollback verified'))
assert(calls==2 and get(target.address,64)==target.bytes)
''')


def test_partial_throw_during_restoration_keeps_updated_evidence_for_retry():
    run_lua(FIXTURE + '''
assert(patch:apply(assert(patch:plan(result,request))))
local calls=0
bridge.write=function(address,bytes)
 calls=calls+1
 if calls==1 then put(address,bytes:sub(1,2));error('partial restoration') end
 put(address,bytes);return true
end
local restored,why=patch:reset()
assert(not restored and why:find('restoration'))
assert(not patch:plan(result,request))
bridge.write=function(address,bytes)put(address,bytes);return true end
assert(patch:reset())
assert(get(target.address,64)==target.bytes and not patch:is_active())
''')
