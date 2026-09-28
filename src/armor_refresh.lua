-- Optional frame-by-frame native equip coordinator. No addresses, FFI, cache
-- writes, fake item ids, persistence, or menu control live in this module.
-- The bridge owns verified native commit + current local-player observation.
local M={}
local function kit_id(value)
 return type(value)=='string'and value:match('^armor:%x%x%x%x%x%x%x%x$')~=nil
end
local function time_value(value)
 return type(value)=='number'and value==value and value>=0 and value<9007199254740992
end
local function copy_ids(values)
 local result,seen={},{}
 for _,id in ipairs(values or {})do
  assert(kit_id(id),'invalid owned donor identity')
  if not seen[id]then seen[id]=true;result[#result+1]=id end
  assert(#result<=4,'too many refresh donors')
 end
 return result,seen
end
local function same_selection(snapshot,id)
 return snapshot.controller_armor_id==id and snapshot.profile_armor_id==id and snapshot.request_armor_id==id
end
function M.new(bridge,report)
 assert(type(bridge)=='table'and type(bridge.snapshot)=='function'and type(bridge.verify)=='function'
  and type(bridge.verify_owned)=='function'and type(bridge.commit_owned)=='function','verified refresh bridge required')
 report=report or function()end
 local self={phase='idle',needs_recovery=false}
 local plan,deadline,last_now,matched,commits= nil,nil,nil,0,0
 local failure,prepared,preparation_attempted
 local function phase(value)
  self.phase=value;matched=0;report('refresh.phase',value)
 end
 local function snapshot()
  local value,why=bridge.snapshot()
  assert(type(value)=='table',why or 'local player state unavailable')
  assert(type(value.session)=='string'and #value.session>0 and #value.session<=2048,'invalid session evidence')
  assert(type(value.other_key)=='string'and #value.other_key<=8192,'other equipment evidence unavailable')
  for _,key in ipairs({'controller_armor_id','profile_armor_id','request_armor_id'})do
   assert(kit_id(value[key]),'invalid native '..key)
  end
  assert(value.cache_armor_id==nil or kit_id(value.cache_armor_id),'invalid cached armor identity')
  assert(value.cache_passive==nil or type(value.cache_passive)=='number'and value.cache_passive%1==0
   and value.cache_passive>=0 and value.cache_passive<=4294967295,'invalid cached passive')
  assert(value.pending_nonarmor==false,'finish pending native non-armor changes first')
  assert(bridge.verify(value)==true,'native refresh evidence changed')
  return value
 end
 local function guarded(restoring)
  local current=snapshot()
  assert(current.session==plan.session,'local player or Armory session changed')
  assert(current.other_key==plan.other_key,'other native equipment changed')
  for _,key in ipairs({'controller_armor_id','profile_armor_id','request_armor_id'})do
   assert(plan.allowed[current[key]],'native armor changed outside this refresh')
  end
  local donors=restoring and {plan.target_id}or plan.donors
  assert(bridge.verify_owned(donors)==true,'current donor ownership unavailable')
  return current
 end
 local function evidence(status,current)
  return {status=status,target_id=plan and plan.target_id,alternate_id=plan and plan.alternate_id,
   cache_armor_id=current and current.cache_armor_id,cache_passive=current and current.cache_passive,
   commits=commits,visual_verified=false,gameplay_verified=false,needs_recovery=self.needs_recovery,
   reason=failure,preparation_attempted=preparation_attempted==true,target_prepared=prepared==true}
 end
 local function blocked(reason)
  failure=tostring(reason)
  self.needs_recovery=commits>0
  phase(self.needs_recovery and 'blocked'or 'failed')
  report('refresh.failure',failure)
  return self.phase,evidence('native_refresh_not_verified')
 end
 local function commit(id,current,now,next_phase)
  assert(commits<3,'native commit budget exceeded')
  -- Count an attempt before entering native code. An uncertain failure is
  -- never retried automatically, and recovery remains visible to the caller.
  commits=commits+1;self.needs_recovery=true
  assert(bridge.verify(current)==true,'state changed before native commit')
  report('refresh.commit.begin',id)
  local ok,why=bridge.commit_owned(id,current)
  assert(ok==true,why or 'native commit not confirmed')
  report('refresh.commit.returned',id)
  local after=snapshot()
  assert(after.session==plan.session and after.other_key==plan.other_key,'native commit changed protected context')
  assert(after.controller_armor_id==id and after.profile_armor_id==id,'native persistent carrier did not commit')
  phase(next_phase);deadline=now+plan.timeout_ms
 end
 function self:begin(request,now)
  if self.needs_recovery or (self.phase~='idle'and self.phase~='complete'and self.phase~='failed'and self.phase~='cancelled')then
   return nil,'a native refresh is already pending'
  end
  local ok,why=pcall(function()
   assert(time_value(now),'invalid refresh clock')
   assert(bridge.capabilities and bridge.capabilities.commit_verified==true
    and bridge.capabilities.cache_layout_verified==true,'native commit/cache proofs unavailable')
   assert(type(request)=='table'and kit_id(request.target_id),'verified target carrier required')
   assert(type(request.passive_enum)=='number'and request.passive_enum%1==0
    and request.passive_enum>=0 and request.passive_enum<=4294967295,'verified target passive required')
   local timeout=request.timeout_ms or 5000
   assert(time_value(timeout)and timeout>=250 and timeout<=20000,'refresh timeout outside bounds')
   assert(request.prepare_target==nil or type(request.prepare_target)=='function','invalid target preparation hook')
   local _,mutations=copy_ids(request.mutation_ids)
   if request.target_unchanged==true then
    assert(request.prepare_target and next(mutations)and not mutations[request.target_id],
     'unchanged target requires other explicit mutation carriers')
   end
   if request.prepare_target and request.target_unchanged~=true then mutations[request.target_id]=true
   elseif not request.prepare_target then assert(next(mutations)==nil,'carrier mutations require a preparation hook')end
   assert(request.accept_current~=true or request.prepare_target==nil,
    'unchanged equipment cannot include target preparation')
   local current=snapshot()
   assert(current.profile_armor_id==current.request_armor_id,'native committed selection is already transitioning')
   assert(current.cache_armor_id==current.request_armor_id,'native armor cache is already transitioning')
   local donors,seen=copy_ids(request.donor_ids or {request.target_id})
   if not seen[request.target_id]then donors[#donors+1]=request.target_id;seen[request.target_id]=true end
   assert(#donors<=4 and bridge.verify_owned(donors)==true,'current variant donor ownership unavailable')
   local alternate
   local already_current=request.accept_current==true and same_selection(current,request.target_id)
    and current.cache_armor_id==request.target_id and current.cache_passive==request.passive_enum
   local release=current.request_armor_id==request.target_id and not already_current and request.target_unchanged~=true
   if request.prepare_target then
    assert(same_selection(current,current.request_armor_id),'finish pending native armor changes first')
    for _,key in ipairs({'controller_armor_id','profile_armor_id','request_armor_id','cache_armor_id'})do
     if mutations[current[key]]then release=true end
    end
   end
   if release then
    alternate=request.alternate_id or(request.target_unchanged==true and request.target_id or nil)
    if not alternate then
     assert(type(bridge.owned_armors)=='function','owned alternate armor list unavailable')
     local owned=bridge.owned_armors();assert(type(owned)=='table'and #owned<=2048,'owned alternate bounds rejected')
     local sorted={};for _,id in ipairs(owned)do assert(kit_id(id),'invalid alternate identity');sorted[#sorted+1]=id end
     table.sort(sorted)
     for _,id in ipairs(sorted)do if id~=request.target_id and not mutations[id]then alternate=id;break end end
    end
    assert(kit_id(alternate)and(alternate~=request.target_id or request.target_unchanged==true),
     'a different owned armor is required to refresh this carrier')
    assert(not mutations[alternate],'alternate armor is a carrier that needs rewriting')
    assert(bridge.verify_owned({alternate})==true,'alternate armor is not currently owned')
    if not seen[alternate]then donors[#donors+1]=alternate end
    assert(#donors<=4,'too many refresh donors')
   end
   plan={target_id=request.target_id,passive_enum=request.passive_enum,alternate_id=alternate,timeout_ms=timeout,started_at=now,
    prepare_target=request.prepare_target,mutations=mutations,
    donors=donors,session=current.session,other_key=current.other_key,
    allowed={[current.request_armor_id]=true,[current.controller_armor_id]=true,[request.target_id]=true}}
   if alternate then plan.allowed[alternate]=true end
   last_now,deadline,commits,failure=nil,nil,0,nil;prepared=false;preparation_attempted=false;self.needs_recovery=false
   phase(already_current and 'wait_target'or alternate and 'commit_alternate'or 'commit_target')
   if already_current then deadline=now+timeout end
  end)
  if not ok then return nil,tostring(why)end
  return true,evidence('native_refresh_prepared')
 end
 function self:step(now)
  if not plan or self.phase=='complete'or self.phase=='failed'or self.phase=='blocked'or self.phase=='cancelled'then
   return self.phase,plan and evidence('native_refresh_inactive')or nil
  end
  if not time_value(now)or now<plan.started_at or last_now and now<last_now then return blocked('refresh clock moved backwards')end
  if last_now==now then return self.phase end -- Never perform two commits in one tick.
  last_now=now
  local ok,current=pcall(guarded,self.phase=='commit_restore'or self.phase=='wait_restore')
  if not ok then return blocked(current)end
  local operation,why=pcall(function()
   if self.phase=='commit_alternate'then
    commit(plan.alternate_id,current,now,'wait_alternate')
   elseif self.phase=='commit_target'then
    if plan.prepare_target and not prepared then
     -- A live actor can still consume the old carrier while its replacement
     -- streams. Do not restore or compose any affected kit until the request
     -- AND cache have left it. Cancellation/timeout restoration skips this.
     assert(same_selection(current,current.request_armor_id)and current.cache_armor_id==current.request_armor_id,
      'armor is still transitioning before target preparation')
     for _,key in ipairs({'controller_armor_id','profile_armor_id','request_armor_id','cache_armor_id'})do
      assert(not plan.mutations[current[key]],'affected carrier is still in use before target preparation')
     end
     assert(not preparation_attempted,'target preparation cannot be replayed')
     preparation_attempted=true;report('refresh.prepare.begin',plan.target_id)
     local done,reason=plan.prepare_target()
     assert(done==true,reason or 'target preparation failed')
     prepared=true;report('refresh.prepare.end',plan.target_id)
     -- Preparation is allowed to alter kit data, never the equipment context.
     assert(bridge.verify(current)==true,'equipment changed during target preparation')
     current=guarded(false)
    end
    commit(plan.target_id,current,now,'wait_target')
   elseif self.phase=='commit_restore'then
    commit(plan.target_id,current,now,'wait_restore')
   elseif self.phase=='wait_alternate'then
    if same_selection(current,plan.alternate_id)and current.cache_armor_id==plan.alternate_id then matched=matched+1 else matched=0 end
    if matched>=2 then phase('commit_target')
    elseif now>=deadline then failure='alternate cache did not advance while Armory was open';phase('commit_restore')end
   elseif self.phase=='wait_target'then
    if same_selection(current,plan.target_id)and current.cache_armor_id==plan.target_id and current.cache_passive==plan.passive_enum then
     matched=matched+1
    else matched=0 end
    if matched>=2 then
     self.needs_recovery=false;phase('complete')
    elseif now>=deadline then
     failure='target armor/passive cache did not verify'
     if same_selection(current,plan.target_id)then self.needs_recovery=false;phase('failed')else phase('commit_restore')end
    end
   elseif self.phase=='wait_restore'then
    if same_selection(current,plan.target_id)and current.cache_armor_id==plan.target_id then matched=matched+1 else matched=0 end
    if matched>=2 then self.needs_recovery=false;phase(plan.cancelled and 'cancelled'or 'failed')
    elseif now>=deadline then
     self.needs_recovery=not same_selection(current,plan.target_id)
     phase(self.needs_recovery and 'blocked'or 'failed')
    end
   end
  end)
  if not operation then return blocked(why)end
  local status=self.phase=='complete'and 'native_armor_and_passive_cache_verified'
   or self.phase=='failed'and 'target_committed_refresh_unverified'
   or self.phase=='cancelled'and 'refresh_cancelled_target_restored'or 'native_refresh_pending'
  return self.phase,evidence(status,current)
 end
 function self:cancel()
  if not plan then return true end
  if self.phase=='complete'or self.phase=='failed'or self.phase=='cancelled'then return true end
  failure='refresh cancelled; return to the selected carrier'
  plan.cancelled=true
  if commits==0 then phase('cancelled');return true end
  if self.phase=='blocked'then return nil,'native recovery needs fresh verified context'end
  phase('commit_restore');return true
 end
 function self:recover_target()
  if not plan or not self.needs_recovery then return nil,'no pending native recovery'end
  if commits>=3 then return nil,'native commit budget exhausted; use the native armor controls'end
  local ok,why=pcall(guarded,true)
  if not ok then return nil,tostring(why)end
  phase('commit_restore');return true
 end
 function self:status()
  local status=self.phase=='complete'and 'native_armor_and_passive_cache_verified'
   or self.phase=='failed'and 'target_committed_refresh_unverified'
   or self.phase=='blocked'and 'native_refresh_needs_recovery'
   or self.phase=='cancelled'and 'refresh_cancelled'or 'native_refresh_pending'
  return self.phase,plan and evidence(status)or nil
 end
 return self
end
return M
