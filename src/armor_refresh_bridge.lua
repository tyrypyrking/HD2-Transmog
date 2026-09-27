-- Join independently verified Armory commit and player-cache observations.
-- Native writes and observation layouts remain in their existing adapters.
local M={}
function M.new(grid,player,catalog)
 local caps=grid:commit_capabilities()
 if not(caps and caps.commit_verified)then return nil,'Native equipment commit is unavailable.'end
 local first,why=player:sample();if not first then return nil,why end
 local observations=setmetatable({},{__mode='k'})
 local bridge={capabilities={commit_verified=true,cache_layout_verified=true}}
 function bridge.snapshot()
  local native,reason=grid:commit_snapshot(catalog);if not native then return nil,reason end
  local actor,error=player:sample();if not actor then return nil,error end
  if native.local_player_id~=actor.local_player_id then return nil,'Local player changed.'end
  local other={native.other_key}
  for _,value in ipairs({actor.request,actor.current})do
   other[#other+1]=table.concat({value.body_type,value.helmet_id,value.cape_id},'|')
  end
  local out={session=tostring(native.session)..':'..tostring(actor.session_key),other_key=table.concat(other,'|'),
   pending_nonarmor=native.pending_nonarmor,controller_armor_id=native.controller_armor_id,
   profile_armor_id=native.profile_armor_id,request_armor_id=actor.request_armor_id,
   cache_armor_id=actor.cache_armor_id,cache_passive=actor.cache_passive_enum}
  local expected={};for key,value in pairs(out)do expected[key]=value end
  observations[out]={native=native,actor=actor,expected=expected};return out
 end
 function bridge.verify(snapshot)
  local value=observations[snapshot]
  if not value then return false end
  for key,expected in pairs(value.expected)do if snapshot[key]~=expected then return false end end
  for key,actual in pairs(snapshot)do if value.expected[key]~=actual then return false end end
  return grid:verify_commit(value.native)==true and value.actor.verify()==true
 end
 function bridge.verify_owned(ids)return catalog.verify_owned(ids)==true end
 function bridge.owned_armors()
  local ids={};for id,owned in pairs(catalog.owned)do if owned then ids[#ids+1]=id end end;return ids
 end
 function bridge.commit_owned(id,snapshot)
  if not bridge.verify(snapshot)then return nil,'Equipment changed before Apply.'end
  if catalog.owned[id]~=true or catalog.verify_owned({id})~=true then return nil,'Armor ownership changed before Apply.'end
  return grid:commit_owned(id,observations[snapshot].native,catalog)
 end
 return bridge
end
return M
