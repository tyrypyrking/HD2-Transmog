"""Wizard presentation never substitutes for native insertion or ownership."""
from test_variant_wizard import FIXTURE, run_lua


RENDER_FIXTURE = r'''
local P=dofile('src/wizard_panel.lua')
local function vector(...)return {...}end
local created,destroyed,texts,rects,bitmaps,uvbitmaps=0,0,{},{},{},{}
local material_names,material_requests={},{}
local worlds={'main','armory'}
local resolution={1920,1080}
local e={Vector2=vector,Vector3=vector,Color=vector,
 IdString64={from_hex=function(value)return value end},
 Application={worlds=function()return worlds end,main_world=function()return 'main'end,
   can_get=function(kind,value)return kind=='material' and value=='0123456789abcdef' end},
 World={create_screen_gui=function()created=created+1;return created end,
   destroy_gui=function()destroyed=destroyed+1 end},
 Gui={resolution=function()return unpack(resolution)end,material=function(gui,name)
   local handle=newproxy(true);material_names[handle]=name
   material_requests[#material_requests+1]={gui=gui,name=name,handle=handle};return handle end,
   rect=function(_,pos,size,color)rects[#rects+1]={pos=pos,size=size,color=color}end,
   text=function(_,text,font,size,material,pos)texts[#texts+1]={value=text,pos=pos,size=size}end,
   bitmap=function(_,material,pos,size)bitmaps[#bitmaps+1]={material=material_names[material]or material,handle=material,pos=pos,size=size}end,
   bitmap_uv=function(_,material,uv0,uv1,pos,size)uvbitmaps[#uvbitmaps+1]={material=material_names[material]or material,handle=material,pos=pos,size=size,uv0=uv0,uv1=uv1}end},
 Material={set_scalar=function()end,set_vector2=function()end,set_vector4=function()end,set_texture=function()end}}
local panel=P.new(e)
local sample={kind='armory',font='font',material='font-material',atlas='font-atlas'}
local function draw()return panel:draw(sample,wizard:view(state,context),context)end
local function shown(value)
 for _,text in ipairs(texts)do if text.value==value then return true,text end end
 return false
end
local function region(kind)
 for _,r in ipairs(panel.regions)do if r.action.type==kind then return r end end
end
local function click(kind)
 local r=assert(region(kind),kind)
 return panel:hit(r.x+r.w/2,r.y+r.h/2)
end
'''


def test_no_browse_overlay_exists_without_explicit_native_reserved_row():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(draw() and created==0 and #panel.captures==0 and not panel:capture(220,800))
assert(not panel:hit(220,800))
sample.custom_section={x=172,y=650,w=644,h=196}
assert(draw() and created==1 and shown('Custom Variant'))
assert(panel:capture(173,651) and panel:capture(815,845))
assert(not panel:capture(200,600))
assert(click('open').type=='open' and click('select_variant').label=='Existing')
sample.custom_section=nil
assert(draw() and destroyed==1 and not panel:capture(173,651))
assert(not panel:handle({type='panel_page',target='section',delta=1}))
''')


def test_section_places_saved_cards_before_plus_and_captures_disabled_surfaces():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
state.presets.Unavailable=catalog.locked
sample.custom_section={x=172,y=650,w=644,h=196}
assert(draw())
local saved,plus=region('select_variant'),region('open')
assert(saved.x<plus.x)
local view=wizard:view(state,context)
assert(view.section.tiles[2].label=='Unavailable' and not view.section.tiles[2].enabled)
local cardwidth=(644-3*7)/4
local hit=panel:hit(172+cardwidth+7+10,670)
assert(hit.type=='panel_background')
assert(not shown('SAVED VARIANTS'))
''')


def test_look_step_leaves_native_grid_and_3d_preview_uncovered():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open') and draw())
local policy=panel:input_policy()
assert(policy.native_look_pick and policy.block_native_apply and policy.block_native_compare)
assert(not policy.block_native_grid)
assert(not panel:capture(300,500) and not panel:capture(600,820))
assert(not panel:hit(300,500))
assert(not panel:capture(1400,750)) -- Native 3D look preview remains available.
assert(panel:capture(200,860)) -- Wizard header owns every pixel it covers.
assert(panel:capture(1000,350) and panel:capture(1800,130)) -- Old stats/perk/Apply.
assert(panel:capture(1800,20)) -- Native bottom Apply hint is covered too.
assert(not region('back') and region('cancel') and not region('create'))
assert(shown('Choose an owned armor thumbnail to use its look.'))
assert(#bitmaps==0 and #uvbitmaps==0) -- No duplicated look thumbnail grid.
''')


def test_stats_cards_preserve_model_order_and_only_show_unboosted_base_values():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open'));assert(act('select_look','look-b'));assert(draw())
assert(panel:capture(300,500) and panel:input_policy().block_native_grid)
assert(not panel:input_policy().native_look_pick)
local choices={}
for _,r in ipairs(panel.regions)do
 if r.action.type=='select_stats' then choices[#choices+1]=r end
end
assert(#choices==3 and choices[1].action.id=='base:50/550/125')
assert(choices[2].action.id=='base:100/500/100' and choices[3].action.id=='base:150/450/50')
assert(choices[1].y>choices[2].y and choices[2].y>choices[3].y)
assert(shown('50') and shown('550') and shown('125') and not shown('200'))
assert(shown('Passive bonuses are excluded.'))
assert(click('back').type=='back' and click('cancel').type=='cancel')
assert(panel:hit(1800,130).type=='panel_background') -- Disabled Create blocks native Apply.
''')


def test_passive_cards_show_native_resource_icons_and_exact_descriptions():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
context.passive_variants['perk-b'].icon_hash='0123456789abcdef'
choose();assert(draw())
assert(shown('Padding') and shown('Exact owned clause.'))
assert(#bitmaps==1 and bitmaps[1].material=='0123456789abcdef')
assert(bitmaps[1].pos[3]>983) -- Icon is above the badge backing rectangle.
assert(region('select_passive') and region('create'))
assert(click('create').type=='create')
assert(shown('Beta') and shown('50') and shown('550') and shown('125'))
assert(shown('Create saves this variant. Your equipped armor stays unchanged.'))
''')


def test_review_does_not_infer_or_add_passive_boosts_to_base_stats():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
context.stats_profiles['stats-b'].displayed_values={armor_rating=999,speed=550,stamina_regen=125}
context.resolved_stats={['stats-b|perk-a']={verified=false,effective={armor_rating=999}}}
choose();assert(draw())
assert(shown('50') and not shown('999'))
context.stats_profiles['stats-b'].base_values_verified=false
texts={};assert(draw())
assert(not region('create') and shown('--') and not shown('50'))
''')


