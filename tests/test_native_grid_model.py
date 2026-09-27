"""Read-only logical model and pure proposal invariants; no game process used."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = r'''
local ffi=require('ffi')
local M=dofile('src/native_grid_model.lua')
local raw=string.rep('\0',0xa0000);local base=0x100000
local function b(n)local t={};for i=1,4 do t[i]=string.char(n%256);n=math.floor(n/256)end;return table.concat(t)end
local function f(n)return ffi.string(ffi.new('float[1]',n),4)end
local function put(at,s)raw=raw:sub(1,at)..s..raw:sub(at+#s+1)end
local function read(at,n)at=at-base;assert(at>=0 and at+n<=#raw);return raw:sub(at+1,at+n)end
put(0x91f14,b(4));put(0x92984,b(9));put(0x92748,b(3))
put(0x91f18,f(224)..f(196)..f(224)..f(224))
put(0x92318,b(3)..b(2)..b(3)..b(1))
put(0x9274c,b(0)..b(2)..b(3)..b(4));put(0x927d0,b(0)..b(5)..b(8))
for i=1,9 do put(0x92990+(i-1)*4,b(100+i))end
put(0x928d8,b(0));put(0x928e8,b(2)..b(1)..b(1));put(0x92988,b(107))
put(0x92960,f(0));put(0x92968,f(868))
local current=true;local owned=true;local lookup={}
for i=1,9 do lookup[100+i]={kit_id=string.format('armor:%08x',i),owned=true}end
local guard={schema_verified=true,verify=function()return current end,offer_lookup=lookup,
 verify_owned=function(ids)assert(#ids>=1);return owned end}
local function sample()return M.capture(read,base,guard)end
local cards={{key='saved:one',kind='variant',kit_id='armor:00000001'},
 {key='saved:two',kind='variant',kit_id='armor:00000002'},
 {key='create',kind='create',kit_id='armor:00000001'}}
local options={columns=3,card_height=224}
'''


def run_lua(code):
    result = subprocess.run(['luajit', '-'], input=FIXTURE + code, text=True,
                            capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_capture_preserves_rows_groups_and_flattened_selection_without_writes():
    run_lua('''
local original=raw;local model=assert(sample());assert(raw==original)
assert(model.row_count==4 and model.item_count==9 and model.height_sum==868)
assert(model.content_matches_height_sum and model.group_partition_verified)
assert(model.rows[3].first_item==5 and model.rows[3].top==420)
assert(model.groups[2].first_item==5 and model.groups[2].end_item==8)
assert(model.selected_index==6 and model.selected_offer==107 and model.selected_offer_matches)
assert(model.mutation_supported==false and model.apply==nil)
local text=M.format(model);assert(text:find('mutation_supported=false',1,true))
assert(text:find('kit=armor:00000001 owned=true',1,true))
assert(not text:find(tostring(base),1,true))
''')


def test_prefix_keeps_original_rows_and_offer_order_with_separate_card_identity():
    run_lua('''
local source=assert(sample());local original=raw;local plan=assert(M.plan_prefix(source,cards,options))
assert(raw==original and source.row_count==4 and #source.offers==9)
assert(plan.status=='detached_prefix_proposal' and not plan.mutation_supported)
assert(not plan.native_capacity_verified and plan.writes==nil and plan.apply==nil)
assert(plan.added_items==3 and plan.added_rows==1)
assert(plan.groups[1].label=='Custom Variant' and plan.groups[2].first_row==1)
assert(plan.cards[1].offer_id==plan.cards[3].offer_id and plan.cards[1].key~=plan.cards[3].key)
assert(plan.cards[3].opaque and plan.cards[3].requires_input_capture)
for i,item in ipairs(source.offers)do assert(plan.offers[i+3].offer_id==item.offer_id)end
for i,row in ipairs(source.rows)do assert(plan.rows[i+1].height==row.height and plan.rows[i+1].item_count==row.item_count)end
assert(plan.selected_row==3 and plan.selected_column==1 and plan.selected_group==2)
assert(plan.offers[plan.original_selection_index+1].offer_id==107)
assert(plan.groups[2].item_threshold==nil and plan.content==nil)
plan.offers[4].offer_id=999;assert(source.offers[1].offer_id==101)
''')


def test_partial_custom_row_has_no_fabricated_padding_offers():
    run_lua('''
table.insert(cards,3,{key='saved:three',kind='variant',kit_id='armor:00000003'})
local source=assert(sample());local plan=assert(M.plan_prefix(source,cards,options))
assert(plan.added_rows==2 and plan.added_items==4 and #plan.offers==13)
assert(plan.rows[1].item_count==3 and plan.rows[2].item_count==1)
assert(plan.rows[3].first_item==4 and plan.groups[2].first_row==2)
''')


def test_duplicate_native_offers_are_diagnostic_but_never_prefix_ready():
    run_lua('''
put(0x92990+4,b(101));local source=assert(sample())
assert(#source.duplicate_offers==1 and source.duplicate_offers[1].first==0)
local plan,why=M.plan_prefix(source,cards,options);assert(not plan and why:find('already ambiguous'))
''')


def test_unowned_or_absent_appearance_cannot_back_saved_or_create_card():
    run_lua('''
lookup[101].owned=false;local source=assert(sample())
local plan,why=M.plan_prefix(source,cards,options);assert(not plan and why:find('owned appearance'))
lookup[101].owned=true;lookup[101].kit_id=nil;source=assert(sample())
assert(not M.plan_prefix(source,cards,options))
''')


def test_ownership_and_snapshot_are_checked_again_after_planning():
    run_lua('''
local source=assert(sample());owned=false;assert(not M.plan_prefix(source,cards,options))
owned=true;current=false;assert(not M.plan_prefix(source,cards,options))
current=true;local calls=0;source.verify_owned=function()calls=calls+1;return calls==1 end
local plan,why=M.plan_prefix(source,cards,options);assert(not plan and why:find('evidence changed'))
''')


def test_bad_counts_floats_and_concurrent_change_fail_capture():
    run_lua('''
local original=raw
put(0x92318,b(4));assert(not sample());raw=original
put(0x91f18,b(0x7fc00000));assert(not sample());raw=original
put(0x91f14,b(129));assert(not sample());raw=original
put(0x92984,b(257));assert(not sample());raw=original
put(0x92748,b(33));assert(not sample());raw=original
current=false;assert(not sample())
''')


def test_unused_terminal_is_ignored_but_bad_group_threshold_blocks_plan():
    run_lua('''
put(0x9274c+12,b(0xffffffff));put(0x927d0+8,b(0xffffffff))
local source=assert(sample());assert(source.group_row_terminal==0xffffffff)
assert(source.raw_group_starts[3]==3 and #source.warnings>=2)
assert(not source.group_partition_verified and source.groups[3].bounded_row_interval)
assert(source.groups[3].end_item==9 and source.groups[3].item_threshold==0xffffffff)
local text=M.format(source);assert(text:find('group_row_terminal=4294967295',1,true))
assert(text:find('raw_group_start index=2 value=3',1,true))
assert(text:find('first-item boundary differs',1,true))
assert(not M.plan_prefix(source,cards,options))
put(0x9274c+12,b(0));source=assert(sample())
assert(source.group_row_terminal==0 and not source.group_partition_verified)
assert(not M.plan_prefix(source,cards,options))
put(0x927d0+8,b(8));source=assert(sample())
assert(source.group_partition_verified and source.groups[3].end_row==4)
''')


def test_partial_group_partition_and_selection_mismatch_remain_unplannable():
    run_lua('''
put(0x9274c,b(1));local source=assert(sample());assert(not source.group_partition_verified)
assert(not M.plan_prefix(source,cards,options));put(0x9274c,b(0))
put(0x92988,b(102));source=assert(sample());assert(not source.selected_offer_matches)
assert(not M.plan_prefix(source,cards,options))
put(0x92988,b(107));put(0x928f0,b(0));source=assert(sample());assert(not source.selected_group_matches)
assert(not M.plan_prefix(source,cards,options))
''')


def test_requires_measured_shape_unique_keys_and_one_final_create_card():
    run_lua('''
local source=assert(sample())
assert(not M.plan_prefix(source,cards,{columns=3,card_height=200}))
cards[3].key=cards[1].key;assert(not M.plan_prefix(source,cards,options));cards[3].key='create'
cards[1].kind='create';assert(not M.plan_prefix(source,cards,options));cards[1].kind='variant'
cards[3].kind='variant';assert(not M.plan_prefix(source,cards,options))
''')


def test_height_sum_is_observation_not_an_invented_header_formula():
    run_lua('''
put(0x92968,f(900));local source=assert(sample())
assert(not source.content_matches_height_sum and source.height_sum==868)
local plan=assert(M.plan_prefix(source,cards,options))
assert(plan.content==nil and plan.rows[2].height==224)
''')


LOGICAL_PROOF = r'''
local solver_rva,groups_rva=0x18000,0x19000
put(base+solver_rva,('488bc45355565741544155415641574881ecf800000083b94827090001'):gsub('%x%x',function(h)return string.char(tonumber(h,16))end))
put(base+groups_rva,('458b86e82809004539864c270900'):gsub('%x%x',function(h)return string.char(tonumber(h,16))end))
local old_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 local ops
 if rva==solver_rva then ops={'cmp dword [rcx+0x92748], +0x01','mov ecx, [rcx+0x91f14]',
  'movss xmm0, [rsi+r15*4+0x91f18]','add r13d, [rsi+r15*4+0x92318]',
  'subss xmm6, xmm0','cmp r13d, [rsi+rax*4+0x927d0]',
  'mov [rsi+0x928d8], r15d','movss [rsi+0x92964], xmm6'}
 elseif rva==groups_rva then ops={'mov r8d, [r14+0x928e8]','cmp [r14+0x9274c], r8d',
  'cmp ecx, edx','lea esi, [rcx+0x1]','cmp [r14+rsi*4+0x9274c], r8d',
  'lea eax, [rsi-0x1]','mov [r14+0x928f0], eax'}
 else return old_decode(raw,rva)end
 local out={};for i,op in ipairs(ops)do out[i]={rva=rva+i,op=op}end;return out
end
put(grid+0x91f18,f(196));put(grid+0x92748,b(1,4));put(grid+0x9274c,b(0,4)..b(1,4))
put(grid+0x927d0,b(0,4));put(grid+0x928e8,b(0,4)..b(1,4)..b(0,4))
put(grid+0x92988,b(77,4));put(grid+0x92968,f(196))
'''


def test_logical_inspector_uses_current_proofs_and_never_invokes_backend():
    from test_native_grid import run_lua as run_native, SELECTION, HIGHLIGHT
    run_native(SELECTION + HIGHLIGHT + LOGICAL_PROOF + '''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local model=assert(g:inspect_model(catalog))
assert(model.item_count==2 and model.offers[1].kit_id=='armor:00005678')
assert(model.offers[2].owned and model.selected_offer_matches)
assert(consumed==0 and moves==0 and sizes==nil and highlighted==0)
put(menu+0x4294,b(0,4));assert(not model.verify() and not g:inspect_model(catalog))
''')


def test_missing_or_rejected_optional_logical_proof_does_not_disable_existing_grid():
    from test_native_grid import run_lua as run_native, SELECTION, HIGHLIGHT
    run_native(SELECTION + HIGHLIGHT + LOGICAL_PROOF + '''
put(base+groups_rva,'X')
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(not g:inspect_model(catalog));assert(g:consume_select() and consumed==1)
assert(g:snapshot(catalog).identity_mapping_verified)
''')


def test_logical_inspector_rejects_changed_code_and_model_read_race():
    from test_native_grid import run_lua as run_native, SELECTION, HIGHLIGHT
    run_native(SELECTION + HIGHLIGHT + LOGICAL_PROOF + '''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local model=assert(g:inspect_model(catalog))
put(base+solver_rva+100,'X');assert(not model.verify() and not g:inspect_model(catalog))
put(base+solver_rva+100,'\0');assert(g:inspect_model(catalog))
local original=bridge.read;local hits=0
bridge.read=function(at,n)
 local data=original(at,n)
 if at==grid+0x91f18 then hits=hits+1;if hits==2 then return f(197)end end
 return data
end
local result,why=g:inspect_model(catalog)
assert(not result and why:find('changed during observation'))
''')
