"""Native stats/perks borrow only a scoped enum; browsing never changes visual data."""
import pytest

from test_native_grid import HIGHLIGHT, SELECTION, run_lua
from test_native_preview import PREVIEW
from test_native_variant_details import DETAILS


WIDGETS = r'''
local stats_rva,passive_rva=0x24000,0x25000
local function ops(list,rva)
 local rows={};for i,op in ipairs(list)do rows[i]={rva=rva+i,op=op}end;return rows
end
local stats_ops={'mov [rcx+0x6308], esi','mov r12, r9','mov edi, r8d',
 'mov [rcx+0x6300], edx','mov [rcx+0x6304], r8d','mov r13, rcx',
 'mov ecx, [r15+0x1ce0]','lea rbp, [r15+0xb9ce4]','cmp [rbp+0x4], ebx',
 'lea r14, [r15+0xb9ce4]','cmp [r14+0x4], edi','cmp eax, +0x03',
 'mov ecx, [r14+0x8]','mov ecx, [rbp+0x8]','mov r8, rax','mov rdx, rax',
 'mov al, 0x1','xor al, al','ret'}
local passive_ops={'cmp [rcx+0x27e8], edx','mov [rcx+0x27e8], edx',
 'mov r8d, [r9+0xd1cf0]','mov r10d, [r9+0xd1cf4]','mov ecx, [r9+rax*4+0xd1d48]',
 'lea rcx, [r9+0xb9ce4]','cmp [rcx+rax*8+0x4], edx','mov esi, [rcx+0x1c]',
 'mov ecx, [r11+rax*4+0x30]','mov rax, [r11+0x20]','mov rsi, [rax+rcx*8]',
 'mov edx, [rsi+0x4]','lea rcx, [rbx+0x13d8]','mov rdx, [rsi+0x8]',
 'lea rcx, [rbx+0x1280]','mov rdi, [rsi+0x10]','mov eax, [rsi+0x18]',
 'lea rdi, [rbx+0x17a8]','mov r8d, 0x1000','mov [rbx+0x1748], eax','ret'}
for _,op in ipairs({'lea rcx, [rbp+0xdff8]','xor r9d, r9d','mov r8d, ebx','mov edx, ebx',
 string.format('call 0x%08x',stats_rva),'lea rcx, [rbp+0x21460]','mov edx, ebx',
 string.format('call 0x%08x',passive_rva)})do detail_ops[#detail_ops+1]=op end
local old_decode=DebugArmory.decode
DebugArmory.decode=function(raw,rva)
 if rva==stats_rva then return ops(stats_ops,rva)end
 if rva==passive_rva then return ops(passive_ops,rva)end
 return old_decode(raw,rva)
end
local executable=backend.executable
backend.executable=function(at)return at==base+stats_rva or at==base+passive_rva or executable(at)end
for _,r in ipairs(memory)do if r.at==progression then r.raw=r.raw..string.rep('\0',0x20000)end end
put(progression+0xd1cf0,b(0,4)..b(2,4));put(progression+0xd1d48,b(0,4)..b(1,4))
local look_id,stats_id='armor:00001234','armor:00005678'
local look_at,stats_at=0xa00000,0xa00100
region(look_at,0x200)
local function header(id,passive)
 return b(id,4)..string.rep('\0',24)..b(passive,4)..string.rep('P',8)..b(0,4)..string.rep('\0',20)
end
local look_raw,stats_raw=header(0x1234,4),header(0x5678,6)
put(look_at,look_raw);put(stats_at,stats_raw)
catalog.records[look_id].address=look_at;catalog.records[look_id].bytes=look_raw
catalog.records[stats_id].address=stats_at;catalog.records[stats_id].bytes=stats_raw
catalog.catalog={[look_id]={passive_variant_id='perk:look'},[stats_id]={passive_variant_id='perk:stats'}}
catalog.context={passive_variants={['perk:look']={enum=4},['perk:stats']={enum=6}}}
local session_current=true
catalog.verify_session=function()return session_current end
catalog.verify_owned=function(ids)for _,id in ipairs(ids)do if not catalog.owned[id]then return false end end;return true end
local detail_widget=manager+0x99d70
local stat_widget,passive_widget=detail_widget+0xdff8,detail_widget+0x21460
local stat_calls,passive_calls,writes={}, {}, {}
local displayed_stat_passive,displayed_passive
local fault
local raw_preview=backend.preview_details
backend.preview_details=function(at,widget,offer,equipped)
 local result=raw_preview(at,widget,offer,equipped)
 put(passive_widget+0x27e8,b(offer,4))
 displayed_passive=offer==77 and n32(look_at+28)or n32(stats_at+28)
 return result
end
backend.write_armor=function(at,value)
 assert(at==stats_at+28,'preview wrote outside the selected stats passive enum')
 writes[#writes+1]={at=at,value=value};put(at,b(value,4))
 return not(fault=='write_failed'and #writes==1)
end
backend.detail_stats=function(at,widget,offer)
 assert(at==base+stats_rva and widget==stat_widget)
 stat_calls[#stat_calls+1]=offer
 displayed_stat_passive=offer==88 and n32(stats_at+28)or n32(look_at+28)
 assert(read(stats_at,28)==stats_raw:sub(1,28)and read(stats_at+32,32)==stats_raw:sub(33),'visual/package data changed')
 if fault=='stats_throw'then error('fixture stat failure')end
 if fault=='stats_reject'then return false end
 if fault=='ownership_lost'then catalog.owned[look_id]=false end
 if fault=='menu_change'then put(menu+0x4294,b(0,4))end
 if fault=='code_change'then put(base+passive_rva+100,'X')end
 if fault=='foreign_passive'then put(stats_at+28,b(99,4))end
 put(widget+0x6300,b(offer,4)..b(offer,4));return true
end
backend.detail_passive=function(at,widget,offer)
 assert(at==base+passive_rva and widget==passive_widget)
 passive_calls[#passive_calls+1]=offer
 if fault=='passive_throw'then error('fixture passive failure')end
 if fault=='passive_reject'then return false end
 if n32(widget+0x27e8)~=offer then
  displayed_passive=offer==88 and n32(stats_at+28)or n32(look_at+28)
  if fault~='passive_readback'then put(widget+0x27e8,b(offer,4))end
 end
 return true
end
local function variant(g,appearance,perk,options)
 return g:preview_variant_details(appearance or look_id,'native-stats:00005678',perk or 'perk:look',catalog,options)
end
'''


