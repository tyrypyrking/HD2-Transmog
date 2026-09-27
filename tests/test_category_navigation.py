"""Main-loop category navigation follows native C/Z selection without equipment writes."""
from test_creator_failure_main import run
from test_ownership_prefix import SETUP

NAV=SETUP+'''
local snapshot=grid.snapshot
nav_group=0;nav_index=0;nav_missing=false
function grid:snapshot(...)
 local s=snapshot(self,...)
 s.logical_selected_group=nav_group;s.logical_selected_index=nav_index
 if not nav_missing then s.widgets={{logical_index=nav_index,bound_owned_kit_id='b'}}end
 return s
end
local factory=VariantSession.new
cancel_previews=0;browses=0;selects=0
VariantSession.new=function(...)
 local s=factory(...)
 s.cancel_preview=function()cancel_previews=cancel_previews+1;return true end
 s.browse=function(_,id,now,index)if id then assert(id=='b'and index==2);browses=browses+1 end;return true end
 s.select=function(_,label)assert(label=='Existing');selects=selects+1;return true end
 return s
end
'''


def test_cz_to_original_and_back_updates_saved_selection_without_saving():
    run('''
advance();assert(flow:view().selected_variant.label=='Existing')
nav_group=1;nav_index=2;advance()
assert(not flow:view().selected_variant and browses==1 and cancel_previews==1)
for i=1,5 do advance()end
assert(browses==1 and save_count==0)
nav_group=0;nav_index=0;advance()
assert(flow:view().selected_variant.label=='Existing'and selects==2 and cancel_previews==2)
assert(save_count==0 and files['transmog.state']==saved_before and session_created==1)
''',automatic=True,setup=NAV)


def test_navigation_waits_for_owned_card_observation_and_apply_completion():
    run('''
advance();nav_group=1;nav_index=2;nav_missing=true
advance();assert(browses==0 and cancel_previews==1 and not flow:view().selected_variant)
nav_missing=false;session_busy=true;advance()
assert(browses==0 and cancel_previews==1)
session_busy=false;advance()
assert(browses==1 and cancel_previews==1 and not flow:view().selected_variant)
assert(save_count==0 and session_created==1)
''',automatic=True,setup=NAV)


def test_departure_drops_unresolved_navigation_before_reentry():
    run('''
advance();nav_group=1;nav_index=2;nav_missing=true;advance()
assert(not flow:view().selected_variant)
sample_mode='departed';advance()
nav_group=0;nav_index=0;nav_missing=false;sample_mode='ready'
for i=1,10 do advance()end
assert(logged_count('runtime.error=')==0)
assert(flow:view().selected_variant.label=='Existing')
assert(browses==0 and save_count==0)
''',automatic=True,setup=NAV)
