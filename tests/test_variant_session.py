"""Browsing is read-only; explicit Apply owns kit composition and native equip."""
from test_runtime import run_lua

FIXTURE = r'''
local Session=dofile('src/variant_session.lua')
local Refresh=dofile('src/armor_refresh.lua')
local A,B,C='armor:00000001','armor:00000002','armor:00000003'
local request={appearance_id=A,stats_id='native-stats:00000002',passive_variant_id='perk-a'}
local other={appearance_id=C,stats_id='native-stats:00000002',passive_variant_id='perk-b'}
local catalog={owned={[A]=true,[B]=true,[C]=true},context={passive_variants={['perk-a']={enum=1},['perk-b']={enum=7}}},
 catalog={[A]={appearance_id=A,stats_id='native-stats:00000001',passive_variant_id='perk-b'},
 [B]={appearance_id=B,stats_id='native-stats:00000002',passive_variant_id='perk-b'},
 [C]={appearance_id=C,stats_id='native-stats:00000003',passive_variant_id='perk-a'}}}
local live={session='armory:player1',other_key='helmet|cape|weapons',pending_nonarmor=false,
 controller_armor_id=A,profile_armor_id=A,request_armor_id=A,cache_armor_id=A,cache_passive=0}
local detail=A
local commits,previews,logs={}, {}, {}
local resets,applies,plans=0,0,0
local active_request,fail_preview,fail_plan,fail_reset,fail_commit,ownership=nil,false,false,false,false,true
local function copy(v)local out={};for k,x in pairs(v)do out[k]=x end;return out end
local host={preview_timing={selection_delay_ms=0,settle_ms=0,stable_samples=1},catalog=function()return catalog end,
 target_for=function(r)return 'armor:'..r.stats_id:match(':(.+)$')end,
 detail_state=function()return {kit_id=detail}end,
 player=function()return {request_armor_id=live.request_armor_id,cache_armor_id=live.cache_armor_id}end,
 report=function(k,v)logs[#logs+1]={key=k,value=v}end}
function host.new_patch()
 local patch={active=false}
 function patch:plan(_,r)
  plans=plans+1
  if fail_plan==true or fail_plan==r.appearance_id then return nil,'recipe unavailable'end
  return {source_id=r.appearance_id,target_id='armor:'..r.stats_id:match(':(.+)$'),
   passive_source_id=C,request=copy(r)}
 end
 function patch:apply(plan)
  applies=applies+1;self.active=true;active_request=copy(plan.request);return true
 end
 function patch:reset()
  if fail_reset then return nil,'patch restoration conflict'end
  resets=resets+1;self.active=false;active_request=nil;return true
 end
 function patch:is_active()return self.active end
 return patch
end
function host.preview_variant(r,suppress)
 previews[#previews+1]={id=r.appearance_id,request=copy(r),suppress=suppress}
 if fail_preview then return nil,'native preview changed'end
 detail=r.appearance_id;return true
end
local bridge={capabilities={commit_verified=true,cache_layout_verified=true}}
function bridge.snapshot()return copy(live)end
function bridge.verify(snapshot)
 for k,v in pairs(snapshot)do if live[k]~=v then return false end end;return true
end
function bridge.verify_owned(ids)
 if not ownership then return false end
 for _,id in ipairs(ids)do if not catalog.owned[id]then return false end end;return true
end
function bridge.owned_armors()return {A,B,C}end
function bridge.commit_owned(id,snapshot)
 assert(bridge.verify(snapshot));commits[#commits+1]=id;live.controller_armor_id=id
 if fail_commit then return nil,'native commit uncertain'end
 live.profile_armor_id=id;live.request_armor_id=id;return true
end
function host.new_refresh()return Refresh.new(bridge)end
local s=Session.new(host)
local function ready(now,label,r)
 assert(s:select(label or 'Saved',r or request,now));s:step(now);s:step(now+1)
 assert(s:view().can_apply)
end
local function equip(now)
 assert(s:apply(now));s:step(now)
 live.cache_armor_id=B;live.cache_passive=1
 s:step(now+1);s:step(now+2)
 assert(s.phase=='equipped'and not s:busy())
end
local function count(key)local n=0;for _,event in ipairs(logs)do if event.key==key then n=n+1 end end;return n end
'''


