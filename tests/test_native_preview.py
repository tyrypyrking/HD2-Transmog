"""Actual NativeGrid preview orchestration against fake current-image evidence."""
import pytest

from test_native_grid import run_lua, SELECTION, HIGHLIGHT

PREVIEW=r'''
local preview_rva,detail_rva,setter_rva=0x20000,0x22000,0x23000
put(base+preview_rva,unhex('40574883ec2083b9888c170001488bf9'))
local wrapper_rows={
 {rva=preview_rva+6,op='cmp dword [rcx+0x178c88], +0x01'},
 {rva=preview_rva+13,op='mov rdi, rcx'},
 {rva=preview_rva+16,op=string.format('jnz 0x%08x',preview_rva+0x73)},
 {rva=preview_rva+0x73,op='cmp byte [rcx+0x178c8e], 0x0'},
 {rva=preview_rva+0x7c,op='mov r9d, [rcx+0x92fbc]'},
 {rva=preview_rva+0x88,op='mov r8d, [rcx+0x92fb8]'},
 {rva=preview_rva+0x8f,op='add rcx, 0x6d0'},
 {rva=preview_rva+0x9b,op='mov edx, [rsp+0x30]'},
 {rva=preview_rva+0x9f,op='lea rcx, [rdi+0x99d70]'},
 {rva=preview_rva+0xa6,op='cmp [rdi+0x9305c], edx'},
 {rva=preview_rva+0xac,op='setz r8b'},
 {rva=preview_rva+0xb0,op='add rsp, +0x20'},
 {rva=preview_rva+0xb4,op='pop rdi'},
 {rva=preview_rva+0xb5,op=string.format('jmp 0x%08x',detail_rva)}}
local detail_ops={'mov edi, [rcx+0xbe00c]','mov ebx, edx','mov [rcx+0xbe00c], ebx',
 'movzx r12d, r8b','mov ecx, [rdx+0x1ce0]','lea r15, [rdx+0xb9ce4]',
 'cmp [r15+0x4], ebx','lea rcx, [rbp+0x20640]',string.format('call 0x%08x',setter_rva)}
local setter_ops={'cmp [rcx+0xdc0], edx','mov [rbx+0xdc0], edx','mov r8d, 0x2',
 'cmp byte [rbx+0xdb0], 0x0','cmp byte [rbx+0xdb1], 0x0'}
local original_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==preview_rva then return wrapper_rows end
 local ops=rva==detail_rva and detail_ops or(rva==setter_rva and setter_ops)
 if ops then local rows={};for i,op in ipairs(ops)do rows[i]={rva=rva+i,op=op}end;return rows end
 return original_decode(raw,rva)
end
local manager=grid-0x6d0
put(manager+0x178c88,b(0,4));put(manager+0x178c8e,'\0');put(grid+0x92fc4,b(4,4))
local profiles=string.rep('PROFILE!',11);put(owner+0x38,profiles)
local mirrors=b(0x1234,4)..b(0x2345,4)..b(0x3456,4);put(owner+0x90,mirrors)
put(owner+0x1d7494,b(77,4));put(owner+0x13a888,b(0x1234,4))
local function n32(at)local a,b,c,d=read(at,4):byte(1,4);return a+b*256+c*65536+d*16777216 end
local calls=0;local behavior='ok'
local executable=backend.executable
backend.executable=function(at)return at==base+preview_rva or executable(at)end
backend.preview_notify=function(at,object)
 assert(at==base+preview_rva and object==manager,'preview wrapper was not derived from current code/UI')
 calls=calls+1
 local offer=n32(grid+0x92988);local kit=offer==88 and 0x5678 or 0x1234
 put(owner+0x1d7494,b(behavior=='wrong_offer'and 999 or offer,4))
 put(owner+0x13a888,b(behavior=='wrong_kit'and 0x9999 or kit,4))
 if behavior=='profile_change'then put(owner+0x64+12,b(0x9999,4))end
 if behavior=='mirror_change'then put(owner+0x90,b(0x9999,4))end
 if behavior=='menu_change'then put(menu+0x4294,b(0,4))end
 if behavior=='code_change'then put(base+setter_rva+100,'X')end
 return true
end
local function resolved()
 local g=G.new(bridge,nil,backend);assert(ready(g)=='ready',g.failure);return g
end
'''


def run(code, shift=False):
    preview=PREVIEW
    if shift:
        preview=preview.replace('0x20000,0x22000,0x23000','0x28000,0x2a000,0x2b000')
    run_lua(SELECTION+HIGHLIGHT+preview+code)


