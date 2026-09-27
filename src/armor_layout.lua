-- Compose mixed base profiles without coupling them to visible piece counts.
-- Resource hashes/materials and carrier packages remain native to the look.
local M={}
local function word(n)return string.char(n%256,math.floor(n/256)%256,math.floor(n/65536)%256,math.floor(n/16777216)%256)end
local function armor_slot(slot)return slot>=2 and slot<=9 and slot~=3 end
local function collect(record,body_type)
 local pieces,slots={},{}
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==body_type then
  for _,p in ipairs(body.pieces)do
   assert(#pieces<20,'native piece collection capacity exceeded')
   assert(p.slot>=0 and p.slot<=9 and p.kind>=0 and p.kind<=2 and p.weight>=0 and p.weight<=2,'unsupported native piece fields')
   local key=p.slot..':'..p.kind
   assert(not slots[key],'ambiguous effective body/slot/kind');slots[key]=p
   pieces[#pieces+1]=p
  end
 end end
 return pieces,slots
end
function M.uniform(record)
 local value
 for _,body_type in ipairs({0,1})do
  local pieces=collect(record,body_type);local torso=false;local count=0
  for _,p in ipairs(pieces)do if p.kind==0 and armor_slot(p.slot)then
   assert(p.weight<=2,'unsupported native weight')
   count=count+1
   if p.slot==2 then torso=true end
   if value==nil then value=p.weight elseif value~=p.weight then return nil end
  end end
  assert(count>0 and torso,'native stats donor has no contributing torso')
 end
 return value
end
local function weighted(p,w)return p.bytes:sub(1,16)..word(w)..p.bytes:sub(21)end
function M.compose(source,target)
 local result={bodies={},stat_only_pieces=false,reclassified_pieces=false,appearance_topology_preserved=true,
  slot_weights_preserved=true,base_weight_sequence_preserved=true,weight_none=false}
 local built={}
 for _,body_type in ipairs({0,1})do
  local visuals,occupied=collect(source,body_type)
  local donors=collect(target,body_type);local by_slot,ordered={},{ }
  for _,p in ipairs(donors)do if p.kind==0 then
   assert(p.weight<=2,'unsupported native donor weight')
   assert(not by_slot[p.slot],'ambiguous donor armor slot')
   by_slot[p.slot]=p;ordered[#ordered+1]=p
  end end
  assert(by_slot[2],'native stats donor has no contributing torso')
  local pieces,used={},{}
  for _,p in ipairs(visuals)do
   if p.kind~=0 then pieces[#pieces+1]=p.bytes
   elseif by_slot[p.slot]then
    pieces[#pieces+1]=weighted(p,by_slot[p.slot].weight);used[p.slot]=true
   else
    -- The renderer stores each kind in a separate per-slot unit array.
    -- Never overwrite another unit: use an unoccupied accessory/underlayer.
    -- Torso/Hips underlayers have additional native behavior; don't use them.
    local kind=not occupied[p.slot..':2']and 2 or
     (p.slot~=2 and p.slot~=3 and not occupied[p.slot..':1']and 1)
    assert(kind,'no collision-free visual classification for surplus armor part')
    pieces[#pieces+1]=p.bytes:sub(1,12)..word(kind)..p.bytes:sub(17)
    result.reclassified_pieces=true;result.appearance_topology_preserved=false
   end
  end
  for _,p in ipairs(ordered)do if not used[p.slot]then
   -- The renderer skips resource hash zero before unit/material creation.
   pieces[#pieces+1]=string.rep('\0',8)..word(p.slot)..word(0)..word(p.weight)..string.rep('\0',76)
   result.stat_only_pieces=true;result.appearance_topology_preserved=false
  end end
  assert(#pieces<=20,'composed body exceeds native piece collection capacity')
  local sequence={}
  for _,raw in ipairs(pieces)do if raw:byte(13)==0 then sequence[#sequence+1]=raw:byte(17)end end
  local expected={};for _,p in ipairs(ordered)do expected[#expected+1]=p.weight end
  if table.concat(sequence,',')~=table.concat(expected,',')then result.base_weight_sequence_preserved=false end
  built[body_type]=pieces
 end
 -- Keep the appearance's original Any prefix. Its byte identity must agree
 -- between body shapes; no visible piece is reordered to manufacture a prefix.
 local common=0
 for _,body in ipairs(source.bodies)do
  if body.type~=3 then break end
  common=common+#body.pieces
 end
 for i=1,common do
  if built[0][i]~=built[1][i]then common=i-1;break end
 end
 if common>0 then
  local p={};for i=1,common do p[i]=built[0][i]end
  result.bodies[#result.bodies+1]={type=3,pieces=p}
 end
 for _,body_type in ipairs({0,1})do
  local p={};for i=common+1,#built[body_type]do p[#p+1]=built[body_type][i]end
  if #p>0 then result.bodies[#result.bodies+1]={type=body_type,pieces=p}end
 end
 return result
end
return M
