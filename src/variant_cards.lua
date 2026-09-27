-- Pure saved-card identities. Display names never become native identity keys.
-- Ordinals are scoped to one sorted presentation; saved state keeps exact names.
local M={}
local MAX_ITEMS=256

function M.capacity(native_item_count,allow_create)
 if type(native_item_count)~='number' or native_item_count%1~=0
  or native_item_count<1 or native_item_count>MAX_ITEMS then return 0 end
 return math.max(0,MAX_ITEMS-native_item_count-(allow_create and 1 or 0))
end

function M.build(presets,available_by_kit,allow_create,create_donor_id)
 if type(presets)~='table'or type(available_by_kit)~='table'then
  return nil,'Saved variants and available armor are required'
 end
 local names={}
 for name,request in pairs(presets)do
  if type(name)~='string'or type(request)~='table'or type(request.appearance_id)~='string'then
   return nil,'Invalid saved variant'
  end
  names[#names+1]=name
 end
 if #names>MAX_ITEMS then return nil,'Saved variant storage limit exceeded'end
 table.sort(names)
 local cards={}
 for ordinal,name in ipairs(names)do
  local request=presets[name]
  if available_by_kit[request.appearance_id]then
   cards[#cards+1]={key='saved:'..ordinal,kind='variant',kit_id=request.appearance_id,
    label=name,request=request}
  end
 end
 if allow_create then
  if type(create_donor_id)~='string'or not available_by_kit[create_donor_id]then
   return nil,'Owned create thumbnail donor unavailable'
  end
  cards[#cards+1]={key='create',kind='create',kit_id=create_donor_id,label='+'}
 end
 return cards
end

return M