def run(code, shift=False):
    fixtures = SELECTION + HIGHLIGHT + PREVIEW + DETAILS + WIDGETS
    if shift:
        fixtures = fixtures.replace('0x24000,0x25000', '0x2c000,0x2d000')
    run_lua(fixtures + code)


@pytest.mark.parametrize('shift', [False, True])
def test_model_stays_original_while_native_widgets_read_scoped_passive(shift):
    run(r'''
local g=resolved();local result,why=variant(g)
assert(result and result.native_detail_view and result.temporary_passive_restored,why)
assert(result.appearance_data_unchanged and not result.equipped and not result.rendering_verified)
assert(result.kit_id==look_id and result.stats_kit_id==stats_id and result.passive_variant_id=='perk:look')
assert(displayed_stat_passive==4 and displayed_passive==4)
assert(#writes==2 and writes[1].value==4 and writes[2].value==6)
assert(read(stats_at,64)==stats_raw and read(look_at,64)==look_raw)
assert(#stat_calls==1 and stat_calls[1]==88 and #passive_calls==1 and passive_calls[1]==88)
assert(#detail_calls==1 and detail_calls[1].offer==77 and not detail_calls[1].equipped)
assert(n32(owner+0x13a888)==0x1234 and read(owner+0x38,88)==profiles)
''', shift)


def test_same_offer_perk_refresh_rebinds_only_passive_widget_to_real_owned_alternate():
    run(r'''
local g=resolved();local result,why=variant(g,stats_id)
assert(result,why)
assert(#detail_calls==1 and detail_calls[1].offer==88)
assert(#passive_calls==2 and passive_calls[1]==77 and passive_calls[2]==88)
assert(displayed_passive==4 and n32(owner+0x13a888)==0x5678)
assert(read(stats_at,64)==stats_raw and #writes==2)
''')