def test_select_uses_original_appearance_and_native_detail_request_without_live_patch():
    run_lua(FIXTURE + '''
ready(0)
assert(#commits==0 and #previews==1 and previews[1].id==A and previews[1].suppress)
assert(previews[1].request.stats_id==request.stats_id and previews[1].request.passive_variant_id=='perk-a')
assert(plans==0 and applies==0 and resets==0 and not s:is_active())
assert(s:view().native_details and s:view().can_apply and live.controller_armor_id==A and live.request_armor_id==A)
request.appearance_id=C;assert(previews[1].request.appearance_id==A)
assert(s:leave()and not s:is_active()and plans==0 and resets==0)
''')


def test_same_appearance_different_stats_or_perk_never_uses_an_alternate_preview():
    run_lua(FIXTURE + '''
ready(0)
local changed=copy(request);changed.passive_variant_id='perk-b'
ready(2,'Changed',changed)
assert(#previews==2 and previews[1].id==A and previews[2].id==A)
assert(previews[2].request.passive_variant_id=='perk-b'and #commits==0)
assert(plans==0 and applies==0 and resets==0)
''')


def test_explicit_apply_preflights_then_composes_and_waits_for_exact_cache():
    run_lua(FIXTURE + '''
ready(0);assert(s:apply(2)and #commits==0 and s:busy())
assert(plans==0 and applies==0 and not s:is_active())
assert(not s:verify_composition(A)and not s:select('Other',other,2)and not s:browse())
s:step(2);assert(#commits==1 and commits[1]==B and s.phase=='applying')
assert(plans==1 and applies==1 and active_request.appearance_id==A and s:verify_composition(B))
live.cache_armor_id=B;live.cache_passive=7;s:step(3);s:step(4);assert(s.phase=='applying')
live.cache_passive=1;s:step(5);s:step(6)
assert(s.phase=='equipped'and not s:busy()and #commits==1)
assert(#previews==1 and previews[1].id==A)
assert(count('variant.equipped')==1)
''')


def test_repeated_saved_browsing_preserves_applied_patch_and_never_replans():
    run_lua(FIXTURE + '''
ready(0);equip(2)
local before_plans,before_applies,before_resets=plans,applies,resets
for i=1,100 do ready(10+i*2,i%2==0 and 'First'or 'Other',i%2==0 and request or other)end
assert(plans==before_plans and applies==before_applies and resets==before_resets)
assert(#commits==1 and active_request.appearance_id==A and s:verify_composition(B))
assert(s:leave()and active_request.appearance_id==A and resets==before_resets)
''')


def test_original_same_carrier_keeps_custom_data_until_explicit_apply():
    run_lua(FIXTURE + '''
ready(0);equip(2)
assert(s:browse(B,10)and s:is_active()and s:view().native_override)
assert(active_request.appearance_id==A and s:view().native_override_id==B)
s:step(10);s:step(11)
assert(s:view().can_apply and previews[#previews].id==B and #commits==1)
assert(s:apply(12)and s:is_active()and active_request.appearance_id==A)
s:step(12);assert(commits[2]==A)
assert(s:is_active()and active_request.appearance_id==A)
live.cache_armor_id=A;live.cache_passive=0;s:step(13);s:step(14);s:step(15)
assert(commits[3]==B and not s:is_active()and active_request==nil)
live.cache_armor_id=B;live.cache_passive=1;s:step(16);s:step(17);assert(s.phase=='applying')
live.cache_passive=7;s:step(18);s:step(19)
assert(s.phase=='equipped'and not s:has_committed()and not s:is_active())
assert(s:leave()and active_request==nil and #commits==3)
''')


def test_original_preview_cancel_and_native_different_carrier_have_distinct_leave_behavior():
    run_lua(FIXTURE + '''
ready(0);equip(2);local before=resets
assert(s:browse(B,10));s:step(10);s:step(11);assert(s:leave())
assert(s:is_active()and active_request.appearance_id==A and resets==before)
assert(s:browse(C,20)and not s:view().native_override)
live.controller_armor_id=C;live.profile_armor_id=C;live.request_armor_id=C;live.cache_armor_id=C
assert(s:leave()and not s:is_active()and not s:has_committed()and resets==before+1)
''')


def test_apply_preflight_failures_have_not_touched_previous_applied_data():
    run_lua(FIXTURE + '''
ready(0);equip(2);ready(10,'Other',other)
local before_plans,before_resets=plans,resets
ownership=false;assert(not s:apply(12)and not s:busy())
assert(plans==before_plans and resets==before_resets and active_request.appearance_id==A)
ownership=true;host.new_refresh=function()return nil,'native proof unavailable'end
assert(not s:apply(13)and s:view().apply_notice=='native proof unavailable')
assert(plans==before_plans and resets==before_resets and #commits==1)
''')


