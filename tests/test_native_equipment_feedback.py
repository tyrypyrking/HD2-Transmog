"""Verified equip completion updates native button/sound without re-equipping."""
import pytest
from test_native_grid import SELECTION, HIGHLIGHT, run_lua
from test_native_preview import PREVIEW
from test_native_variant_details import DETAILS

FEEDBACK=r'''
local input_rva,state_rva,sound_rva=0x26000,0x28000,0x29000
put(base+input_rva,unhex('48895c241048896c2418565741564883ec308b8104e00b004d8bf0'))
detail_ops[#detail_ops+1]=string.format('call 0x%08x',state_rva)
local state_ops={'mov edi, edx','mov rbx, rcx','mov [rbx+0x47b8], edx',
 'mov [rcx+0x47b8], edi','cmp byte [rcx+0x47b2], 0x0','mov byte [rcx+0x47b3], 0x0',
 'movss xmm2, [rbx+0x47b4]','mov edx, [rbx+0x47c8]','mov edx, [rbx+0x47c4]'}
local sound_ops={'mov ebx, edx','mov rdx, [rax+0x288]','mov rcx, [rcx+0x10f8]',
 'mov rsi, [rax+0x338]','call rdx','mov ecx, ebx','xor r9d, r9d','jmp rax'}
local prior_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva,budget)
 local ops=rva==state_rva and state_ops or rva==sound_rva and sound_ops
 if rva==input_rva then
  assert(budget>=400,'native confirmation is beyond the old 256-instruction bound')
  ops={'lea rdi, [rbx+0x49f0]','mov byte [rbx+0x91a3], 0x1',
   'mov edx, [rbx+0x91b0]',string.format('call 0x%08x',sound_rva)}
 end
 if ops then local out={};for i,op in ipairs(ops)do out[i]={rva=rva+i,op=op}end;return out end
 return prior_decode(raw,rva,budget)
end
local old_executable=backend.executable
backend.executable=function(at)return at==base+state_rva or at==base+sound_rva or old_executable(at)end
local button=manager+0x99d70+0x49f0
put(button+0x47b8,b(5,4));put(button+0x47c0,b(999999,4));put(button+0x47c8,b(123456,4))
local state_calls,sounds=0,0
local fault
backend.button_state=function(at,object,state)
 assert(at==base+state_rva and object==button and state==6)
 state_calls=state_calls+1
 if read(button+0x47b2,2)=='\0\1'and read(button+0x47b4,4)==f(1)then sounds=sounds+1 end
 if fault~='state'then put(button+0x47b8,b(state,4))end
 if fault=='profile'then put(owner+0x64+12,b(0x9999,4))end
 if fault=='code'then put(base+sound_rva,'X')end
 if fault=='menu'then put(menu+0x4294,b(0,4))end
 return true
end
backend.ui_sound=function(at,event)
 assert(at==base+sound_rva and event==123456);sounds=sounds+1;return true
end
local id='armor:00001234'
local committed_id=id
local function feedback_grid()
 local g=resolved()
 -- Equipment commit is covered independently; this tests presentation against
 -- real detail-context, code proofs and readback with a verified completion.
 g.commit_snapshot=function()return {profile_armor_id=committed_id,controller_armor_id=committed_id,pending_nonarmor=false}end
 g.verify_commit=function()return true end
 return g
end
'''


def run(code):
    run_lua(SELECTION+HIGHLIGHT+PREVIEW+DETAILS+FEEDBACK+code)


def test_completion_uses_native_state_and_own_sound_once_without_preview_or_commit():
    run(r'''
local g=feedback_grid();local result,why=g:equipment_feedback(id,catalog)
assert(result and result.sound_played and n32(button+0x47b8)==6,why)
assert(state_calls==1 and sounds==1 and #detail_calls==0 and calls==0 and highlighted==0)
assert(read(owner+0x38,88)==profiles and read(owner+0x90,12)==mirrors)
assert(g:equipment_feedback(id,catalog)and state_calls==1 and sounds==1)
''')


@pytest.mark.parametrize('fault',['state','profile','code','menu'])
def test_failed_native_readback_never_plays_success_sound(fault):
    run(f"fault='{fault}'\n"+r'''
local g=feedback_grid();assert(not g:equipment_feedback(id,catalog))
assert(state_calls==1 and sounds==0)
''')


@pytest.mark.parametrize('change',[
    "committed_id='armor:00005678'",
    "catalog.owned[id]=false",
    "put(button+0x47c8,b(0,4))",
    "put(owner+0x13a888,b(0x5678,4))",
    "put(base+sound_rva,'X')",
])
def test_changed_armor_ownership_event_or_proof_prevents_all_feedback(change):
    run('local g=feedback_grid()\n'+change+r'''
assert(not g:equipment_feedback(id,catalog))
assert(state_calls==0 and sounds==0)
''')


def test_missing_optional_feedback_does_not_disable_native_preview():
    run(r'''
put(base+input_rva,'X');local g=feedback_grid()
assert(not g:equipment_feedback(id,catalog))
assert(g:preview_details(id,catalog,{requires_apply=true})and #detail_calls==1)
assert(state_calls==0 and sounds==0)
''')


def test_native_setter_completion_sound_is_not_dispatched_twice():
    run(r'''
put(button+0x47b2,'\0\1');put(button+0x47b4,f(1))
local g=feedback_grid();local result,why=g:equipment_feedback(id,catalog)
assert(result and result.sound_played,why)
assert(state_calls==1 and sounds==1)
''')
