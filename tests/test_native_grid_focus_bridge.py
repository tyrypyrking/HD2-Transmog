"""Exact row-focus adapter against isolated current-image and memory fakes."""
import pytest

from test_native_grid import run_lua, SELECTION, HIGHLIGHT
from test_native_grid_model import LOGICAL_PROOF
from test_native_grid_presentation_bridge import BUILDERS


FOCUS = r'''
local focus_rva=0x25000
put(base+focus_rva,unhex('48896c2420564883ec208bea488bf1'))
local focus_ops={'mov ebp, edx','mov rsi, rcx','cmp [rcx+0xaec0], edx',
 'mov [rcx+0xaec0], edx','cmp [rcx+0xaeb4], ebx','lea rdi, [rsi+0x110]',
 'imul rcx, rax, 0x2b68','movzx edx, word [rdi+0x2b5a]','cmp ebx, ebp',
 'setz al','and ax, r14w','or dx, +0x02','cmovnz dx, ax','mov [rdi+0x2b5a], dx',
 'cmp ebx, [rsi+0xaeb4]'}
local decode_focus=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==focus_rva then
  local out={};for i,op in ipairs(focus_ops)do out[i]={rva=rva+i,op=op}end
  out[#out+1]={rva=rva+230,op='ret'};return out
 end
 local out=decode_focus(raw,rva)
 local extra
 if rva==highlight_rva then
  extra={'imul rcx, rax, 0xaed0','add rcx, 0xb00','mov edx, 0xffffffff','add rcx, rdi',
   string.format('call 0x%08x',focus_rva),'mov edx, ebx','mov [rdi+0x928e4], r14d','add rcx, rdi',
   string.format('call 0x%08x',focus_rva)}
 elseif rva==solver_rva then
  extra={'mov [rsi+r8*4+0x92718], r15d','cmp r15d, [rsi+r8*4+0x92718]'}
 end
 for _,op in ipairs(extra or {})do out[#out+1]={rva=rva+100+#out,op=op}end
 return out
end
put(grid+0x91f0c,b(3,4));put(grid+0x92718,b(0,4)..b(1,4)..b(2,4))
put(grid+0x928e4,b(0,4));put(grid+0x92990+2*4,b(701,4)) -- Duplicate of first offer.
local function row_address(slot)return grid+0xb00+slot*0xaed0 end
for slot=0,2 do
 local at=row_address(slot);put(at+0xaeb4,b(3,4));put(at+0xaec0,b(slot==0 and 0 or 0xffffffff,4))
 for column=0,2 do put(at+0x110+column*0x2b68+0x2b5a,string.char(slot==0 and column==0 and 2 or 0))end
end
local focus_calls,writes={},0
local behavior,write_failure='ok',nil
local before_executable=backend.executable
backend.executable=function(at)return at==base+focus_rva or before_executable(at)end
backend.focus_row=function(at,row,column)
 assert(at==base+focus_rva and (row==row_address(0)or row==row_address(1)or row==row_address(2)))
 focus_calls[#focus_calls+1]={row=row,column=column}
 put(row+0xaec0,b(column,4))
 for i=0,2 do
  local bit=i==column and 2 or 0
  if behavior=='wrong_bits'and column~=0xffffffff then bit=0 end
  put(row+0x110+i*0x2b68+0x2b5a,string.char(bit))
 end
 if behavior=='profile_change'then put(owner+0x38,b(123,4))end
 if behavior=='scroll_change'then put(grid+0x92960,f(123))end
 return true
end
backend.write_armor=function(at,value)
 local allowed={[grid+0x928e4]=true,[grid+0x928e8]=true,[grid+0x928ec]=true,
  [grid+0x928f0]=true,[grid+0x92988]=true}
 assert(allowed[at],'focus wrote outside its five UI selection mirrors')
 writes=writes+1;if write_failure==writes then return false end
 put(at,b(value,4));return true
end
'''


def run(code, shifted=False):
    fixture=FOCUS.replace('focus_rva=0x25000','focus_rva=0x26000') if shifted else FOCUS
    run_lua(SELECTION+HIGHLIGHT+LOGICAL_PROOF+BUILDERS+fixture+code)


