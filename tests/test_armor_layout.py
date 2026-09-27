"""Independent numeric profiles, visible resources, and bounded native layouts."""
from test_variant_patch import run

CATALOG = r'''
local L=dofile('src/armor_layout.lua')
local B=dofile('src/armor_base_stats.lua')
local C={armor_scale=50,one=1,zero=0,rounding='nearest_ties_away'}
local kits={}
local function decode(raw)return(raw:gsub('..',function(v)return string.char(tonumber(v,16))end))end
for _,kit in pairs(dofile('src/catalog_data.lua').kits)do if kit.category==0 then
 for _,body in ipairs(kit.bodies)do for _,p in ipairs(body.pieces)do p.kind=p.type;p.bytes=decode(p.raw)end end
 kits[#kits+1]=kit
end end
local function word(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function observe(composed)
 local result={category=0,bodies={}}
 for _,body in ipairs(composed.bodies)do
  local b={type=body.type,pieces={}};result.bodies[#result.bodies+1]=b
  for _,raw in ipairs(body.pieces)do b.pieces[#b.pieces+1]={slot=word(raw,8),kind=word(raw,12),weight=word(raw,16),bytes=raw}end
 end
 return result
end
local function collect(record,shape)
 local result={}
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==shape then
  for _,p in ipairs(body.pieces)do result[#result+1]=p end
 end end
 return result
end
'''


def test_all_catalog_pairs_preserve_numeric_profiles_resources_and_torso_class():
    run(CATALOG+r'''
local count=0
for _,source in ipairs(kits)do for _,donor in ipairs(kits)do
 local uniform=L.uniform(donor);local composed
 if uniform~=nil then
  composed={category=0,bodies={}}
  for _,b in ipairs(source.bodies)do
   local copy={type=b.type,pieces={}};composed.bodies[#composed.bodies+1]=copy
   for _,p in ipairs(b.pieces)do copy.pieces[#copy.pieces+1]={slot=p.slot,kind=p.kind,weight=p.kind==0 and uniform or p.weight,bytes=p.bytes}end
  end
 else
  local ok,value=pcall(L.compose,source,donor)
  assert(ok,source.id..' / '..donor.id..': '..tostring(value))
  composed=observe(value)
 end
 for _,shape in ipairs({0,1})do
  local before=assert(B.calculate(donor,shape,C));local after=assert(B.calculate(composed,shape,C))
  for _,field in ipairs({'armor_rating','speed','stamina_regen'})do
   assert(before.base_values[field]==after.base_values[field],source.id..' / '..donor.id..' '..field)
  end
  local original,actual=collect(source,shape),collect(composed,shape)
  assert(#actual<=20)
  local visuals={}
  local function signature(p)return p.bytes:sub(1,12)..p.bytes:sub(21)end
  for _,p in ipairs(original)do local key=signature(p);visuals[key]=(visuals[key]or 0)+1 end
  local occupied={};local torso
  for _,p in ipairs(actual)do
   assert(p.weight<=2,'unproved weight None')
   if p.kind==0 and p.slot==2 then torso=p.weight end
   if p.bytes:sub(1,8)~=string.rep('\0',8)then
    local key=signature(p);assert(visuals[key]and visuals[key]>0,'visual resource/material/slot changed')
    visuals[key]=visuals[key]-1
    local location=p.slot..':'..p.kind
    assert(not occupied[location],'renderer unit-array collision');occupied[location]=true
   end
  end
  for _,n in pairs(visuals)do assert(n==0,'visible part lost')end
  local expected_torso
  for _,p in ipairs(collect(donor,shape))do if p.kind==0 and p.slot==2 then expected_torso=p.weight end end
  assert(torso==expected_torso,'native torso class changed')
  if uniform==nil then
   local expected,observed={0,0,0},{0,0,0}
   for _,p in ipairs(collect(donor,shape))do if p.kind==0 then expected[p.weight+1]=expected[p.weight+1]+1 end end
   for _,p in ipairs(actual)do if p.kind==0 then observed[p.weight+1]=observed[p.weight+1]+1 end end
   assert(table.concat(expected,',')==table.concat(observed,','),'gameplay coefficient distribution changed')
  end
 end
 count=count+1
end end
assert(count==18225)
''')
