-- Loadout-context armor bridge. Reuse the recognized DiverKit Lua preflight and
-- native bindings; no duplicated offsets or independent game-code discovery.
local M={}
local function armor(id)
 assert(type(id)=='string'and id:match('^0x%x%x%x%x%x%x%x%x$'),'Invalid loadout armor ID')
 return 'armor:'..id:sub(3):lower()
end
local function other(snapshot,actor)
 local out={}
 for _,k in ipairs({'primary','pistol','grenade','helmet','cape','title','player_card','booster'})do
  out[#out+1]=tostring(snapshot[k])
 end
 for _,v in ipairs(snapshot.stratagems)do out[#out+1]=tostring(v.enum)..':'..tostring(v.key)end
 for _,v in ipairs({actor.request,actor.current})do
  out[#out+1]=table.concat({v.body_type,v.helmet_id,v.cape_id},':')
 end
 return table.concat(out,'|')
end
function M.new(driver,player,catalog)
 local A,context=driver.apply,driver.context
 local observations=setmetatable({},{__mode='k'})
 local bridge={capabilities={commit_verified=true,cache_layout_verified=true}}
 local function sample()
  assert(not driver.current or driver.current(),'DiverKit interfaces changed')
  local token,info=A.session(context)
  local captured=assert(driver.capture(),'Loadout equipment unavailable')
  local actor,why=player:sample();assert(actor,why)
  assert(info.player==actor.local_player_id,'Loadout player changed')
  assert(#A.profile_differences(context,captured,{armor=true})==0,'Loadout profile is transitioning')
  local request,current=actor.request,actor.current
  local pending=request.body_type~=current.body_type or request.helmet_id~=current.helmet_id or request.cape_id~=current.cape_id
  assert(actor.verify()==true and A.session(context)==token,'Loadout observation changed')
  return {session=tostring(token)..':'..tostring(actor.session_key),other_key=other(captured,actor),
   pending_nonarmor=pending,controller_armor_id=armor(captured.armor),profile_armor_id=armor(captured.armor),
   request_armor_id=actor.request_armor_id,cache_armor_id=actor.cache_armor_id,cache_passive=actor.cache_passive_enum},
   {token=token,info=info,captured=captured,actor=actor}
 end
 function bridge.snapshot()
  local ok,state,proof=pcall(sample);if not ok then return nil,tostring(state)end
  local expected={};for k,v in pairs(state)do expected[k]=v end
  proof.expected=expected;observations[state]=proof;return state
 end
 function bridge.verify(state)
  local proof=observations[state];if not proof then return false end
  for k,v in pairs(proof.expected)do if state[k]~=v then return false end end
  for k,v in pairs(state)do if proof.expected[k]~=v then return false end end
  local ok,fresh=pcall(sample);if not ok then return false end
  for k,v in pairs(proof.expected)do if fresh[k]~=v then return false end end
  return proof.actor.verify()==true
 end
 function bridge.verify_owned(ids)return catalog.verify_owned(ids)==true end
 function bridge.owned_armors()
  local ids={};for id,owned in pairs(catalog.owned)do if owned then ids[#ids+1]=id end end;return ids
 end
 function bridge.commit_owned(id,state)
  local proof=observations[state]
  assert(proof and bridge.verify(state),'Loadout changed before armor commit')
  assert(catalog.owned[id]and catalog.verify_owned({id})==true,'Armor ownership changed')
  local target=driver.model.copy_snapshot(proof.captured)
  target.armor='0x'..assert(id:match('^armor:(%x%x%x%x%x%x%x%x)$'),'Invalid carrier'):upper()
  target.transmog=nil -- Native phase operates only on the ordinary carrier ID.
  local native=A.bind(context)
  local plan=A.preflight(context,native,target,proof.captured,{armor=true},driver.report)
  assert(plan.token==proof.token and #plan.weapons==0 and not plan.stratagem_changed
   and #plan.gear<=1 and #(plan.extras.changes or {})==0,'Unexpected loadout operation')
  assert(bridge.verify(state),'Loadout changed during armor preflight')
  local function check_ownership()
   assert(A.session(context)==proof.token and catalog.verify_owned({id})==true,'Loadout or ownership changed')
   if plan.check_ownership then plan.check_ownership()end
  end
  check_ownership()
  for _,g in ipairs(plan.gear)do
   assert(g.spec.name=='armor'and g.id==tonumber(target.armor:sub(3),16),'Unexpected gear mutation')
   check_ownership()
   native.write_gear(plan.info.payload+g.spec.offset,g.before,g.id)
   native.armor(plan.catalog,plan.info.player,g.id)
  end
  if #plan.gear>0 then
   assert(A.session(context)==proof.token,'Loadout changed during armor selection')
   check_ownership()
   native.commit(plan.info.payload)
   native.refresh(plan.info.card,plan.info.payload,true,plan.info.mode)
  end
  local after,why=bridge.snapshot();assert(after,why)
  assert(after.session==state.session and after.other_key==state.other_key,'Armor commit changed other equipment')
  assert(after.controller_armor_id==id and after.profile_armor_id==id and after.request_armor_id==id,
   'Native loadout armor commit was not confirmed')
  return true
 end
 return bridge
end
return M
