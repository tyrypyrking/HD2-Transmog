"""Release boundaries: native prefix capacity and save-time capacity changes."""
from test_native_grid_presentation import run as run_presentation
from test_variant_wizard import FIXTURE as WIZARD_FIXTURE, run_lua


CARDS = r'''
local function saved_cards(count,create)
 local list={}
 for i=1,count do list[#list+1]={key='saved:'..i,kind='variant',kit_id='armor:00000001'}end
 if create then list[#list+1]={key='create',kind='create',kit_id='armor:00000001'}end
 return list
end
'''


def test_thirty_two_saved_variants_and_creator_construct_successfully():
    run_presentation(CARDS + r'''
local result=controller:attempt(saved_cards(32,true))
assert(result.phase=='active',result.error)
assert(result.custom_count==33 and current.item_count==126)
assert(counts.clear==1 and counts.append==126)
''')


def test_exact_256_native_items_construct_in_both_menus():
    for allow_create in (True, False):
        run_presentation(CARDS + (
            "local allow_create=" + str(allow_create).lower() + "\n"
        ) + r'''
local C=dofile('src/variant_cards.lua')
controller=P.new(bridge,{allow_create=allow_create})
local limit=C.capacity(source.item_count,allow_create)
local result=controller:attempt(saved_cards(limit,allow_create))
assert(result.phase=='active',result.error)
assert(current.item_count==256 and counts.append==256)
assert(current.row_count<=128)
''')


def test_native_item_overflow_is_rejected_before_any_mutation():
    for allow_create in (True, False):
        run_presentation(CARDS + (
            "local allow_create=" + str(allow_create).lower() + "\n"
        ) + r'''
local C=dofile('src/variant_cards.lua')
controller=P.new(bridge,{allow_create=allow_create})
local result=controller:attempt(saved_cards(C.capacity(source.item_count,allow_create)+1,allow_create))
assert(result.phase=='blocked'and result.error:find('custom item capacity rejected',1,true))
assert(counts.begin==0 and counts.clear==0 and counts.append==0 and counts.finish==0)
assert(current.item_count==source.item_count)
''')


def test_reserving_all_known_armor_leaves_room_for_later_unlocks():
    run_presentation(CARDS + r'''
local C=dofile('src/variant_cards.lua')
local known_armors=135
local limit=C.capacity(math.max(source.item_count,known_armors),true)
assert(limit==120)
-- All known armor can become owned without exceeding the fixed item array.
assert(known_armors+limit+1==256)
local result=controller:attempt(saved_cards(limit,true))
assert(result.phase=='active',result.error)
assert(current.item_count==214)
''')


def test_wizard_capacity_disables_open_and_blocks_create_without_state_changes():
    run_lua(WIZARD_FIXTURE + r'''
local before=S.encode(state)
context.variant_capacity=1
local view=wizard:view(state,context)
assert(not view.section.tiles[#view.section.tiles].enabled)
assert(not act('open'))
assert(S.encode(state)==before)
context.variant_capacity=2
choose()
assert(wizard:view(state,context).can_create)
context.variant_capacity=1
assert(not wizard:view(state,context).can_create)
assert(not act('create'))
assert(S.encode(state)==before)
''')


def test_wizard_rechecks_shrinking_capacity_before_persisting_transaction():
    run_lua(WIZARD_FIXTURE + r'''
context.variant_capacity=2
local before=S.encode(state)
choose()
local ok,why,tx=act('create');assert(ok and tx,why)
assert(wizard:validate_transaction(tx,state,context))
context.variant_capacity=1
local valid,reason=wizard:validate_transaction(tx,state,context)
assert(not valid and reason:find('limit',1,true))
assert(S.encode(state)==before)
context.variant_capacity=2
assert(wizard:validate_transaction(tx,state,context))
''')


def test_group_limit_rejects_before_native_construction():
    from test_native_grid_presentation import run
    run(r'''
source.groups={};source.rows={};source.content=32*246
for i=1,93 do
 source.entries[i].group_key=i<=90 and math.floor((i-1)/3)or(i<=92 and 30 or 31)
end
for g=0,31 do
 local first=g<31 and g*3 or 92
 source.groups[g+1]={key=g,first_row=g,first_item=first}
 source.rows[g+1]={count=g<30 and 3 or(g==30 and 2 or 1),first_item=first,height=246}
end
source.group_count=32;source.row_count=32
local result=controller:attempt(cards)
assert(result.phase=='blocked' and result.error:find('readback capacity',1,true))
assert(counts.begin==0 and counts.clear==0)
''')