def test_paging_keeps_option_order_and_never_dispatches_domain_actions():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open'));assert(act('select_look','look-b'));assert(act('select_stats','base:50/550/125'))
local view=wizard:view(state,context)
for i=1,12 do
 view.options[i]={id='passive-'..i,label='Perk '..i,effects={'Clause '..i},action={type='select_passive',id='passive-'..i}}
end
assert(panel:draw(sample,view,context))
assert(region('select_passive').action.id=='passive-1')
local page=click('panel_page')
assert(page.target=='options' and page.delta==1)
assert(panel:handle(page) and panel:draw(sample,view,context))
assert(region('select_passive').action.id=='passive-4')
assert(not panel:handle({type='select_passive',id='passive-4'}))
assert(state.selected.passive_variant_id=='perk-a' and not view.can_create)
''')


def test_all_long_passive_clauses_can_be_read_in_review_pages():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
context.passive_variants['perk-a']={effects={}}
for i=1,20 do context.passive_variants['perk-a'].effects[i]='Effect line '..i end
choose();assert(draw())
assert(shown('Effect line 1') and shown('Effect line 7') and not shown('Effect line 20'))
assert(panel:handle({type='panel_page',target='review',delta=1}));texts={};assert(draw())
assert(shown('Effect line 8') and shown('Effect line 14'))
assert(panel:handle({type='panel_page',target='review',delta=1}));texts={};assert(draw())
assert(shown('Effect line 15') and shown('Effect line 20') and region('create'))
''')


