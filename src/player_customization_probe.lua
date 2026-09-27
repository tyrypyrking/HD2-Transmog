-- Read-only local-player customization request/cache observations. Offsets are
-- cross-checked against the current native armor setter, two native getters and
-- the normal Armory apply path; globals are obtained only from code signatures.
-- No pointer/byte export, calls, writes or inference of item ownership.
local M={}
local function u32(s,o)
 if type(s)~='string' or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function ptr(s,o)
 o=o or 0;local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local n=lo+hi*4294967296;return n>=65536 and n or nil
end
local function kit_id(n)return string.format('armor:%08x',n)end
function M.new(bridge,data)
 assert(type(bridge)=='table' and type(bridge.read)=='function' and type(bridge.verify)=='function','verified read bridge required')
 assert(type(data)=='table' and type(data.kits)=='table' and type(data.passives)=='table','catalog reference required')
 local self={};local identity,session_key
 function self:sample()
  local ok,result=pcall(function()
   assert(bridge.verify(),'customization compatibility changed')
   assert(type(bridge.players)=='number','local-player signature unavailable')
   local watches={};local reads=0
   local function watch(at,n)
    reads=reads+1;assert(reads<=160,'customization read budget exceeded')
    assert(type(at)=='number' and at%1==0 and at>=65536 and at+n<140737488355328 and n>0 and n<=80,'customization read bounds rejected')
    local s=bridge.read(at,n);assert(type(s)=='string' and #s==n,'customization data unavailable')
    watches[#watches+1]={at=at,bytes=s};return s
   end
   local manager=assert(ptr(watch(bridge.armor_catalog,8)),'customization manager unavailable')
   local players=assert(ptr(watch(bridge.players,8)),'players manager unavailable')
   local counts=watch(players+0x84,8);local total,locals=u32(counts,0),u32(counts,4)
   assert(total>=1 and total<=4 and locals==1,'exactly one local player required')
   local player=assert(ptr(watch(players+0xe8,8)),'local player unavailable')
   local player_id=u32(watch(player+8,4),0)
   local map=watch(manager+0x930,20)
   local entries,capacity,empty,multiplier=ptr(map),u32(map,8),u32(map,12),u32(map,16)
   assert(entries and capacity>=1 and capacity<=4096,'player lookup capacity rejected')
   local power=capacity;while power>1 and power%2==0 do power=power/2 end
   assert(power==1,'player lookup capacity rejected')
   -- Only the low log2(capacity) bits matter. Reduce before multiplying so the
   -- product stays exact in Lua's number representation even for uint32 IDs.
   local start=((player_id%capacity)*(multiplier%capacity))%capacity
   local index
   for probe=0,math.min(capacity,64)-1 do
    local row=watch(entries+((start+probe)%capacity)*8,8);local key=u32(row,0)
    if key==player_id then index=u32(row,4);break end
    if key==empty then break end
   end
   assert(index and index<4,'local customization slot unavailable')
   local info=assert(ptr(watch(manager+0x948+index*8,8)),'local customization entity unavailable')
   local entity=u32(watch(info+0x10,4),0)
   assert(entity~=0x7fff,'local customization entity is not live')
   local request=watch(manager+0xa7c+index*64,16)
   local cache=watch(manager+0x96c+index*68,68)
   local function equipment(raw)
    local out={body_type=u32(raw,0)}
    assert(out.body_type==0 or out.body_type==1,'local body type unavailable')
    for i,field in ipairs({'helmet','cape','armor'})do
     local item=u32(raw,i*4);local ref=data.kits[item]
     assert(ref and ref.category==({1,2,0})[i],'local equipment identity/category unavailable')
     out[field..'_id']=kit_id(item)
    end
    return out
   end
   local requested,current=equipment(request),equipment(cache)
   local passive_enum=u32(cache,0x3c);local passive=data.passives[passive_enum]
   assert(passive,'cached native armor passive unavailable')
   local torso=u32(cache,0x40);assert(torso<=3,'cached native torso class unavailable')
   local next_identity={manager,players,player,player_id,index,info,entity}
   local same=identity~=nil
   if same then for i,v in ipairs(next_identity)do if identity[i]~=v then same=false;break end end end
   if not same then identity=next_identity;session_key={}end
   local function verify()
    if not bridge.verify()then return false end
    for _,w in ipairs(watches)do if bridge.read(w.at,#w.bytes)~=w.bytes then return false end end
    return true
   end
   assert(verify(),'customization changed during observation')
   return {session_key=session_key,local_player_id=player_id,entity_id=entity,slot=index,
    request=requested,current=current,request_armor_id=requested.armor_id,cache_armor_id=current.armor_id,
    cache_passive_enum=passive_enum,cache_passive_variant_id=passive.variant_id,
    torso_class=torso,settled=request==cache:sub(1,16),verify=verify,
    evidence='native_request_and_cache_readback'}
  end)
  if not ok then return nil,tostring(result)end
  return result
 end
 return self
end
function M.format(result)
 if type(result)~='table'then return 'HD2TRANSMOG_PLAYER_CUSTOMIZATION 1\nstatus=unavailable\n'end
 return table.concat({'HD2TRANSMOG_PLAYER_CUSTOMIZATION 1','local_player_id='..result.local_player_id,
  'slot='..result.slot,'request_armor_id='..result.request_armor_id,'cache_armor_id='..result.cache_armor_id,
  'cache_passive_enum='..result.cache_passive_enum,'cache_passive_variant_id='..result.cache_passive_variant_id,
  'torso_class='..result.torso_class,'settled='..tostring(result.settled),'status=observed'},'\n')..'\n'
end
return M