def test_repeated_selections_restore_enum_each_time_and_never_rewrite_visuals():
    run(r'''
local g=resolved()
for i=1,120 do
 local perk=i%2==1 and 'perk:look'or 'perk:stats'
 local result,why=variant(g,nil,perk);assert(result,why)
 assert(displayed_passive==(i%2==1 and 4 or 6))
 assert(displayed_stat_passive==displayed_passive)
 assert(read(stats_at,64)==stats_raw and read(look_at,64)==look_raw)
end
assert(#writes==120 and #detail_calls==120 and #stat_calls==120)
''')


@pytest.mark.parametrize('failure', [
    'write_failed', 'stats_throw', 'stats_reject', 'passive_throw',
    'passive_reject', 'passive_readback', 'ownership_lost', 'menu_change', 'code_change',
])
def test_failure_restores_original_enum_before_returning(failure):
    run(f'''
local g=resolved();fault='{failure}'
local result,why=variant(g)
assert(not result,tostring(why))
assert(read(stats_at,64)==stats_raw and read(look_at,64)==look_raw)
assert(#writes==2 and writes[2].value==6)
''')


def test_independent_passive_change_is_preserved_and_reports_recovery():
    run(r'''
local g=resolved();fault='foreign_passive'
local result,why=variant(g)
assert(not result and why:find('recovery required',1,true),tostring(why))
assert(n32(stats_at+28)==99 and #writes==1)
''')


def test_changed_appearance_or_unverified_active_stat_carrier_is_rejected_before_preview():
    run(r'''
local g=resolved();put(look_at+32,'X')
local result,why=variant(g);assert(not result and why:find('currently used',1,true))
put(look_at,look_raw);put(stats_at+32,'X')
result,why=variant(g);assert(not result and why:find('base profile',1,true))
assert(#writes==0 and #detail_calls==0 and highlighted==0)
''')


def test_stats_carrier_override_requires_fresh_host_composition_verification():
    run(r'''
local g=resolved();put(stats_at+12,'X');local active=read(stats_at,64)
stats_raw=active -- fake widget guard expects this retained verified composition
local checks=0
local result,why=variant(g,nil,nil,{verify_composition=function(id,raw)
 checks=checks+1;return id==stats_id and raw==active
end})
assert(result and checks==1,why)
assert(read(stats_at,64)==active and displayed_passive==4)
''')


def test_missing_widget_edge_or_changed_semantics_never_enters_native_preview():
    run(r'''
stats_ops[2]='mov r12d, r9d'
local g=resolved();local result,why=variant(g)
assert(not result and why:find('widget proof unavailable',1,true))
assert(#writes==0 and #detail_calls==0 and highlighted==0)
''')
    run(r'''
passive_ops[7]='mov esi, [rcx+0x20]'
local g=resolved();assert(not variant(g))
assert(#writes==0 and #detail_calls==0 and highlighted==0)
''')


def test_passive_binder_offer_filter_is_respected_before_any_enum_write():
    run(r'''
local g=resolved();put(progression+0xd1cf4,b(1,4))
local result,why=variant(g)
assert(not result and why:find('no enabled owned offer',1,true))
assert(#writes==0 and #stat_calls==0 and #passive_calls==0)
''')


def test_exact_custom_focus_precedes_preview_and_bypasses_offer_highlight():
    run(r'''
local g=resolved();local focused=0
g.focus_index=function(_,index,id,observed)
 assert(index==4 and id==look_id and observed==catalog)
 assert(#detail_calls==0 and #writes==0,'model changed before exact focus')
 focused=focused+1;return {status='fixture_exact_focus'}
end
local result,why=variant(g,nil,nil,{focus_index=4});assert(result,why)
assert(focused==1 and highlighted==0 and #detail_calls==1)
''')


def test_offscreen_exact_focus_stops_before_model_or_stat_calls():
    run(r'''
local g=resolved()
g.focus_index=function()return nil,'requested card is outside the native visible rows'end
local result,why=variant(g,nil,nil,{focus_index=31})
assert(not result and why:find('outside the native visible rows',1,true))
assert(highlighted==0 and #detail_calls==0 and #writes==0 and #stat_calls==0)
''')


