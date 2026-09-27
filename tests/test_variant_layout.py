"""All current appearance/stat donor pairings have an exact <=20-piece layout."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def test_all_current_armor_pairs_preserve_visuals_ordered_stat_slots_and_torso():
    script=r'''
local L=dofile('src/variant_layout.lua')
local data=dofile('src/catalog_data.lua')
local function unhex(s)return(s:gsub('%x%x',function(v)return string.char(tonumber(v,16))end))end
local function word(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local records={}
for _,kit in pairs(data.kits)do if kit.category==0 then
 local record={bodies={}}
 for _,body in ipairs(kit.bodies)do
  local b={type=body.type,pieces={}}
  for _,p in ipairs(body.pieces)do b.pieces[#b.pieces+1]={bytes=unhex(p.raw),slot=p.slot,kind=p.type,weight=p.weight}end
  record.bodies[#record.bodies+1]=b
 end
 records[#records+1]=record
end end
assert(#records==135)
local function effective(record,t,is_output)
 local weights,visuals,count={},{},0
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==t then
  for _,piece in ipairs(body.pieces)do
   local raw=is_output and piece or piece.bytes
   count=count+1
   local kind,weight,slot=word(raw,12),word(raw,16),word(raw,8)
   if kind==0 and weight~=3 then weights[#weights+1]=slot..':'..weight end
   if raw:sub(1,8)~=string.rep('\0',8)then
    local visual=raw:sub(1,16)..raw:sub(21);visuals[visual]=(visuals[visual]or 0)+1
   end
  end
 end end
 return table.concat(weights,','),visuals,count
end
local combinations,none,null=0,0,0
for _,look in ipairs(records)do for _,stats in ipairs(records)do
 local result=L.compose(look,stats);combinations=combinations+1
 if result.needs_none then none=none+1 end
 if result.needs_null then null=null+1 end
 for _,body_type in ipairs({0,1})do
  local expected=effective(stats,body_type,false)
  local actual,visuals,count=effective(result,body_type,true)
  assert(actual==expected,'donor slot/weight order changed')
  assert(count<=20,'native collection overflow')
  local _,original=effective(look,body_type,false)
  for key,n in pairs(original)do assert(visuals[key]==n,'appearance changed');visuals[key]=nil end
  assert(next(visuals)==nil,'unexpected visible mesh')
 end
end end
assert(combinations==18225 and none>0 and null>0)
'''
    # Lua source must contain one escaped NUL, rather than a backslash-zero name.
    script=script.replace("'\\\\0'","'\\0'")
    result=subprocess.run(["luajit","-"],input=script,text=True,cwd=ROOT,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
