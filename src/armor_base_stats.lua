-- Pure Armor-card base-stat calculations from already verified kit pieces.
-- No game reads/writes, native calls, passive lookup, ownership inference or IO.
-- The caller supplies missing formula/rounding evidence explicitly. Constants
-- from the captured current UI are facts, not a future-build compatibility gate.
local M={}
local ffi=require('ffi')
local scalar=ffi.new('float[1]')
local function f32(value)
 scalar[0]=value;return tonumber(scalar[0])
end
local function finite(value)
 return type(value)=='number'and value==value and value>-math.huge and value<math.huge
end
local function uint(value)
 return type(value)=='number'and value%1==0 and value>=0 and value<=4294967295
end
local FIELDS={'armor_rating','speed','stamina_regen'}
local KNOWN={initial_value=100,speed_scale=5,
 coefficients={armor_rating={0,1,2},speed={f32(1.1),1,f32(0.9)},stamina_regen={0.75,1,1.5}}}
local MISSING={'armor_scale','one','zero','rounding'}
local function values_copy(value)
 return {armor_rating=value.armor_rating,speed=value.speed,stamina_regen=value.stamina_regen}
end
function M.evidence()
 local out={initial_value=KNOWN.initial_value,speed_scale=KNOWN.speed_scale,coefficients={},missing={},verified=false}
 for _,field in ipairs(FIELDS)do out.coefficients[field]={unpack(KNOWN.coefficients[field])}end
 for i,field in ipairs(MISSING)do out.missing[i]=field end
 return out