def test_failed_explicit_new_composition_restores_previous_applied_request():
    run_lua(FIXTURE + '''
ready(0);equip(2);assert(s:leave());fail_plan=C
ready(10,'Unavailable',other)
assert(s:apply(12)and s:busy())
s:step(12);assert(commits[2]==A and active_request.appearance_id==A)
live.cache_armor_id=A;s:step(13);s:step(14);s:step(15)
assert(s.phase=='apply_failed'and s:busy())
assert(active_request.appearance_id==A and s:has_committed()and s:verify_composition(B))
assert(#commits==2 and s:leave())
''')


def test_close_before_first_native_commit_leaves_prior_data_untouched():
    run_lua(FIXTURE + '''
ready(0);assert(s:apply(2)and not s:is_active());assert(s:leave())
assert(#commits==0 and not s:is_active()and not s:busy())
assert(plans==0 and applies==0 and resets==0)
s:step(3);assert(#commits==0)
''')
    run_lua(FIXTURE + '''
ready(0);equip(2);ready(10,'Other',other)
local before=resets
assert(s:apply(12)and active_request.appearance_id==A)
assert(s:leave()and active_request.appearance_id==A and #commits==1)
assert(resets==before)
''')


def test_uncertain_commit_retains_data_without_repeat_commits_logs_or_leave_resets():
    run_lua(FIXTURE + '''
ready(0);assert(s:apply(2));fail_commit=true;s:step(2)
assert(s.phase=='apply_failed'and s:busy()and #commits==1 and s:is_active())
for now=3,100 do s:step(now)end
assert(#commits==1 and count('variant.apply_failed')==1)
assert(s:leave()and s:is_active()and not s:busy())
for now=101,200 do assert(s:leave()and s:is_active())end
assert(#commits==1 and not s:view().native_details)
''')


def test_cache_failure_reports_no_success_and_keeps_observed_target_composition():
    run_lua(FIXTURE + '''
ready(0);assert(s:apply(2));s:step(2);s:step(5002)
assert(s.phase=='apply_failed'and not s:busy()and count('variant.equipped')==0)
assert(s:view().apply_notice:find('cache')and not s:view().native_details)
assert(s:leave()and s:is_active()and #commits==1)
''')


def test_preview_failure_never_mutates_an_applied_composition():
    run_lua(FIXTURE + '''
ready(0);equip(2);local before=resets
assert(s:select('Other',other,10));fail_preview=true;s:step(10)
assert(s.phase=='preview_failed'and not s:apply(11))
assert(active_request.appearance_id==A and resets==before and #commits==1)
assert(s:leave()and active_request.appearance_id==A and resets==before)
''')


def test_ownership_metadata_and_apply_notices_are_checked_without_live_plans():
    run_lua(FIXTURE + '''
assert(not s:apply(0)and s:view().apply_notice:find('preview'))
catalog.owned[C]=false
assert(not s:select('Saved',request,0)and plans==0 and #previews==0)
catalog.owned[C]=true;ready(0);catalog.context.passive_variants['perk-a']=nil
assert(not s:apply(2)and s:view().apply_notice:find('passive')and plans==0)
''')


def test_production_timing_coalesces_clicks_and_requires_stable_distinct_observations():
    run_lua(FIXTURE + '''
host.preview_timing=nil;s=Session.new(host)
assert(s:select('First',request,0));assert(s:select('Latest',other,30))
s:step(209);assert(#previews==0 and plans==0 and not s:view().can_apply)
s:step(210);assert(#previews==1 and previews[1].id==C and not s:view().can_apply)
s:step(210);s:step(359);assert(not s:view().can_apply)
s:step(360);assert(s:view().can_apply and #previews==1 and plans==0)
assert(count('variant.preview.begin')==1 and count('variant.preview.end')==1)
''')


def test_inflight_selection_bursts_wait_and_only_preview_latest_request():
    run_lua(FIXTURE + '''
host.preview_timing=nil;s=Session.new(host)
assert(s:select('First',request,0));s:step(180)
assert(#previews==1)
for now=181,220 do assert(s:select('Burst '..now,now%2==0 and other or request,now));s:step(now)end
assert(#previews==1 and plans==0 and not s:view().can_apply)
s:step(330);assert(#previews==1 and not s:view().can_apply)
s:step(480);assert(#previews==2 and previews[2].id==C)
s:step(630);assert(s:view().can_apply and #previews==2 and plans==0 and applies==0)
''')