def test_resource_previews_need_explicit_verification_and_pointer_descriptors_are_rejected():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
sample.custom_section={x=172,y=650,w=644,h=196}
context.appearance_previews['look-a']={material='0123456789abcdef'}
assert(draw() and #bitmaps==0 and shown('Saved look'))
context.appearance_previews['look-a'].verified=true
assert(draw() and #bitmaps==1)
context.appearance_previews['look-a']={material_pointer=1234,material='0123456789abcdef',verified=true,
 native_handle_verified=true,valid=function()error('A raw pointer must never be examined')end}
assert(draw() and #bitmaps==1 and #uvbitmaps==0)
''')


def test_borrowed_original_engine_handles_need_fresh_proof_before_retained_reuse():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
sample.custom_section={x=172,y=650,w=644,h=196}
local live,checks=true,0
local handle=newproxy(true)
context.appearance_previews['look-a']={material_handle=handle,handle_source='engine_material',
 native_handle_verified=true,uv={0,0,1,1},valid=function()checks=checks+1;return live end}
assert(draw() and #uvbitmaps==1 and uvbitmaps[1].material==handle)
local before,oldchecks=created,checks
assert(draw() and created==before and checks>oldchecks)
live=false
assert(draw() and created==before+1 and destroyed==1 and #uvbitmaps==1)
assert(shown('Saved look'))
context.appearance_previews['look-a'].material_handle=newproxy(true);live=true
assert(draw() and #uvbitmaps==2)
''')


def test_retained_reuse_and_lifecycle_clear_capture_without_native_resize():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
choose();assert(draw())
local before=created
assert(draw() and created==before)
worlds={'main'}
assert(not draw() and #panel.captures==0 and not panel:hit(1800,130))
worlds={'main','armory'};assert(draw())
sample.kind='ship'
assert(not draw() and #panel.captures==0)
sample.kind='armory';sample.custom_section={x=-1,y=100,w=644,h=196}
assert(not draw())
sample.custom_section=nil;sample.wizard_layout={review={x=1000,y=100,w=1,h=1}}
assert(not draw())
''')


def test_no_triple_or_domain_state_is_mutated_by_rendering_and_local_paging():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
local before=S.encode(state)
choose();local view=wizard:view(state,context)
assert(panel:draw(sample,view,context))
assert(panel:capture(1800,130) and panel:hit(1800,130).type=='create')
assert(S.encode(state)==before and state.selected.stats_id=='stats-a')
assert(view.selection.stats_id=='stats-b' and wizard:view(state,context).can_create)
panel:clear();assert(S.encode(state)==before and #panel.captures==0)
''')


PREFIX_FIXTURE = r'''
sample.native_prefix={verified=true,clip={x=172,y=104,w=644,h=738},
 headers={{rect={x=202,y=796,w=590,h=46},text='Custom Variant'}},
 cells={
   {rect={x=202,y=600,w=180,h=190},key='variant:Existing',kind='variant',label='Existing',
    passive={icon_hash='0123456789abcdef'},selected=true},
   {rect={x=399,y=600,w=180,h=190},key='create',kind='create',label='+'},
 }}
'''


def test_native_prefix_uses_measured_header_and_cells_without_old_section():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
assert(sample.custom_section==nil and draw())
assert(shown('Custom Variant') and shown('Existing') and shown('+'))
assert(panel:hit(230,700).type=='select_variant' and panel:hit(230,700).label=='Existing')
assert(panel:hit(450,700).type=='open')
assert(panel:hit(250,820).type=='panel_background')
assert(not panel:capture(700,700)) -- Untouched native cell in the same row.
assert(not panel:capture(250,450)) -- Original list below the prefix stays native.
assert(not panel:capture(390,700)) -- Native gap is not captured.
assert(#panel.captures==3 and panel:input_policy().native_prefix)
assert(panel:input_policy().custom_cells_require_interception)
assert(not panel:input_policy().block_native_apply)
''')


def test_prefix_preserves_native_variant_thumbnail_and_uses_only_resource_badge():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local calls=0
local borrowed={material_handle=newproxy(true),material_pointer=1234,native_handle_verified=true,
 handle_source='engine_material',valid=function()calls=calls+1;error('No handle calls in prefix')end,uv={0,0,1,1}}
context.appearance_previews['look-a']=borrowed
context.passive_icons={['perk-a']=borrowed}
sample.native_prefix.cells[1].passive.material_handle=borrowed.material_handle
sample.native_prefix.cells[1].passive.material_pointer=borrowed.material_pointer
sample.native_prefix.cells[1].passive.valid=borrowed.valid
assert(draw() and calls==0 and #uvbitmaps==0)
assert(#bitmaps==1 and bitmaps[1].material=='0123456789abcdef')
local center_x,center_y=290,700
for _,r in ipairs(rects)do
 assert(not(center_x>=r.pos[1] and center_x<r.pos[1]+r.size[1]
  and center_y>=r.pos[2] and center_y<r.pos[2]+r.size[2]),'variant thumbnail was covered')
end
local plus_covered=false
for _,r in ipairs(rects)do
 if r.pos[1]==399 and r.pos[2]==600 and r.size[1]==180 and r.size[2]==190 then plus_covered=true end
end
assert(plus_covered and not shown('Saved look'))
assert(bitmaps[1].pos[1]==207 and bitmaps[1].pos[2]>750)
for _,r in ipairs(rects)do
 assert(not(367>=r.pos[1]and 367<r.pos[1]+r.size[1]and 774>=r.pos[2]and 774<r.pos[2]+r.size[2]),
  'native top-right selection marker was covered')
end
assert(bitmaps[1].pos[3]>983)
''')


def test_prefix_clips_partial_variants_and_skips_invalid_cells_without_drawing_outside_clip():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local prefix=sample.native_prefix
prefix.headers[2]={rect={x=202,y=825,w=590,h=46},text='Custom Variant'}
prefix.cells[#prefix.cells+1]={rect={x=750,y=600,w=180,h=190},key='outside-right',kind='variant',label='Existing'}
prefix.cells[#prefix.cells+1]={rect={x=202,y=50,w=180,h=190},key='outside-bottom',kind='variant',label='Existing'}
prefix.cells[#prefix.cells+1]={rect={x=202,y=600,w=0/0,h=190},key='invalid',kind='create'}
assert(draw() and #panel.captures==5)
assert(panel:hit(800,700).type=='panel_background' and panel:hit(250,150).type=='panel_background')
assert(not panel:capture(817,700) and not panel:capture(250,103))
local clip=prefix.clip
for _,r in ipairs(rects)do
 assert(r.pos[1]>=clip.x and r.pos[2]>=clip.y)
 assert(r.pos[1]+r.size[1]<=clip.x+clip.w and r.pos[2]+r.size[2]<=clip.y+clip.h)
end
for _,r in ipairs(bitmaps)do
 assert(r.pos[1]>=clip.x and r.pos[2]>=clip.y)
 assert(r.pos[1]+r.size[1]<=clip.x+clip.w and r.pos[2]+r.size[2]<=clip.y+clip.h)
end
''')


def test_prefix_missing_or_unverified_geometry_fails_closed_without_fallback():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
assert(draw());local before=created
sample.custom_section={x=172,y=650,w=644,h=196}
sample.native_prefix.verified=false
assert(not draw() and created==before and #panel.captures==0)
sample.native_prefix=false
assert(not draw() and #panel.captures==0)
sample.native_prefix={verified=true,clip={x=172,y=104,w=644,h=738},cells={}}
assert(not draw() and #panel.captures==0) -- Missing measured headers.
sample.native_prefix={verified=true,clip={x=-1,y=104,w=644,h=738},headers={},cells={}}
assert(not draw() and #panel.captures==0)
sample.native_prefix=nil;sample.custom_section=nil
assert(draw() and #panel.captures==0)
''')


def test_prefix_signature_tracks_geometry_content_selection_and_ownership():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
assert(draw());local before=created
assert(draw() and created==before)
sample.native_prefix.cells[2].rect.x=410
assert(draw() and created==before+1 and panel:hit(405,700)==nil)
before=created;sample.native_prefix.cells[1].selected=false
assert(draw() and created==before+1)
before=created;sample.native_prefix.cells[1].passive.icon_hash='fedcba9876543210'
assert(draw() and created==before+1)
before=created;state.ownership_verified=false
assert(draw() and created==before+1)
assert(panel:hit(230,700).type=='panel_background' and panel:hit(450,700).type=='panel_background')
sample.native_prefix=nil
assert(draw() and #panel.captures==0)
''')


def test_prefix_unknown_saved_labels_do_not_gain_actions_or_replace_original_cells():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.native_prefix.cells[1].label='Unknown saved variant'
sample.native_prefix.headers[1].text='Light Armor'
assert(draw())
assert(not panel:capture(230,700) and not panel:capture(250,820))
assert(not shown('Unknown saved variant') and not shown('Light Armor'))
assert(panel:hit(450,700).type=='open')
''')


def test_native_prefix_is_ignored_during_wizard_and_does_not_recreate_look_grid():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
assert(act('open') and draw())
assert(not panel:capture(230,700) and not panel:capture(450,700))
assert(panel:input_policy().native_look_pick and not panel:input_policy().native_prefix)
assert(#bitmaps==0 and not shown('+'))
''')


SAVED_REVIEW_FIXTURE=r'''
state.presets.Existing={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}
context.passive_variants['perk-b'].icon_hash='0123456789abcdef'
local view=wizard:view(state,context)
view.selected_variant={label='Existing',request=state.presets.Existing}
local function review_draw()return panel:draw(sample,view,context)end
'''


def test_saved_review_shows_chosen_components_without_create_or_apply_action():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
local before=S.encode(state)
assert(review_draw())
assert(shown('Saved variant') and shown('Existing') and shown('Beta'))
assert(shown('BASE STATS') and shown('50') and shown('550') and shown('125'))
assert(shown('Padding') and shown('Exact owned clause.'))
assert(not shown('Create') and not shown('Apply') and not region('create') and not region('apply'))
assert(#bitmaps==2) -- Prefix badge plus chosen passive's resource icon.
assert(panel:hit(1800,130).type=='panel_background')
assert(panel:input_policy().saved_variant_review and panel:input_policy().block_native_apply)
assert(panel:input_policy().block_native_compare and not panel:input_policy().wizard_open)
assert(S.encode(state)==before and state.selected.stats_id=='stats-a')
''')


def test_saved_review_keeps_prefix_cards_plus_original_grid_and_3d_preview_available():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
assert(review_draw())
assert(panel:hit(230,700).type=='select_variant')
assert(panel:hit(450,700).type=='open')
assert(panel:input_policy().native_prefix)
assert(not panel:capture(230,450) and not panel:capture(700,700))
assert(not panel:capture(1400,750))
assert(panel:capture(1000,350) and panel:capture(1500,300))
assert(panel:capture(1800,130) and panel:capture(1800,20))
assert(not panel:input_policy().block_native_grid)
''')


def test_saved_review_requires_verified_base_values_and_ignores_boosted_donor_totals():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
context.stats_profiles['stats-b'].displayed_values={armor_rating=999,speed=999,stamina_regen=999}
context.resolved_stats={['stats-b|perk-b']={verified=true,effective={armor_rating=999,speed=999,stamina_regen=999}}}
assert(review_draw() and shown('50') and not shown('999'))
context.stats_profiles['stats-b'].base_values_verified=false
texts={};assert(review_draw() and shown('--') and not shown('50') and not shown('999'))
context.stats_profiles['stats-b'].base_values_verified=true
context.stats_profiles['stats-b'].base_only=false
local before=created
assert(review_draw() and created==before and shown('--') and not shown('50'))
''')


def test_saved_review_retains_and_invalidates_with_selected_metadata_without_native_handles():
    run_lua(FIXTURE + RENDER_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
context.passive_icons={['perk-b']={material_handle=newproxy(true),native_handle_verified=true,
 handle_source='engine_material',valid=function()error('Saved review does not use native handles')end}}
assert(review_draw() and shown('Saved variant') and #uvbitmaps==0 and #bitmaps==1)
local before=created
assert(review_draw() and created==before)
view.selected_variant={label='Another saved variant',request={appearance_id='look-a',stats_id='stats-a',passive_variant_id='perk-a'}}
texts={};assert(review_draw() and created==before+1 and shown('Another saved variant') and shown('Alpha'))
assert(shown('150') and shown('450') and not shown('550'))
view.selected_variant=nil
assert(review_draw() and #panel.captures==0)
assert(not panel:input_policy().saved_variant_review)
''')


def test_saved_review_pages_complete_passive_text_and_resets_page_on_another_variant():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
context.passive_variants['perk-b'].effects={}
for i=1,18 do context.passive_variants['perk-b'].effects[i]='Saved effect '..i end
assert(review_draw() and shown('Saved effect 1') and not shown('Saved effect 18'))
assert(panel:handle({type='panel_page',target='review',delta=1}));texts={}
assert(review_draw() and shown('Saved effect 8'))
assert(panel:handle({type='panel_page',target='review',delta=1}));texts={}
assert(review_draw() and shown('Saved effect 18') and not region('create'))
view.selected_variant={label='Another variant',request=state.presets.Existing}
texts={};assert(review_draw() and shown('Saved effect 1') and not shown('Saved effect 18'))
''')


def test_absent_malformed_or_creation_time_saved_review_does_not_steal_native_browse():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.selected_variant={label='Incomplete',request={appearance_id='look-a'}}
assert(review_draw() and not panel:capture(1800,130))
assert(not panel:input_policy().saved_variant_review and region('open'))
view.selected_variant={label='Bad request',request={appearance_id='bad id',stats_id='stats-a',passive_variant_id='perk-a'}}
assert(review_draw() and not panel:capture(1800,130))
choose();view=wizard:view(state,context)
view.selected_variant={label='Ignored saved name',request=state.presets.Existing}
texts={};assert(review_draw() and region('create') and not shown('Ignored saved name'))
assert(not panel:input_policy().saved_variant_review and panel:input_policy().wizard_open)
''')


def test_resource_bitmaps_use_original_engine_userdata_once_per_gui_material():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
assert(review_draw() and #bitmaps==2)
assert(type(bitmaps[1].handle)=='userdata' and bitmaps[1].handle==bitmaps[2].handle)
local requests={}
for _,request in ipairs(material_requests)do
 if request.name=='0123456789abcdef' then requests[#requests+1]=request end
end
assert(#requests==1 and bitmaps[1].handle==requests[1].handle)
local first=bitmaps[1].handle
assert(review_draw() and #bitmaps==2 and #material_requests==2) -- Font plus one icon lookup.
sample.native_prefix.cells[1].selected=false
assert(review_draw() and #bitmaps==4 and #material_requests==4)
assert(bitmaps[3].handle==bitmaps[4].handle and bitmaps[3].handle~=first)
assert(destroyed==1) -- No material outlives its owned GUI.
''')


def test_resource_bitmap_rejects_integer_cdata_pointer_string_and_table_material_results():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local ffi=require('ffi')
local original=e.Gui.material
local invalid={123456,ffi.cast('void *',123456),'0123456789abcdef',{material_pointer=123456}}
for _,bad in ipairs(invalid)do
 e.Gui.material=function(gui,name)
  if name=='0123456789abcdef' then return bad end
  return original(gui,name)
 end
 panel:clear();assert(draw())
 assert(#bitmaps==0 and #uvbitmaps==0)
end
''')


def test_metrics_show_retention_when_only_observation_tables_and_closures_are_recreated():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local function preview()
 return {material_pointer=123456,binding_verified=true,native_handle_verified=false,
  uv={0,0,1,1},generation='stable',valid=function()error('Prefix never calls this')end}
end
context.appearance_previews['look-a']=preview()
assert(draw());local m=panel:metrics()
assert(m.draw_count==1 and m.rebuild_count==1 and m.signature_ms>=0 and m.signature_bytes>0)
context.appearance_previews['look-a']=preview()
assert(draw());m=panel:metrics()
assert(m.draw_count==2 and m.rebuild_count==1 and m.signature_total_ms>=m.signature_ms)
sample.native_prefix.cells[1].rect.x=203
assert(draw());m=panel:metrics()
assert(m.draw_count==3 and m.rebuild_count==2)
m.draw_count=999
assert(panel:metrics().draw_count==3) -- Metric callers cannot mutate counters.
''')


def test_unreferenced_catalog_weights_modifiers_labels_and_previews_do_not_rebuild_prefix_review():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
assert(review_draw());local before=created
context.stats_profiles['stats-a'].body_weights={{body_type=1,pieces={{slot=2,kind=0,weight=2}}}}
context.stats_profiles['stats-b'].body_weights={{body_type=99,pieces={{slot=8,kind=0,weight=1}}}}
context.passive_variants['perk-b'].modifiers={{modifier_id=123,value=9999}}
context.labels.appearance_id['look-d']='Offscreen look changed'
context.appearance_previews['look-d']={material_handle=newproxy(true),native_handle_verified=true,
 handle_source='engine_material',valid=function()error('Unreferenced preview should not be inspected')end}
context.passive_icons={unreferenced={material_handle=newproxy(true),native_handle_verified=true,
 handle_source='engine_material',valid=function()error('Unreferenced icon should not be inspected')end}}
context.unused={nested={string.rep('ignored',10000)}}
assert(review_draw() and created==before)
assert(panel:metrics().signature_bytes<8000)
context.stats_profiles['stats-b'].base_values.armor_rating=75
assert(review_draw() and created==before+1 and shown('75'))
context.labels.appearance_id['look-b']='Visible look changed'
assert(review_draw() and created==before+2 and shown('Visible look changed'))
context.passive_variants['perk-b'].effects={'Visible effect changed'}
assert(review_draw() and created==before+3 and shown('Visible effect changed'))
''')


def test_offscreen_option_changes_do_not_rebuild_until_their_page_is_visible():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
choose();local view=wizard:view(state,context)
for i=1,9 do view.options[i]={id='option-'..i,label='Option '..i,effects={'Effect '..i},
 action={type='select_passive',id='option-'..i}}end
assert(panel:draw(sample,view,context));local before=created
view.options[5].label='Changed offscreen option'
view.options[5].effects={'Changed offscreen effect'}
assert(panel:draw(sample,view,context) and created==before)
view.options[2].label='Changed visible option'
assert(panel:draw(sample,view,context) and created==before+1 and shown('Changed visible option'))
assert(panel:handle({type='panel_page',target='options',delta=1}))
assert(panel:draw(sample,view,context) and created==before+2)
assert(shown('Changed offscreen option') and shown('Changed offscreen effect'))
''')


def test_only_visible_legacy_saved_cards_validate_previews_or_invalidate_signature():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
sample.custom_section={x=172,y=600,w=644,h=196}
local view=wizard:view(state,context)
view.section.tiles={}
local unused_calls=0
for i=1,8 do view.section.tiles[i]={kind='variant',label='Card '..i,enabled=true,
 request=catalog.a,action={type='select_variant',label='Card '..i}}end
view.section.tiles[6].preview={material_handle=newproxy(true),native_handle_verified=true,handle_source='engine_material',
 valid=function()unused_calls=unused_calls+1;return false end}
assert(panel:draw(sample,view,context));local before=created
assert(unused_calls==0)
view.section.tiles[6].label='Changed hidden card'
assert(panel:draw(sample,view,context) and created==before and unused_calls==0)
assert(panel:handle({type='panel_page',target='section',delta=1}))
assert(panel:draw(sample,view,context) and created==before+1 and unused_calls>0)
assert(shown('Changed hidden card'))
''')


def test_unrendered_look_options_and_unused_review_pages_keep_the_gui_retained():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open'));local view=wizard:view(state,context)
assert(panel:draw(sample,view,context));local before=created
view.options[1].label='Native grid owns this label'
view.options[1].preview={material_pointer=123456,generation='changed'}
assert(panel:draw(sample,view,context) and created==before)
view.open=false;view.step=0
context.passive_variants['perk-b'].effects={}
for i=1,14 do context.passive_variants['perk-b'].effects[i]='Clause '..i end
view.selected_variant={label='Existing',request={appearance_id='look-b',stats_id='stats-b',passive_variant_id='perk-b'}}
assert(panel:draw(sample,view,context));before=created
context.passive_variants['perk-b'].effects[12]='Changed second-page clause'
assert(panel:draw(sample,view,context) and created==before)
assert(panel:handle({type='panel_page',target='review',delta=1}))
assert(panel:draw(sample,view,context) and created==before+1 and shown('Changed second-page clause'))
''')


ORIGINAL_ART_FIXTURE=r'''
PassiveIconGeometry=dofile('src/passive_icon_geometry.lua')
PassiveIconDraw=dofile('src/passive_icon_draw.lua')
local native_icon='7c818b04a594d8e5'
'''


def test_original_native_art_draws_gold_and_black_prefix_and_saved_review_without_resources():
    run_lua(FIXTURE + ORIGINAL_ART_FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
sample.native_prefix.cells[1].passive.icon_hash=native_icon
context.passive_variants['perk-b'].icon_hash=native_icon
context.passive_icons={['perk-b']={material_handle=newproxy(true),native_handle_verified=true,
 handle_source='engine_material',valid=function()error('Known art must not inspect a native handle')end}}
e.Application.can_get=function()error('Original icon art needs no resource query')end
assert(review_draw() and #bitmaps==0 and #uvbitmaps==0)
local m=panel:metrics()
assert(m.original_icon_available and m.original_icon_draws==2 and m.original_icon_rectangles>100)
local gold,black,art_count=false,false,0
for _,r in ipairs(rects)do if r.pos[3]==985 then
 art_count=art_count+1
 if r.color[1]==255 and r.color[2]>=250 and r.color[3]>=215 and r.color[3]<=221 and r.color[4]>=29 and r.color[4]<=31 then gold=true end
 if r.color[1]==255 and r.color[2]<=2 and r.color[3]<=2 and r.color[4]<=1 then black=true end
end end
assert(gold and black and art_count==m.original_icon_rectangles)
assert(not shown('?'))
assert(panel:hit(230,700).type=='select_variant' and panel:hit(450,700).type=='open')
''')


def test_original_art_covers_wizard_passive_choices_review_and_legacy_saved_badges():
    run_lua(FIXTURE + ORIGINAL_ART_FIXTURE + RENDER_FIXTURE + r'''
context.passive_variants['perk-b'].icon_hash=native_icon
choose();assert(act('select_passive','perk-b'));assert(draw())
assert(panel:metrics().original_icon_draws==2 and #bitmaps==0)
assert(act('cancel'))
context.passive_variants['perk-a']={icon_hash=native_icon}
sample.custom_section={x=172,y=600,w=644,h=196}
assert(draw())
assert(panel:metrics().original_icon_draws==3 and #bitmaps==0)
''')


def test_original_art_is_retained_and_does_not_rebuild_when_unneeded_resource_metadata_changes():
    run_lua(FIXTURE + ORIGINAL_ART_FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
sample.native_prefix.cells[1].passive.icon_hash=native_icon
context.passive_variants['perk-b'].icon_hash=native_icon
assert(review_draw());local before=panel:metrics();local rectangles=#rects
context.passive_icons={['perk-b']={material='bad-resource',texture='missing',generation='new'}}
context.passive_variants['perk-b'].modifiers={{unused=999}}
assert(review_draw())
local after=panel:metrics()
assert(after.rebuild_count==before.rebuild_count and after.original_icon_draws==before.original_icon_draws)
assert(#rects==rectangles and after.signature_bytes<8000)
sample.native_prefix.cells[1].passive.icon_hash='e5ad658ba8221acf'
assert(review_draw() and panel:metrics().rebuild_count==before.rebuild_count+1)
assert(panel:metrics().original_icon_draws==before.original_icon_draws+2)
''')


def test_unknown_icon_hash_keeps_guarded_original_userdata_or_question_fallback():
    run_lua(FIXTURE + ORIGINAL_ART_FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
assert(draw() and #bitmaps==1)
assert(panel:metrics().original_icon_draws==0 and type(bitmaps[1].handle)=='userdata')
sample.native_prefix.cells[1].passive.icon_hash='ffffffffffffffff'
assert(draw() and #bitmaps==1 and shown('?'))
assert(panel:metrics().original_icon_draws==0)
''')


def test_partial_create_tile_covers_only_visible_intersection_and_cannot_activate():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.native_prefix.headers={}
sample.native_prefix.cells={{rect={x=399,y=40,w=180,h=190},key='create',kind='create',label='+'}}
assert(draw() and #rects==1)
local r=rects[1]
assert(r.pos[1]==399 and r.pos[2]==104 and r.size[1]==180 and r.size[2]==126)
assert(r.color[1]==255) -- Opaque even though only part of the native image is visible.
assert(shown('+') and not shown('Create variant'))
assert(not region('open') and panel:hit(450,120).type=='panel_background')
assert(not panel:capture(450,80) and not panel:hit(450,80))
for _,text in ipairs(texts)do
 assert(text.pos[1]>=399 and text.pos[2]>=104)
 assert(text.pos[1]+text.size<=579 and text.pos[2]+text.size<=230)
end
''')


def test_thin_partial_create_strip_stays_opaque_without_plus_or_caption():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.native_prefix.headers={}
sample.native_prefix.cells={{rect={x=399,y=-60,w=180,h=190},key='create',kind='create'}}
assert(draw() and #rects==1)
assert(rects[1].pos[2]==104 and rects[1].size[2]==26)
assert(#texts==0 and not region('open'))
assert(panel:hit(450,115).type=='panel_background')
assert(not panel:capture(450,100) and not panel:capture(450,131))
sample.native_prefix.cells[1].rect={x=800,y=600,w=180,h=190}
rects={};texts={};assert(draw())
assert(#rects==1 and rects[1].pos[1]==800 and rects[1].size[1]==16)
assert(#texts==0 and panel:hit(805,650).type=='panel_background')
assert(not panel:hit(820,650))
''')


def test_scroll_from_partial_to_full_create_restores_only_the_fully_visible_action():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.native_prefix.headers={}
sample.native_prefix.cells={{rect={x=399,y=40,w=180,h=190},key='create',kind='create'}}
assert(draw());local before=created
assert(not region('open'))
sample.native_prefix.cells[1].rect.y=600
texts={};assert(draw() and created==before+1)
local caption=false;for _,text in ipairs(texts)do if text.value:find('^Create')then caption=true end end
assert(region('open') and panel:hit(450,700).type=='open' and caption)
sample.native_prefix.cells[1].rect.y=900
rects={};texts={};assert(draw() and created==before+2)
assert(#rects==0 and #texts==0 and #panel.captures==0 and not region('open'))
''')


def test_measured_prefix_captions_keep_fitting_variant_numbers_and_measure_only_on_redraw():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
state.presets['Custom Variant 1']=catalog.a
state.presets['Custom Variant 2']=catalog.b
sample.native_prefix.cells[1].label='Custom Variant 1'
sample.native_prefix.cells[2].kind='variant';sample.native_prefix.cells[2].label='Custom Variant 2'
local calls=0
e.Gui.text_extents=function(gui,value,font,size)
 calls=calls+1;assert(gui==panel.gui and font=='font' and size==13)
 return {x=-3,y=0},{x=-3+#value*6,y=size},'unused-result'
end
assert(draw() and shown('Custom Variant 1') and shown('Beta - Padding'))
assert(calls==2 and not shown('Custom Varia...'))
assert(panel:hit(230,700).label=='Custom Variant 1' and panel:hit(450,700).label=='Custom Variant 2')
local before=created;assert(draw() and created==before and calls==2)
sample.native_prefix.cells[1].rect.w=90
texts={};assert(draw() and created==before+1 and calls>2)
assert(not shown('Custom Variant 1') and shown('Beta - Padding'))
''')


def test_measured_long_unicode_caption_fits_with_valid_utf8_ellipsis_and_preserves_action_label():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local name='Мой боевой вариант 名称 очень длинное имя'
state.presets[name]=catalog.a;sample.native_prefix.cells[1].label=name
local function count(value)
 local n=0;for _ in value:gmatch('[%z\1-\127\194-\244][\128-\191]*')do n=n+1 end;return n
end
e.Gui.text_extents=function(_,value,_,size)
 local minimum,maximum=newproxy(true),newproxy(true)
 getmetatable(minimum).__index=function(_,key)if key=='x'then return -2 end end
 getmetatable(maximum).__index=function(_,key)if key=='x'then return count(value)*8-2 end end
 return minimum,maximum
end
assert(draw())
local caption
for _,text in ipairs(texts)do
 if text.pos[1]==208 and text.pos[2]>600 and text.pos[2]<630 then caption=text.value end
end
assert(caption and caption~=name and caption:sub(-3)=='...' and count(caption)*8<=168)
local check=S.new();check.presets[caption]=catalog.a;assert(S.validate(check))
assert(panel:hit(230,700).label==name)
''')


def test_missing_failed_or_malformed_text_measurement_uses_guarded_caption_fallback():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local name='A very long saved armor variant name'
state.presets[name]=catalog.a;sample.native_prefix.cells[1].label=name
local function caption()
 for _,text in ipairs(texts)do
  if text.pos[1]==208 and text.pos[2]>600 and text.pos[2]<630 then return text.value end
 end
end
assert(draw());local fallback=caption();assert(fallback and fallback:sub(-3)=='...')
local invalid={
 function()error('Text measurement unavailable')end,
 function()return nil,nil end,
 function()return {x=0/0},{x=10}end,
 function()return {x=20},{x=10}end,
 function()return {x='wrong'},{x=10}end,
}
for _,measure in ipairs(invalid)do
 e.Gui.text_extents=measure;panel:clear();texts={}
 assert(draw() and caption()==fallback and panel:hit(230,700).label==name)
end
''')


def test_native_details_exposes_native_views_and_intercepts_apply_without_replacement_art():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
assert(review_draw() and shown('Saved variant'))
view.native_details=true;view.can_apply=true
texts={};rects={};assert(review_draw())
assert(not shown('Saved variant') and not shown('BASE STATS') and not shown('Padding'))
assert(not panel:capture(1000,350) and not panel:capture(1500,300))
assert(panel:hit(1800,130).type=='apply_variant' and panel:hit(1800,20).type=='apply_variant')
assert(panel:hit(230,700).type=='select_variant' and panel:hit(450,700).type=='open')
local policy=panel:input_policy()
assert(policy.native_details and policy.block_native_apply and not policy.block_native_compare)
assert(not policy.saved_variant_review and not policy.wizard_open)
for _,r in ipairs(rects)do assert(r.pos[1]+r.size[1]<=816)end
local before=created
assert(review_draw() and created==before)
view.apply_pending=true
assert(review_draw() and created==before+1)
assert(panel:hit(1800,130).type=='panel_background' and not region('apply_variant'))
view.apply_pending=false;view.can_apply=false
assert(review_draw() and panel:hit(1800,20).type=='panel_background')
view.native_details=false
texts={};assert(review_draw() and shown('Saved variant'))
assert(panel:input_policy().saved_variant_review and panel:input_policy().block_native_compare)
''')


def test_pending_apply_captures_native_button_before_details_are_ready_and_never_changes_creation():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
local view=wizard:view(state,context)
view.apply_pending=true;view.can_apply=true
assert(panel:draw(sample,view,context) and #rects==0 and shown('Loading preview…'))
assert(panel:hit(1800,130).type=='panel_background' and not region('apply_variant'))
view.apply_pending=false;view.native_details='true'
assert(panel:draw(sample,view,context) and not panel:capture(1800,130))
choose();view=wizard:view(state,context)
view.native_details=true;view.can_apply=true;view.apply_pending=true
texts={};assert(panel:draw(sample,view,context))
assert(shown('BASE STATS') and region('create') and not region('apply_variant'))
assert(panel:input_policy().wizard_open and not panel:input_policy().native_details)
''')


def test_badges_follow_thumbnail_geometry_each_draw_and_reject_unrelated_image_bounds():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local cell=sample.native_prefix.cells[1]
cell.image_rect={x=206,y=638,w=172,h=148}
assert(draw());local before=created
assert(bitmaps[#bitmaps].pos[1]==211 and bitmaps[#bitmaps].pos[2]==753)
cell.rect.y=cell.rect.y+0.25;cell.image_rect.y=cell.image_rect.y+0.25
assert(draw() and created==before+1 and destroyed==1)
assert(bitmaps[#bitmaps].pos[2]==753.25)
-- A moving image can animate independently of its containing frame.
cell.image_rect.y=cell.image_rect.y-1
assert(draw() and created==before+2 and bitmaps[#bitmaps].pos[2]==752.25)
cell.image_rect={x=1,y=1,w=100,h=100}
assert(draw() and bitmaps[#bitmaps].pos[1]==207 and bitmaps[#bitmaps].pos[2]==757.25)
sample.native_prefix.cells={};sample.native_prefix.headers={}
assert(draw() and not panel:capture(230,700))
''')


def test_partial_variants_keep_badges_at_original_anchors_and_crop_resource_uvs():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local prefix=sample.native_prefix;prefix.headers={};prefix.cells[2]=nil
local cell=prefix.cells[1];cell.rect.y=90
assert(draw() and #bitmaps==1)
assert(bitmaps[1].pos[2]==247) -- Badge stays on thumbnail despite bottom clipping.
assert(not shown('Existing') and panel:hit(230,110).type=='panel_background')
cell.rect.y=670;rects={};texts={};assert(draw())
assert(#uvbitmaps==1 and #bitmaps==1)
local icon=uvbitmaps[1]
assert(icon.pos[2]==827 and icon.size[2]==15) -- Top 13 of the 28 pixels are clipped.
assert(icon.uv0[1]==0 and math.abs(icon.uv0[2]-13/28)<1e-9)
assert(icon.uv1[1]==1 and icon.uv1[2]==1)
assert(shown('Existing')) -- Bottom caption is still fully in the viewport.
for _,r in ipairs(rects)do assert(r.pos[2]>=104 and r.pos[2]+r.size[2]<=842)end
cell.rect.y=843;rects={};texts={};assert(draw())
assert(#rects==0 and #texts==0 and not panel:capture(230,841))
''')


def test_partial_original_badges_clip_without_moving_the_art_or_loading_materials():
    run_lua(FIXTURE + ORIGINAL_ART_FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.native_prefix.headers={};sample.native_prefix.cells[2]=nil
local cell=sample.native_prefix.cells[1]
cell.rect.y=670;cell.passive.icon_hash=native_icon
e.Application.can_get=function()error('Original badge must not load a resource')end
assert(draw() and #bitmaps==0 and #uvbitmaps==0)
assert(panel:metrics().original_icon_draws==1 and panel:metrics().original_icon_rectangles>0)
for _,r in ipairs(rects)do
 assert(r.pos[1]>=172 and r.pos[1]+r.size[1]<=816)
 assert(r.pos[2]>=104 and r.pos[2]+r.size[2]<=842)
end
''')


def test_native_variant_label_and_apply_notice_fit_the_lower_strip_without_covering_details():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.native_details=true;view.can_apply=true
assert(review_draw())
for _,item in ipairs(texts)do assert(item.pos[1]<=816 or (item.value~='Existing' and item.value~='Beta'))end
assert(panel:hit(1800,130).label=='Existing')
view.apply_notice='Armor refresh could not be verified.'
texts={};rects={};assert(review_draw())
assert(shown(view.apply_notice))
for _,item in ipairs(texts)do assert(item.pos[1]<=816 or item.value~='Beta')end
local _,notice=shown(view.apply_notice)
assert(notice.pos[1]>816 and notice.pos[2]>=104 and notice.pos[2]+notice.size<=162)
for _,r in ipairs(rects)do assert(r.pos[1]+r.size[1]<=816)end
assert(not panel:capture(1000,350) and not panel:capture(1500,300))
view.native_details=false;view.apply_pending=false
texts={};assert(review_draw() and shown(view.apply_notice) and shown('Saved variant'))
''')


def test_pending_preview_preserves_native_details_without_flashing_saved_review():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.apply_pending=true;view.native_details=false
assert(review_draw() and shown('Loading preview…') and not shown('Saved variant') and not shown('BASE STATS'))
assert(not panel:capture(1000,350) and not panel:capture(1500,300))
assert(panel:hit(1800,130).type=='panel_background' and panel:input_policy().block_native_compare)
for _,r in ipairs(rects)do assert(r.pos[1]+r.size[1]<=816)end
view.apply_pending=false;view.apply_notice='Preview could not be verified.'
texts={};assert(review_draw() and shown('Saved variant') and shown(view.apply_notice))
view.selected_variant=nil;sample.native_prefix=nil
texts={};rects={};assert(review_draw() and shown(view.apply_notice) and not shown('Saved variant'))
assert(#rects==0 and not panel:capture(1000,350) and panel:hit(1800,130).type=='panel_background')
''')


def test_verified_equipped_phase_updates_native_strip_and_disables_repeat_apply():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.native_details=true;view.can_apply=true;view.variant_phase='ready'
assert(review_draw())
for _,item in ipairs(texts)do assert(item.pos[1]<=816 or item.value~='Beta')end
view.can_apply=false;view.variant_phase='equipped';texts={};rects={}
assert(review_draw() and shown('Equipped'))
for _,item in ipairs(texts)do assert(item.pos[1]<=816 or item.value~='Beta')end
assert(panel:hit(1800,130).type=='panel_background' and not region('apply_variant'))
assert(not panel:capture(1000,350) and not panel:capture(1500,300))
for _,r in ipairs(rects)do assert(r.pos[1]+r.size[1]<=816)end
''')


def test_custom_category_and_original_badges_are_explicit_and_invalidate_retained_drawing():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
local prefix=sample.native_prefix
e.Application.can_get=function(kind)return kind=='material'end
prefix.category={text='CUSTOM VARIANTS',rect={x=290,y=855,w=405,h=48}}
prefix.original_badges={{rect={x=590,y=600,w=180,h=190},passive={icon_hash='fedcba9876543210'}}}
assert(draw()and shown('CUSTOM VARIANTS'))
local before=created;local count=#bitmaps
assert(count==2,'original badge was not drawn independently of variant badge')
assert(not panel:capture(600,700),'original card was converted into a custom action')
prefix.original_badges[1].rect.y=601
assert(draw()and created==before+1)
prefix.category=nil;texts={}
assert(draw()and created==before+2 and not shown('CUSTOM VARIANTS'))
''')


def test_equipment_uses_same_prefix_styling_with_no_create_surface():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
sample.kind='deployment'
wizard=W.new(S,{allow_create=false})
sample.native_prefix.cells[2]=nil
assert(draw() and shown('Custom Variant') and shown('Existing'))
assert(not shown('+') and not region('open') and not region('create'))
assert(panel:hit(230,700).type=='select_variant')
assert(not panel:capture(450,700))
assert(#bitmaps==1 and bitmaps[1].material=='0123456789abcdef')
assert(bitmaps[1].pos[1]==207 and bitmaps[1].pos[2]>750)
''')


def test_remove_button_is_armory_only_and_disabled_during_apply():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.native_details=true;view.can_apply=true;view.can_remove=true
assert(review_draw() and shown('Remove variant') and region('remove_variant'))
assert(region('remove_variant').action.label=='Existing')
view.apply_pending=true;assert(review_draw() and not region('remove_variant'))
view.apply_pending=false;sample.kind='deployment';texts={}
assert(review_draw() and not region('remove_variant') and not shown('Remove variant'))
''')


def test_long_appearance_perk_caption_uses_two_lines_inside_card():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + r'''
context.labels.appearance_id['look-a']='BP-77 Grand Juror'
context.labels.passive_variant_id['perk-a']='BALLISTIC PADDING'
e.Gui.text_extents=function(_,value,_,size)return {x=0,y=0},{x=#value*6,y=size}end
assert(draw())
local _,look=shown('BP-77 Grand Juror');local _,perk=shown('- BALLISTIC PADDING')
assert(look and perk and look.pos[2]>perk.pos[2])
assert(perk.pos[2]>=sample.native_prefix.cells[1].rect.y)
assert(look.pos[2]+look.size<=sample.native_prefix.cells[1].rect.y+34)
assert(panel:hit(230,700).label=='Existing')
''')


def test_native_picker_failure_never_restores_legacy_review_panel():
    run_lua(FIXTURE + RENDER_FIXTURE + PREFIX_FIXTURE + SAVED_REVIEW_FIXTURE + r'''
view.native_picker=true;view.native_details=false;view.can_apply=false
view.apply_notice='The native preview changed. Select the variant again.'
assert(review_draw() and not shown('Saved variant')and not shown('BASE STATS'))
assert(shown(view.apply_notice)and not panel:capture(1000,350))
assert(not region('apply_variant')and panel:capture(1800,130))
for _,r in ipairs(rects)do assert(r.pos[1]+r.size[1]<=816)end
sample.native_prefix=nil;texts={};rects={}
assert(review_draw()and not shown('Saved variant')and #rects==0)
''')


def test_creator_footer_covers_complete_inapplicable_compare_and_equip_hints():
    run_lua(FIXTURE + RENDER_FIXTURE + r'''
assert(act('open'));assert(draw())
assert(panel:capture(1540,20)and panel:capture(1880,20))
assert(not panel:capture(1380,20),'native Rotate hint was covered')
assert(not region('apply_variant'))
assert(act('cancel'));texts={};rects={};assert(draw())
assert(not panel:capture(1540,20)and not panel:capture(1880,20))
''')
