"""Saved variants use the real detail view without disturbing custom grid focus."""
import pytest

from test_native_grid import HIGHLIGHT, SELECTION, run_lua
from test_native_preview import PREVIEW


DETAILS = r'''
detail_ops[#detail_ops+1]='lea rsi, [rbp+0x49f0]'
detail_ops[#detail_ops+1]='lea edx, [r12+0x5]'
detail_ops[#detail_ops+1]='mov rcx, rsi'
local detail_calls={}
local previous_executable=backend.executable
backend.executable=function(at)return at==base+detail_rva or previous_executable(at)end
backend.preview_details=function(at,object,offer,equipped)
 assert(at==base+detail_rva and object==manager+0x99d70)
 detail_calls[#detail_calls+1]={offer=offer,equipped=equipped}
 local kit=offer==88 and 0x5678 or 0x1234
 put(owner+0x1d7494,b(behavior=='wrong_offer'and 999 or offer,4))
 put(owner+0x13a888,b(behavior=='wrong_kit'and 0x9999 or kit,4))
 if behavior=='profile_change'then put(owner+0x64+12,b(0x9999,4))end
 if behavior=='mirror_change'then put(owner+0x90,b(0x9999,4))end
 if behavior=='menu_change'then put(menu+0x4294,b(0,4))end
 if behavior=='code_change'then put(base+setter_rva+100,'X')end
 if behavior=='selection_change'then put(grid+0x928ec,b(2,4))end
 if behavior=='scroll_change'then put(grid+0x92960,f(100))end
 return behavior~='rejected'
end
put(manager+0x9305c,b(88,4))
put(grid+0x92988,b(77,4))
put(grid+0x928e8,b(0,4)..b(1,4))
'''


def run(code, shift=False):
    preview = PREVIEW
    if shift:
        preview = preview.replace('0x20000,0x22000,0x23000', '0x28000,0x2a000,0x2b000')
    run_lua(SELECTION + HIGHLIGHT + preview + DETAILS + code)


@pytest.mark.parametrize('shift', [False, True])
def test_carrier_details_preserve_duplicate_look_focus_and_native_scroll(shift):
    run(r'''
-- Both visible cards can show the same look; the composed carrier need not
-- appear in the current list at all. Offer ownership comes from progression.
put(grid+0x92990,b(77,4)..b(77,4))
local g=resolved();local result,why=g:preview_details('armor:00005678',catalog,{requires_apply=true})
assert(result and result.native_detail_view and result.selection_preserved,why)
assert(result.kit_id=='armor:00005678'and result.native_apply_pending and not result.equipped)
assert(not result.rendering_verified and #detail_calls==1 and detail_calls[1].offer==88)
assert(detail_calls[1].equipped==false and calls==0 and highlighted==0)
assert(n32(grid+0x92988)==77 and n32(grid+0x928ec)==1)
assert(read(owner+0x38,88)==profiles and read(owner+0x90,12)==mirrors)
assert(consumed==0 and moves==0 and stops==0)
local state=assert(g:detail_state())
assert(state.kit_id=='armor:00005678'and state.offer_id==88 and state.equipped_offer_id==88)
''', shift)


def test_native_equipped_hint_follows_marker_unless_variant_still_needs_apply():
    run(r'''
local g=resolved()
assert(g:preview_details('armor:00005678',catalog))
assert(detail_calls[1].equipped==true)
assert(g:preview_details('armor:00001234',catalog))
assert(detail_calls[2].equipped==false)
assert(g:preview_details('armor:00005678',catalog,{requires_apply=true}))
assert(detail_calls[3].equipped==false)
assert(g:preview_details('armor:00005678',catalog,{requires_apply=false}))
assert(detail_calls[4].equipped==true)
''')


def test_apply_visual_override_requires_its_own_code_proof():
    run(r'''
detail_ops[#detail_ops-1]='lea edx, [r12+0x6]'
local g=resolved()
local result,why=g:preview_details('armor:00005678',catalog,{requires_apply=true})
assert(not result and why:find('Apply presentation proof')and #detail_calls==0)
assert(g:preview_details('armor:00005678',catalog)and #detail_calls==1)
''')


@pytest.mark.parametrize('failure,reason', [
    ('wrong_offer', 'detail offer readback'),
    ('wrong_kit', 'large preview kit readback'),
    ('profile_change', 'changed a profile'),
    ('mirror_change', 'selection mirror'),
    ('selection_change', 'grid focus or scroll'),
    ('scroll_change', 'grid focus or scroll'),
    ('rejected', 'detail call rejected'),
])
def test_failed_native_readback_does_not_publish_detail_success(failure, reason):
    run(f'''
local g=resolved();behavior='{failure}'
local result,why=g:preview_details('armor:00005678',catalog)
assert(not result and why:find('{reason}',1,true),tostring(why))
assert(#detail_calls==1 and highlighted==0)
''')


@pytest.mark.parametrize('failure', ['menu_change', 'code_change'])
def test_native_detail_call_cannot_claim_success_after_menu_or_proof_changes(failure):
    run(f'''
local g=resolved();behavior='{failure}'
assert(not g:preview_details('armor:00005678',catalog))
assert(#detail_calls==1 and not g:detail_state())
''')


def test_unowned_locked_ambiguous_or_changed_offers_never_enter_native_details():
    run(r'''
local g=resolved()
catalog.owned['armor:00005678']=false
assert(not g:preview_details('armor:00005678',catalog))
catalog.owned['armor:00005678']=true
put(progression+0x1ce4+184+0x14,b(1,4))
assert(not g:preview_details('armor:00005678',catalog))
put(progression+0x1ce4+184+0x14,b(4,4))
put(progression+0x1ce4+184+0xb4,'\1')
assert(not g:preview_details('armor:00005678',catalog))
put(progression+0x1ce4+184+0xb4,'\0')
put(progression+0xb9ce4+24+4,b(77,4))
assert(not g:preview_details('armor:00005678',catalog))
put(progression+0xb9ce4+24+4,b(88,4))
local checks=0;catalog.verify_owned=function()checks=checks+1;return checks==1 end
assert(not g:preview_details('armor:00005678',catalog))
assert(#detail_calls==0 and highlighted==0)
''')


def test_hidden_wrong_mode_or_changed_code_blocks_detail_calls_and_observation():
    run(r'''
local g=resolved()
put(grid+272+84,f(0));assert(not g:detail_state())
assert(not g:preview_details('armor:00005678',catalog))
put(grid+272+84,f(1));put(manager+0x178c8e,'\1')
assert(not g:detail_state()and not g:preview_details('armor:00005678',catalog))
put(manager+0x178c8e,'\0');put(grid+602052,b(3,4))
assert(not g:detail_state()and not g:preview_details('armor:00005678',catalog))
put(grid+602052,b(4,4));put(base+detail_rva+200,'X')
assert(not g:detail_state()and not g:preview_details('armor:00005678',catalog))
assert(#detail_calls==0 and highlighted==0)
''')
