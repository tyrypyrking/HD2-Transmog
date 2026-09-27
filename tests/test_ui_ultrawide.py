"""Native card geometry and overlay input stay aligned across aspect ratios."""
import pytest
from test_ui_workflow_apply import APPLY_FIXTURE
from test_wizard_panel import FIXTURE, RENDER_FIXTURE, PREFIX_FIXTURE, run_lua

RESOLUTIONS = [(1920,1080), (2560,1440), (2560,1080), (2400,1000),
               (3440,1440), (3840,1600), (2400,675), (5120,1440)]


def viewport(width, height):
    return f'resolution={{{width},{height}}}\n' + r'''
local Layout=require('src.ui_layout')
local geometry=Layout.resolve(unpack(resolution))
local s,left=geometry.scale,geometry.left
-- Native widgets arrive in viewport coordinates, already centered.
local p=sample.native_prefix
p.clip=geometry.prefix
for _,items in ipairs({p.cells,p.headers})do
 for _,item in ipairs(items)do local r=item.rect
  r.x=left+r.x*s;r.y=r.y*s;r.w=r.w*s;r.h=r.h*s
 end
end
'''


@pytest.mark.parametrize('width,height', RESOLUTIONS)
def test_saved_and_original_mouse_apply_follow_native_ultrawide_canvas(width, height):
    run_lua(APPLY_FIXTURE + viewport(width,height) + r'''
host.should_capture=function(input)
 return selected_custom or apply_state.native_override==true
  or (input and input.down and Layout.contains(geometry.picker,input.x,input.y))
end
local card=sample.native_prefix.cells[1].rect
local x,y=card.x+card.w/2,card.y+card.h/2
assert(frame(0,0,false))
assert(frame(x,y,true));assert(frame(x,y,false))
assert(flow:view().selected_variant.label=='Existing' and native_equips==0)
ready();assert(frame(0,0,false))
local r=geometry.apply;x,y=r.x+r.w/2,r.y+r.h/2
assert(frame(x,y,true));assert(frame(x,y,false))
assert(applied==1 and native_equips==0)
-- Ordinary armor uses the same intercepted Apply surface.
flow:clear_selected_variant();selected_custom=false
apply_state={native_override=true,native_override_id='look-a',native_details=true,
 can_apply=true,apply_pending=false,variant_phase='ready'}
assert(frame(0,0,false));assert(frame(x,y,true));assert(frame(x,y,false))
assert(applied==2 and native_equips==0)
-- The old screen-edge Apply position must not equip on wide displays.
if left>r.w then
 ready();apply_state.native_override=true;apply_state.native_override_id='look-a'
 local oldx=resolution[1]-221*s
 assert(frame(0,0,false));assert(frame(oldx,y,true));assert(frame(oldx,y,false))
 assert(applied==2)
end
''')


@pytest.mark.parametrize('width,height', RESOLUTIONS)
def test_creator_and_partial_cards_share_centered_native_clip(width,height):
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + viewport(width,height) + r'''
assert(draw())
local plus=sample.native_prefix.cells[2].rect
local hit=panel:hit(plus.x+plus.w/2,plus.y+plus.h/2)
assert(hit and hit.type=='open')
assert(act('open') and draw())
local policy=panel:input_policy()
assert(Layout.contains(policy.native_picker_rect,plus.x+plus.w/2,plus.y+plus.h/2))
assert(not panel:capture(plus.x+plus.w/2,plus.y+plus.h/2))
assert(region('cancel').x>=geometry.header.x)
assert(act('select_look','look-b') and draw())
assert(panel:capture(plus.x+plus.w/2,plus.y+plus.h/2))
assert(region('select_stats').x>=geometry.picker.x)
for _,r in ipairs(panel.regions)do
 assert(r.x>=0 and r.y>=0 and r.x+r.w<=resolution[1]+.001 and r.y+r.h<=resolution[2]+.001)
end
-- Clip a native card at the list boundary: it must not become an action.
assert(act('cancel'))
local cell=sample.native_prefix.cells[2]
cell.rect.y=geometry.prefix.y-10*s
assert(draw())
hit=panel:hit(cell.rect.x+cell.rect.w/2,geometry.prefix.y+2*s)
assert(not hit or hit.type~='open')
''')


def test_resize_moves_actions_and_discards_old_hit_regions():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open') and draw())
local old=region('cancel');local x,y=old.x+old.w/2,old.y+old.h/2
resolution={3840,1080}
assert(draw())
local moved=region('cancel')
assert(moved.x==old.x+960)
local stale=panel:hit(x,y);assert(not stale or stale.type~='cancel')
assert(panel:hit(moved.x+moved.w/2,moved.y+moved.h/2).type=='cancel')
''')