@pytest.mark.parametrize('shift',[False,True])
def test_dynamic_owned_preview_reads_back_detail_and_kit_without_profile_or_equip_write(shift):
    run('''
local g=resolved();local result,why=g:preview_kit('armor:00005678',catalog)
assert(result and result.status=='native_preview_readback_verified',why)
assert(result.kit_id=='armor:00005678' and result.offer_id==88 and not result.equipped and not result.rendering_verified)
assert(calls==1 and highlighted==1 and n32(owner+0x1d7494)==88 and n32(owner+0x13a888)==0x5678)
assert(read(owner+0x38,88)==profiles and read(owner+0x90,12)==mirrors)
assert(consumed==0 and moves==0 and stops==0)
''', shift)


def test_missing_wrapper_or_changed_semantic_relation_never_invokes_notify():
    run('''
put(base+preview_rva,'X');local g=resolved()
local result,why=g:preview_kit('armor:00005678',catalog)
assert(not result and why:find('preview unavailable') and calls==0 and highlighted==0)
assert(g:consume_select())
''')
    run('''
wrapper_rows[3].op=string.format('jnz 0x%08x',preview_rva+0x74)
local g=resolved();assert(not g:preview_kit('armor:00005678',catalog))
assert(calls==0 and highlighted==0)
''')
    run('''
setter_ops[2]='mov [rbx+0xdc4], edx'
local g=resolved();assert(not g:preview_kit('armor:00005678',catalog))
assert(calls==0 and highlighted==0)
''')


def test_mode_blocker_wrong_category_and_absent_owned_look_reject_notify():
    run('''
local g=resolved();put(manager+0x178c88,b(1,4))
assert(not g:preview_kit('armor:00005678',catalog) and calls==0)
put(manager+0x178c88,b(0,4));put(manager+0x178c8e,'\1')
assert(not g:preview_kit('armor:00005678',catalog) and calls==0)
put(manager+0x178c8e,'\0');catalog.records['armor:00005678'].category=1
assert(not g:preview_kit('armor:00005678',catalog) and calls==0)
catalog.records['armor:00005678'].category=0;catalog.owned['armor:00005678']=false
assert(not g:preview_kit('armor:00005678',catalog) and calls==0)
assert(read(owner+0x38,88)==profiles)
''')


def test_ownership_change_after_highlight_stops_before_detail_preview():
    run('''
local g=resolved();local owner_fresh=true;local highlight=backend.highlight
backend.highlight=function(...)local done=highlight(...);owner_fresh=false;return done end
catalog.verify_owned=function()return owner_fresh end
local result,why=g:preview_kit('armor:00005678',catalog)
assert(not result and why:find('preview context changed') and highlighted==1 and calls==0)
assert(n32(owner+0x1d7494)==77 and n32(owner+0x13a888)==0x1234)
''')


@pytest.mark.parametrize('failure,reason',[('wrong_offer','detail offer readback'),('wrong_kit','large preview kit readback'),('profile_change','changed a profile'),('mirror_change','selection mirror')])
def test_wrong_native_readback_or_profile_side_effect_never_reports_success(failure,reason):
    run(f'''
local g=resolved();behavior='{failure}'
local result,why=g:preview_kit('armor:00005678',catalog)
assert(not result and why:find('{reason}',1,true),tostring(why))
assert(calls==1)
''')


def test_changed_current_image_proof_prevents_native_preview_call():
    run('''
local g=resolved();put(base+detail_rva+200,'X')
assert(not g:preview_kit('armor:00005678',catalog) and calls==0 and highlighted==0)
''')


@pytest.mark.parametrize('failure',['menu_change','code_change'])
def test_menu_or_proof_change_during_notify_invalidates_success_from_old_memory(failure):
    run(f'''
local g=resolved();behavior='{failure}'
local result,why=g:preview_kit('armor:00005678',catalog)
assert(not result and calls==1,'retired menu/code was reported as successful: '..tostring(why))
''')


def test_exact_original_card_preview_does_not_call_ambiguous_offer_selection():
    run('''
local g=resolved();local focus=0
function g:select_kit()error('ambiguous ID lookup must not be used')end
function g:focus_index(index,id,actual_catalog)
 assert(index==17 and id=='armor:00001234'and actual_catalog==catalog)
 focus=focus+1;put(grid+0x92988,b(77,4));return {offer_id=77}
end
local shown,why=g:preview_kit('armor:00001234',catalog,{focus_index=17})
assert(shown and focus==1 and calls==1,why)
''')