end
local function contract(input)
 assert(type(input)=='table','explicit base-stat formula contract required')
 local out={}
 for _,field in ipairs({'initial_value','speed_scale','armor_scale','one','zero'})do
  local value=input[field]
  if value==nil then value=KNOWN[field]end
  assert(finite(value),'base-stat formula contract missing finite '..field)
  value=f32(value);assert(finite(value),'base-stat formula constant outside float32: '..field)
  out[field]=value
 end
 assert(out.one==1 and out.zero==0,'unsupported native one/zero identities')
 assert(out.initial_value>0 and out.armor_scale>0 and out.speed_scale>0,'invalid native stat scales')
 out.coefficients={}
 for _,field in ipairs(FIELDS)do
  local source=input.coefficients and input.coefficients[field]or KNOWN.coefficients[field]
  assert(type(source)=='table'and #source==3,'three native weight coefficients required for '..field)
  out.coefficients[field]={}
  for index,value in ipairs(source)do
   assert(finite(value),'invalid weight coefficient');value=f32(value)
   assert(finite(value),'weight coefficient outside float32');out.coefficients[field][index]=value
  end
 end
 local rounders={
  nearest_ties_away=function(n)return n<0 and math.ceil(n-0.5)or math.floor(n+0.5)end,
  nearest_ties_even=function(n)
   local whole=math.floor(n);local fraction=n-whole
   return fraction<0.5 and whole or fraction>0.5 and whole+1 or whole%2==0 and whole or whole+1
  end,
  floor=math.floor,ceil=math.ceil,
  truncate=function(n)return n<0 and math.ceil(n)or math.floor(n)end,
 }
 assert(type(input.rounding)=='string'and rounders[input.rounding],'explicit supported native rounding contract required')
 out.round=rounders[input.rounding];out.rounding=input.rounding
 out.verified=input.verified==true and type(input.evidence)=='string'and #input.evidence>0 and #input.evidence<=1024
 out.evidence=type(input.evidence)=='string'and input.evidence or nil
 return out
end
local function calculate(record,body_type,c)
 assert(type(record)=='table'and record.category==0,'verified body-armor record required')
 assert(body_type==0 or body_type==1,'explicit native body type 0 or 1 required')
 assert(type(record.bodies)=='table'and #record.bodies>=1 and #record.bodies<=8,'invalid verified body descriptors')
 local gathered,count=0,0
 local sums={armor_rating=0,speed=0,stamina_regen=0}
 for _,body in ipairs(record.bodies)do
  if gathered==30 then break end
  assert(type(body)=='table'and uint(body.type),'invalid body descriptor')
  if body.type==body_type or body.type==3 then
   assert(type(body.pieces)=='table'and #body.pieces<=64,'invalid verified piece array')
   for _,piece in ipairs(body.pieces)do
    if gathered==30 then break end
    gathered=gathered+1
    assert(type(piece)=='table'and uint(piece.slot),'invalid piece slot')
    local kind=piece.kind;if kind==nil then kind=piece.type end
    assert(uint(kind),'invalid piece kind')
    if kind==0 and piece.slot>=2 and piece.slot<=9 and piece.slot~=3 then
     assert(uint(piece.weight)and piece.weight<=2,'Armor-card weight is outside the proved three-entry tables')
     count=count+1
     for _,field in ipairs(FIELDS)do sums[field]=f32(sums[field]+c.coefficients[field][piece.weight+1])end
    end
   end
  end
 end
 local means={}
 for _,field in ipairs(FIELDS)do means[field]=count==0 and 0 or f32(sums[field]/f32(count))end
 -- Match each SSE scalar operation in the current Armor-card calculation.
 -- Base Armor bypasses the native passive modifier accumulator completely.
 local armor=f32(means.armor_rating-c.one)
 armor=f32(armor*c.armor_scale);armor=f32(armor+c.initial_value)
 local speed=f32(means.speed*c.speed_scale);speed=f32(speed*c.initial_value)
 local stamina=f32(means.stamina_regen-c.one)
 stamina=f32(c.zero-stamina);stamina=f32(stamina+c.one);stamina=f32(stamina*c.initial_value)
 local unrounded={armor_rating=armor,speed=speed,stamina_regen=stamina}
 local displayed={}
 for _,field in ipairs(FIELDS)do
  assert(finite(unrounded[field]),'native base-stat arithmetic overflow')
  displayed[field]=c.round(unrounded[field])
  assert(displayed[field]>=-2147483648 and displayed[field]<=2147483647,'native displayed stat outside int32')
 end
 return {base_values=displayed,displayed=values_copy(displayed),unrounded=unrounded,
  coefficients=means,body_type=body_type,contributor_count=count,gathered_count=gathered,
  verified=c.verified,evidence=c.evidence,rounding=c.rounding,donor_passive_ignored=true}
end
function M.calculate(record,body_type,formula_contract)
 local ok,result=pcall(function()return calculate(record,body_type,contract(formula_contract))end)
 if not ok then return nil,tostring(result)end
 return result
end
local function key(values)
 return string.format('%d|%d|%d',values.armor_rating,values.speed,values.stamina_regen)
end
function M.choices(catalog_result,body_type,formula_contract)
 local ok,result=pcall(function()
  local c=contract(formula_contract)
  assert(body_type==0 or body_type==1,'explicit native body type 0 or 1 required')
  assert(type(catalog_result)=='table'and type(catalog_result.records)=='table'
   and type(catalog_result.catalog)=='table'and type(catalog_result.owned)=='table','verified owned catalog required')
  local caps=catalog_result.capabilities
  assert(caps and caps.kit_records_verified==true and caps.ownership_verified==true,'verified pieces and owned-donor set required')
  local ids={}
  for id,owned in pairs(catalog_result.owned)do if owned==true then
   assert(type(id)=='string'and id:match('^armor:%x%x%x%x%x%x%x%x$'),'invalid owned armor identity')
   ids[#ids+1]=id
  end end
  assert(#ids<=2048,'owned armor bounds rejected');table.sort(ids)
  local groups,ordered={},{}
  for _,id in ipairs(ids)do
   local record=catalog_result.records[id];local entry=catalog_result.catalog[id]
   assert(record and entry and uint(record.item_id)and id==string.format('armor:%08x',record.item_id),'owned donor record missing or mismatched')
   local stats_id='native-stats:'..string.format('%08x',record.item_id)
   assert(entry.stats_id==stats_id,'owned donor stats identity mismatch')
   local value=calculate(record,body_type,c);local group_key=key(value.base_values)
   local group=groups[group_key]
   if not group then
    group={key=group_key,body_type=body_type,base_values=values_copy(value.base_values),
     displayed=values_copy(value.base_values),unrounded=values_copy(value.unrounded),
     verified=value.verified,donor_ids={},stats_ids={},donors={},
     representative_kit_id=id,stats_id=stats_id,donor_passive_ignored=true}
    groups[group_key]=group;ordered[#ordered+1]=group
   elseif group.unrounded then
    for _,field in ipairs(FIELDS)do if group.unrounded[field]~=value.unrounded[field]then group.unrounded=nil;break end end
   end
   group.donor_ids[#group.donor_ids+1]=id;group.stats_ids[#group.stats_ids+1]=stats_id
   group.donors[#group.donors+1]={kit_id=id,stats_id=stats_id,unrounded=values_copy(value.unrounded),
    contributor_count=value.contributor_count,gathered_count=value.gathered_count}
  end
  table.sort(ordered,function(a,b)
   for _,field in ipairs(FIELDS)do if a.base_values[field]~=b.base_values[field]then return a.base_values[field]<b.base_values[field]end end
   return a.key<b.key
  end)
  return ordered
 end)
 if not ok then return nil,tostring(result)end
 return result
end
return M