def test_native_focus_mismatch_never_reasserts_preview_every_frame():
    run_lua(FIXTURE + '''
ready(0);detail=C
for now=2,100 do s:step(now)end
assert(s.phase=='preview_failed'and #previews==1 and count('variant.preview_failed')==1)
assert(plans==0 and applies==0 and #commits==0)
''')


def test_equipped_cache_success_does_not_restart_native_preview():
    run_lua(FIXTURE + '''
ready(0);assert(s:apply(2));s:step(2)
live.cache_armor_id=B;live.cache_passive=1;s:step(3);fail_preview=true;s:step(4)
assert(s.phase=='equipped'and s:view().native_details and s:has_committed())
assert(s:is_active()and #commits==1 and count('variant.equipped')==1)
assert(#previews==1 and s:view().apply_notice==nil and not s:view().can_apply)
''')


def test_ready_requires_model_stats_and_passive_bindings_to_remain_coherent():
    run_lua(FIXTURE+'''
local stats,perk=88,88
host.preview_variant=function(r)
 detail=r.appearance_id;return {stats_offer_id=88,passive_offer_id=88}
end
host.detail_state=function()return {kit_id=detail,stats_offer_id=stats,passive_offer_id=perk}end
ready(0);assert(s:view().can_apply)
perk=77;s:step(2)
assert(not s:view().can_apply and not s:view().native_details and s.phase=='preview_failed')
assert(not s:apply(3)and plans==0 and applies==0 and #commits==0)
''')


def test_original_override_keeps_exact_vanilla_index_across_deferred_preview():
    run_lua(FIXTURE+'''
ready(0);equip(2)
local index
host.preview_variant=function(r,requires,label,at)index=at;assert(label==nil);detail=r.appearance_id;return true end
assert(s:browse(B,10,19));s:step(10);s:step(11)
assert(index==19 and s:view().native_override and s:view().can_apply)
''')


def test_pristine_vanilla_card_uses_controlled_apply_and_restores_its_exact_index():
    run_lua(FIXTURE+'''
local focused,restored,widgets=12,0,0
host.restore_focus=function(id,index)
 assert(id==C and index==12);focused=index;restored=restored+1;return true
end
host.refresh_widgets=function(r,label,index)
 assert(r.appearance_id==C and label==nil and index==12);widgets=widgets+1;return true
end
assert(s:browse(C,0,12));s:step(0);s:step(1)
assert(s:view().native_override and s:view().native_override_id==C and s:view().can_apply)
assert(s:apply(2));s:step(2)
assert(#commits==1 and commits[1]==C and plans==0 and applies==0 and resets==0)
focused=0 -- Simulated native same-offer focus side effect during equipment update.
live.cache_armor_id=C;live.cache_passive=1;s:step(3);s:step(4)
assert(s.phase=='equipped'and restored==1 and focused==12 and widgets==1)
assert(not s:has_committed()and not s:is_active())
''')


def test_pristine_equipped_vanilla_apply_does_not_switch_armor_or_write_composition():
    run_lua(FIXTURE+'''
live.cache_passive=7
assert(s:browse(A,0,12));s:step(0);s:step(1)
assert(s:view().can_apply and s:apply(2));s:step(2);s:step(3)
assert(s.phase=='equipped'and #commits==0 and plans==0 and applies==0 and resets==0)
''')


def test_unrepresentable_variant_shows_reason_and_never_enables_apply():
    run_lua(FIXTURE+'''
host.validate_composition=function()return nil,'Unsupported part layout'end
assert(s:select('Saved',request,0));s:step(0);s:step(1)
assert(s:view().native_details and not s:view().can_apply)
assert(s:view().apply_notice=='Unsupported part layout')
assert(not s:apply(2)and #commits==0 and applies==0)
''')


def test_category_navigation_cancels_only_preview_and_preserves_applied_armor():
    run_lua(FIXTURE + '''
ready(0);equip(2)
local before=active_request;local old_commits=#commits;local old_resets=resets
host.preview_timing={selection_delay_ms=180,settle_ms=150,stable_samples=2}
assert(s:select('Another',other,10))
assert(s:cancel_preview())
assert(s.phase=='idle'and s:is_active()and active_request==before)
s:step(10000)
assert(#commits==old_commits and resets==old_resets)
assert(not s:view().can_apply and not s:view().apply_pending)
ready(10001,'New',other);assert(s:apply(10003))
assert(s:busy()and not s:cancel_preview(),'navigation cancelled equipment work')
''')


