"""Saved names stay lossless while native card identities remain bounded."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(code):
    result = subprocess.run(
        ['luajit', '-'], input="local C=dofile('src/variant_cards.lua')\n" + code,
        text=True, capture_output=True, cwd=ROOT, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_long_utf8_labels_and_duplicate_looks_keep_distinct_bounded_identities():
    run('''
local name=string.rep('Б',128)
local request={appearance_id='armor:one',stats_id='stats:one',passive_variant_id='passive:one'}
local presets={[name]=request,Alpha=request}
local cards,why=C.build(presets,{['armor:one']={owned=true}},true,'armor:one')
assert(cards,why);assert(#cards==3)
assert(cards[1].label=='Alpha'and cards[2].label==name)
assert(cards[1].key=='saved:1'and cards[2].key=='saved:2')
assert(cards[1].kit_id==cards[2].kit_id and cards[2].request==request)
assert(cards[3].kind=='create'and cards[3].label=='+')
assert(#name==256 and presets[name]==request)
''')


def test_missing_looks_are_skipped_without_mutating_saved_state_or_label_ordinals():
    run('''
local presets={Alpha={appearance_id='missing'},Beta={appearance_id='owned'}}
local cards=assert(C.build(presets,{owned=true},false))
assert(#cards==1 and cards[1].label=='Beta'and cards[1].key=='saved:2')
assert(presets.Alpha.appearance_id=='missing')
local restored=assert(C.build(presets,{owned=true,missing=true},false))
assert(#restored==2 and restored[2].key==cards[1].key)
''')


def test_empty_saved_lists_and_creation_donor_validation():
    run('''
local cards=assert(C.build({}, {},false));assert(#cards==0)
cards=assert(C.build({}, {owned=true},true,'owned'))
assert(#cards==1 and cards[1].key=='create')
assert(not C.build({}, {},true,'missing'))
assert(not C.build({}, {owned=true},true,nil))
assert(not C.build(nil,{},false))
assert(not C.build({Bad=false},{},false))
''')


def test_capacity_reserves_original_items_and_armory_creator_at_boundaries():
    run('''
assert(C.capacity(93,true)==162 and C.capacity(93,false)==163)
assert(C.capacity(1,true)==254 and C.capacity(1,false)==255)
assert(C.capacity(255,true)==0 and C.capacity(255,false)==1)
assert(C.capacity(256,true)==0 and C.capacity(256,false)==0)
for _,invalid in ipairs({0,-1,257,1.5,'93',math.huge,0/0})do
 assert(C.capacity(invalid,true)==0)
end
assert(C.capacity(nil,true)==0)
''')


def test_storage_limit_keeps_all_valid_presets_for_caller_capacity_policy():
    run('''
local presets={}
for i=1,256 do presets[string.format('Variant %03d',i)]={appearance_id='owned'}end
local cards=assert(C.build(presets,{owned=true},false))
assert(#cards==256 and cards[256].key=='saved:256')
presets.Extra={appearance_id='owned'}
assert(not C.build(presets,{owned=true},false))
''')