def test_verified_applied_self_appearance_can_preview_its_retained_header():
    run(r'''
local g=resolved()
local profile={base_values_verified=true,base_values={armor_rating=100,speed=500,stamina_regen=100}}
catalog.context.stats_profiles={['native-stats:00001234']=profile,['native-stats:00005678']=profile}
-- Applied source==carrier has original visual/package/localization fields,
-- a private body descriptor and the chosen passive.
put(stats_at+28,b(4,4));put(stats_at+48,b(0xdead0000,8))
local active=read(stats_at,64);stats_raw=active
local appearance_checks,composition_checks=0,0
local result,why=variant(g,stats_id,'perk:look',{
 verify_appearance=function(id,raw)
  appearance_checks=appearance_checks+1;return id==stats_id and raw==active
 end,
 verify_composition=function(id,raw)
  composition_checks=composition_checks+1;return id==stats_id and raw==active
 end})
assert(result,why)
assert(appearance_checks>=2 and composition_checks==1)
assert(read(stats_at,64)==active and #writes==0)
assert(displayed_stat_passive==4 and displayed_passive==4 and #detail_calls==1)
assert(stat_calls[1]==77 and result.stats_kit_id==look_id,'modified appearance was reused as original base stats')
''')


def test_generic_active_stats_verification_does_not_authorize_a_changed_appearance():
    run(r'''
local g=resolved();put(stats_at+48,b(0xdead0000,8))
local result,why=variant(g,stats_id,nil,{verify_composition=function()return true end})
assert(not result and why:find('currently used',1,true))
assert(#detail_calls==0 and #writes==0 and highlighted==0)
''')


def test_active_different_look_cannot_use_the_original_appearance_exception():
    run(r'''
local g=resolved();put(stats_at+32,'X');put(stats_at+48,b(0xdead0000,8))
local result,why=variant(g,stats_id,nil,{
 verify_appearance=function()return true end,verify_composition=function()return true end})
assert(not result and why:find('currently used',1,true))
assert(#detail_calls==0 and #writes==0 and highlighted==0)
''')


def test_self_appearance_proof_must_remain_current_before_native_preview():
    run(r'''
local g=resolved();put(stats_at+48,b(0xdead0000,8));local checks=0
local profile={base_values_verified=true,base_values={armor_rating=100,speed=500,stamina_regen=100}}
catalog.context.stats_profiles={['native-stats:00001234']=profile,['native-stats:00005678']=profile}
local result,why=variant(g,stats_id,nil,{
 verify_appearance=function()checks=checks+1;return checks==1 end,
 verify_composition=function()return true end})
assert(not result and why:find('appearance changed before native model',1,true))
assert(#detail_calls==0 and #writes==0)
''')


def test_modified_base_stat_donor_without_pristine_equivalent_blocks_before_model_preview():
    run(r'''
local g=resolved();put(stats_at+48,b(0xdead0000,8))
local result,why=variant(g,nil,nil,{verify_composition=function()return true end})
assert(not result and why:find('unchanged owned equivalent',1,true),tostring(why))
assert(#detail_calls==0 and #writes==0 and #stat_calls==0)
''')


def test_post_apply_widget_refresh_never_calls_model_preview_or_moves_selection():
    run(r'''
local g=resolved();local result,why=variant(g,nil,nil,{widgets_only=true})
assert(result,why)
assert(#detail_calls==0 and highlighted==0 and #stat_calls==1)
assert(displayed_stat_passive==4 and displayed_passive==4)
assert(result.stats_offer_id==88 and result.passive_offer_id==88)
assert(read(stats_at,64)==stats_raw)
''')
    run(r'''
local g=resolved();local result,why=variant(g,stats_id,nil,{widgets_only=true})
assert(not result and why:find('Selected model changed',1,true),tostring(why))
assert(#detail_calls==0 and highlighted==0 and #stat_calls==0 and #writes==0)
''')


def test_original_same_offer_rebinds_original_perk_after_custom_variant_preview():
    run(r'''
local g=resolved();assert(variant(g,stats_id,'perk:look'))
assert(displayed_passive==4 and read(stats_at,64)==stats_raw)
local focus_count=0
function g:focus_index(index,id)
 assert(index==17 and id==stats_id);focus_count=focus_count+1
 return {offer_id=88}
end
function g:select_kit()error('original selection cannot resolve duplicate IDs')end
local original,why=variant(g,stats_id,'perk:stats',{focus_index=17,requires_apply=false})
assert(original,why)
assert(focus_count==1 and displayed_passive==6 and displayed_stat_passive==6)
assert(read(stats_at,64)==stats_raw and read(owner+0x38,88)==profiles)
''')
