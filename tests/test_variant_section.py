"""Saved armor cards, independent perks, and base-versus-adjusted stat display."""
from test_variant_editor import FIXTURE, run_lua


def test_saved_card_actions_remain_stable_across_reordering_and_open_correct_editor():
    run_lua(FIXTURE + '''
local label='Мой: 50% вариант'
state.presets[label]={appearance_id='appearance-a',stats_id='stats-b',passive_variant_id='passive-a'}
local action=S.variant_action(label)
state.presets['AAA']={appearance_id='appearance-b',stats_id='stats-a',passive_variant_id='passive-b'}
local handled,notice,candidate,event=act(action)
assert(handled and not candidate and event.intent=='variant_select' and not event.open_editor)
assert(event.label==label and event.ownership_resolved and editor.draft.stats_id=='stats-b')
local _,_,_,event=act(S.variant_action(label,true))
assert(event.open_editor and event.intent=='variant_edit')
act('next_option','passive')
local before=editor.draft.passive_variant_id
local _,why,_,event=act(S.variant_action('AAA'))
assert(not event and why:find('discard') and editor.draft.passive_variant_id==before)
local _,_,_,event=act(S.variant_action(label,true))
assert(event.open_editor and editor.dirty)
''')


def test_saved_section_paginates_and_follows_newly_saved_selection():
    run_lua(FIXTURE + '''
for i=1,7 do state.presets['Variant '..i]={appearance_id='appearance-a',stats_id='stats-a',passive_variant_id='passive-b'}end
local model=S.editor_view(state,editor,'appearance',context)
assert(model.saved_section.count==7 and #model.saved_section.cards==3 and model.saved_section.pages==3)
act('next_variants');model=S.editor_view(state,editor,'appearance',context)
assert(model.saved_section.page==2 and model.saved_section.cards[1].label=='Variant 4')
act(S.variant_action('Variant 7'));model=S.editor_view(state,editor,'appearance',context)
assert(model.saved_section.page==3 and model.saved_section.cards[1].selected)
state.ownership_verified=false
model=S.editor_view(state,editor,'appearance',context)
assert(not model.saved_section.cards[1].available)
assert(model.saved_section.cards[1].request.passive_variant_id=='passive-b')
''')


def test_perk_totals_are_provided_once_without_reusing_native_boosted_totals():
    run_lua(FIXTURE + '''
local request={appearance_id='appearance-b',stats_id='stats-a',passive_variant_id='passive-b'}
context.stats_profiles={['stats-a']={base_only=true,base_values={armor_rating=100,speed=500,stamina_regen=100},
 displayed_values={armor_rating=150,speed=500,stamina_regen=100},native_perk_variant_id='passive-b'}}
context.resolved_stats={['stats-a|passive-b']={verified=true,
 base={armor_rating=100,speed=500,stamina_regen=100},effective={armor_rating=150,speed=500,stamina_regen=100}}}
local result=S.editor_stats(request,context)
assert(result.verified and result.rows[1].base==100 and result.rows[1].bonus==50 and result.rows[1].effective==150)
context.resolved_stats['stats-a|passive-b'].verified=false
result=S.editor_stats(request,context)
assert(not result.verified and result.rows[1].base==100 and result.rows[1].effective==nil)
context.resolved_stats['stats-a|passive-b']={verified=true,base={armor_rating=100},effective={armor_rating=0/0}}
assert(not S.editor_stats(request,context).verified)
''')


def test_card_uses_selected_independent_perk_icon_and_new_opens_editor():
    run_lua(FIXTURE + '''
context.passive_variants={['passive-a']={icon_hash='1111111111111111'},['passive-b']={icon_hash='2222222222222222'}}
state.presets['Mixed']={appearance_id='appearance-a',stats_id='stats-a',passive_variant_id='passive-b'}
local model=S.editor_view(state,editor,'appearance',context)
assert(model.saved_section.cards[1].passive_icon.material=='2222222222222222')
local _,_,_,event=act('new_variant');assert(event.open_editor)
''')