@pytest.mark.parametrize('shifted',[False,True])
def test_dynamic_row_helper_selects_exact_duplicate_column_and_preserves_view(shifted):
    run(r'''
put(grid+0x92960,f(23));put(grid+0x110+0x7b8,f(.25))
local profile,marker,scrollbar=read(owner+0x38,100),read(grid+0x9298c,4),read(grid+0x110+0x7b8,4)
local g=resolved();local result,why=g:focus_index(2,'armor:00001234',catalog)
assert(result and result.status=='native_exact_focus_readback_verified',why)
assert(result.logical_index==2 and result.row==0 and result.column==2 and result.offer_id==701)
assert(n32(grid+0x928e8)==0 and n32(grid+0x928ec)==2 and n32(grid+0x92988)==701)
assert(#focus_calls==2 and focus_calls[1].column==0xffffffff and focus_calls[2].column==2)
assert(writes==5 and consumed==1 and invoked.highlight==0 and invoked.clear==0 and invoked.finish==0)
assert(read(owner+0x38,100)==profile and read(grid+0x9298c,4)==marker and read(grid+0x110+0x7b8,4)==scrollbar)
assert(read(grid+0x92960,4)==f(23)and moves==0 and stops==0 and not result.equipped)
''',shifted)


def test_exact_focus_updates_group_and_clears_the_previous_visible_row():
    run(r'''
local g=resolved();local result,why=g:focus_index(6,'armor:00001234',catalog)
assert(result and result.row==2 and result.column==0,why)
assert(n32(grid+0x928e4)==2 and n32(grid+0x928e8)==2 and n32(grid+0x928ec)==0 and n32(grid+0x928f0)==1)
assert(n32(row_address(0)+0xaec0)==0xffffffff and n32(row_address(2)+0xaec0)==0)
assert(invoked.highlight==0 and invoked.clear==0 and invoked.finish==0)
''')


def test_missing_semantic_proof_or_changed_live_code_has_zero_mutation_fallback():
    run(r'''
focus_ops[4]='mov [rcx+0xaec4], edx'
local g=resolved();local result,why=g:focus_index(2,'armor:00001234',catalog)
assert(not result and why:find('capability unavailable',1,true))
assert(#focus_calls==0 and writes==0 and invoked.highlight==0 and consumed==0)
assert(g:consume_select()) -- Other native grid capabilities remain usable.
''')
    run(r'''
local g=resolved();put(base+focus_rva+64,'X')
assert(not g:focus_index(2,'armor:00001234',catalog))
assert(#focus_calls==0 and writes==0 and consumed==0 and invoked.highlight==0)
''')


def test_offscreen_or_wrong_owned_identity_fails_before_any_focus_or_mirror_write():
    run(r'''
local g=resolved()
assert(not g:focus_index(9,'armor:00005678',catalog))
assert(not g:focus_index(2,'armor:00005678',catalog))
catalog.owned['armor:00001234']=false
assert(not g:focus_index(2,'armor:00001234',catalog))
assert(#focus_calls==0 and writes==0 and consumed==0 and invoked.highlight==0)
''')


def test_partial_mirror_failure_and_incorrect_native_focus_bits_never_claim_success():
    run(r'''
write_failure=3;local g=resolved();local result,why=g:focus_index(2,'armor:00001234',catalog)
assert(not result and why:find('mirror write rejected',1,true))
assert(#focus_calls==1 and writes==3 and invoked.highlight==0)
''')
    run(r'''
behavior='wrong_bits';local g=resolved();local result,why=g:focus_index(2,'armor:00001234',catalog)
assert(not result and why:find('focus bit readback differs',1,true))
assert(#focus_calls==2 and writes==5 and invoked.highlight==0)
''')


@pytest.mark.parametrize('behavior',['profile_change','scroll_change'])
def test_unexpected_native_profile_or_scroll_change_invalidates_result(behavior):
    run(f'''
behavior='{behavior}';local g=resolved();local result,why=g:focus_index(2,'armor:00001234',catalog)
assert(not result and why:find('changed scroll, marker, profile, or owner',1,true))
assert(invoked.highlight==0 and invoked.clear==0 and invoked.finish==0)
''')