def test_native_feedback_follows_verified_cache_completion_once_and_is_not_preview():
    run_lua(FIXTURE+r'''
local feedback=0
host.equipped_feedback=function(r)
 assert(r.appearance_id==request.appearance_id and live.cache_armor_id==B and live.cache_passive==1)
 feedback=feedback+1;return {status='native_equipped_feedback_verified'}
end
ready(0);assert(feedback==0);equip(10);assert(feedback==1)
for i=20,30 do s:step(i)end
assert(feedback==1 and #commits==1)
''')


def test_feedback_failure_does_not_replay_a_completed_equipment_transaction():
    run_lua(FIXTURE+r'''
local feedback=0
host.equipped_feedback=function()feedback=feedback+1;error('feedback proof changed')end
ready(0);equip(10)
for i=20,30 do s:step(i)end
assert(feedback==1 and #commits==1 and s.phase=='equipped'and not s:busy())
local found=false;for _,line in ipairs(logs)do if line.key=='variant.feedback_failed'then found=true end end
assert(found)
''')


def test_background_restore_reuses_refresh_and_patch_without_ui_or_feedback():
    run_lua(FIXTURE+r'''
local persisted=0
host.preview_variant=function()error('startup must not open or preview UI')end
host.refresh_widgets=function()error('startup must not refresh menu widgets')end
host.equipped_feedback=function()error('startup must not play user Equip feedback')end
host.before_apply=function(background)assert(background);return true end
host.persist_equipped=function(label,r)assert(label=='Saved'and r.stats_id==request.stats_id);persisted=persisted+1;return true end
live.controller_armor_id=B;live.profile_armor_id=B;live.request_armor_id=B;live.cache_armor_id=B
assert(s:restore('Saved',request,0)and s:restoring())
for t=1,15 do
 s:step(t);live.cache_armor_id=live.request_armor_id;live.cache_passive=live.request_armor_id==B and 1 or 7
end
assert(s.restore_status=='complete'and not s:restoring()and not s:busy()and s:is_active())
assert(#commits==2 and committed==nil and persisted==1 and s:has_committed())
assert(s:view().native_details==false and s.phase=='idle')
''')


def test_unknown_startup_definition_and_durable_clear_failure_make_no_native_changes():
    run_lua(FIXTURE+r'''
local broken={appearance_id=A,stats_id='missing',passive_variant_id='perk-a'}
assert(not s:restore('Missing',broken,0)and #commits==0 and applies==0)
host.before_apply=function()return nil,'cannot clear startup intent'end
assert(not s:restore('Saved',request,0))
assert(#commits==0 and applies==0 and not s:busy())
''')


def test_failed_background_restore_does_not_lock_the_armory_or_retry_automatically():
    run_lua(FIXTURE+r'''
live.controller_armor_id=B;live.profile_armor_id=B;live.request_armor_id=B;live.cache_armor_id=B
assert(s:restore('Saved',request,0));fail_commit=true;s:step(1)
assert(s.restore_status=='failed'and not s:restoring()and not s:busy())
local count=#commits
for t=2,20 do s:step(t)end
assert(#commits==count and applies==0)
''')


def test_reopening_restored_variant_recognizes_verified_equipped_composition_without_reapply():
    run_lua(FIXTURE+r'''
host.player=function()return {request_armor_id=live.request_armor_id,cache_armor_id=live.cache_armor_id,cache_passive_enum=live.cache_passive}end
ready(0);equip(10);assert(s:leave())
local count=#commits
assert(s:select('Saved',request,20));s:step(20);s:step(21)
assert(s.phase=='equipped'and not s:view().can_apply and #commits==count)
assert(previews[#previews].suppress==false)
''')


def test_failed_equipped_record_save_does_not_repeat_successful_native_commits():
    run_lua(FIXTURE+r'''
local saves=0
host.before_apply=function()return true end
host.persist_equipped=function()saves=saves+1;return nil,'disk unavailable'end
ready(0);equip(10)
for t=20,30 do s:step(t)end
assert(saves==1 and #commits==1 and s.phase=='equipped')
local found=false;for _,line in ipairs(logs)do if line.key=='variant.persistence_failed'then found=true end end
assert(found)
''')


def test_native_base_stats_proof_requires_the_exact_active_donor():
    run_lua(FIXTURE+r'''
ready(0);equip(2)
assert(s:verify_base_stats(B,request.stats_id))
assert(not s:verify_base_stats(A,request.stats_id))
assert(not s:verify_base_stats(B,'native-stats:00000003'))
''')