def test_reserved_cards_render_native_badge_at_top_right_and_capture_blank_space():
    run_lua(FIXTURE + '''
local P=dofile('src/panel.lua')
state.presets['Mixed']={appearance_id='appearance-a',stats_id='stats-a',passive_variant_id='passive-b'}
context.passive_variants={['passive-b']={icon_hash='2222222222222222'}}
local draws,created={},0
local function vector(...)return {...}end
local e={Vector2=vector,Vector3=vector,Color=vector,IdString64={from_hex=function(v)return v end},
 Application={worlds=function()return {'main','armory'}end,main_world=function()return 'main'end,
 can_get=function(kind,id)return kind=='material' and id=='2222222222222222'end},
 World={create_screen_gui=function()created=created+1;return created end,destroy_gui=function()end},
 Gui={resolution=function()return 1920,1080 end,material=function()return {}end,rect=function()end,text=function()end,
 bitmap=function(_,material,position,size)draws[#draws+1]={material=material,position=position,size=size}end},
 Material={set_scalar=function()end,set_vector2=function()end,set_vector4=function()end,set_texture=function()end}}
local panel=P.new(e)
local sample={kind='armory',anchor={x=100,y=100,w=10,h=700},font='a',material='b',atlas='c',
 variant_section={x=200,y=720,w=600,h=150}}
local view={open=false,tab='appearance',notice='ready',editor=S.editor_view(state,editor,'appearance',context)}
assert(panel:draw(sample,view))
assert(#draws==1 and draws[1].material=='2222222222222222')
local card=panel:variant_cards()[1]
assert(draws[1].position[1]==card.badge.x and draws[1].position[2]==card.badge.y)
assert(card.badge.x>card.x+card.w/2 and card.badge.y>card.y+card.h/2)
assert(panel:hit(card.x+20,card.y+50)==S.variant_action('Mixed'))
assert(panel:capture(550,725) and panel:hit(550,725)=='panel_background')
assert(not panel:capture(1000,500))
local before=created;assert(panel:draw(sample,view));assert(created==before)
context.passive_variants['passive-b'].icon_hash='3333333333333333'
view.editor=S.editor_view(state,editor,'appearance',context)
assert(panel:draw(sample,view));assert(created==before+1)
-- No adapter opt-in keeps the legacy entry, with no overlaid native-grid cards.
sample.variant_section=nil;assert(panel:draw(sample,view));assert(#panel:variant_cards()==0)
local diagnostic=panel:material_diagnostic()
assert(diagnostic.gui_present and diagnostic.material_type=='table' and not diagnostic.void_pointer_cast)
for key in pairs(diagnostic)do
 assert(({gui_present=true,material_type=true,ffi_available=true,void_pointer_cast=true})[key])
end
local binding=panel:test_pointer_binding()
assert(not binding.accepted and type(binding.error)=='string'and #binding.error<=240)
e.Gui.material=function()return require('ffi').new('uint8_t[1]')end
view.notice='diagnostic rebuild';assert(panel:draw(sample,view))
diagnostic=panel:material_diagnostic()
assert(diagnostic.material_type=='cdata' and diagnostic.void_pointer_cast)
local deleted=0
e.Gui.bitmap=function(_,material,position,size)
 assert(type(material)=='cdata'and not require('ffi').istype('void *',material)and size[1]==8 and size[2]==8)
 return 42
end
e.Gui.destroy_bitmap=function(_,primitive)assert(primitive==42);deleted=deleted+1 end
local stages={}
binding=panel:test_pointer_binding(function(stage)stages[#stages+1]=stage end)
assert(binding.accepted and binding.error==nil and deleted==1 and panel:material_diagnostic().gui_present)
assert(table.concat(stages,',')=='begin,before_handle_prepare,before_bitmap,after_bitmap,before_cleanup,after_cleanup')
e.Gui.destroy_bitmap=nil
assert(panel:test_pointer_binding().accepted and not panel:material_diagnostic().gui_present)
panel:clear();assert(not panel:material_diagnostic().gui_present)
''')


def test_borrowed_native_material_is_gated_and_revalidated_before_retention():
    run_lua(FIXTURE + '''
local P=dofile('src/panel.lua')
state.presets['Mixed']={appearance_id='appearance-a',stats_id='stats-a',passive_variant_id='passive-b'}
local allowed,validations,calls,created,destroyed=false,0,0,0,0
local descriptor={material_pointer=0x123450,native_handle_verified=false,uv={0.1,0.2,0.4,0.8},width=138,height=178,
 valid=function()validations=validations+1;return allowed end}
context.appearance_previews={['appearance-a']=descriptor}
local function vector(...)return {...}end
local e={Vector2=vector,Vector3=vector,Color=vector,IdString64={from_hex=function(v)return v end},
 Application={worlds=function()return {'main','armory'}end,main_world=function()return 'main'end},
 World={create_screen_gui=function()created=created+1;return created end,destroy_gui=function()destroyed=destroyed+1 end},
 Gui={resolution=function()return 1920,1080 end,material=function()return {}end,rect=function()end,text=function()end,
 bitmap_uv=function(_,material)assert(material==descriptor.material_handle);calls=calls+1 end},
 Material={set_scalar=function()end,set_vector2=function()end,set_vector4=function()end,set_texture=function()end}}
local panel=P.new(e)
local sample={kind='armory',anchor={x=100,y=100,w=10,h=700},font='a',material='b',atlas='c',
 variant_section={x=200,y=720,w=600,h=150}}
local view={open=false,tab='appearance',notice='ready',editor=S.editor_view(state,editor,'appearance',context)}
assert(panel:draw(sample,view));assert(calls==0 and validations==0)
descriptor.native_handle_verified=true
assert(panel:draw(sample,view));assert(calls==0 and validations==0)
-- Explicit flag alone never enables the unproven raw-address conversion.
descriptor.material_handle=require('ffi').new('uint8_t[1]');descriptor.handle_source='engine_material'
assert(panel:draw(sample,view));assert(calls==0 and validations==1)
allowed=true;assert(panel:draw(sample,view));assert(calls==1 and panel:variant_cards()[1].thumbnail_ready)
local image=panel:variant_cards()[1].image
assert(math.abs(image.w/image.h-138/178)<0.0001)
local before,checked=created,validations
assert(panel:draw(sample,view));assert(created==before and validations>checked and calls==1)
-- Same model/signature but revoked lifetime must destroy the old shape now.
allowed=false;local removed=destroyed
assert(panel:draw(sample,view));assert(destroyed==removed+1 and calls==1)
assert(not panel:variant_cards()[1].thumbnail_ready)
allowed=true;descriptor.uv[4]=2
assert(panel:draw(sample,view));assert(calls==1)
descriptor.uv[4]=0.8;descriptor.material_pointer=0;descriptor.material_handle=nil
assert(panel:draw(sample,view));assert(calls==1)
''')
