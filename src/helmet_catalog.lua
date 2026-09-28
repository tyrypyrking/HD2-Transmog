-- Generic helmet capabilities derived from observed data, with no provider IDs.
local M={}
local function copy(t)local out={};for k,v in pairs(t)do out[k]=v end;return out end
local function u32(s,o)local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216 end
local function hex(s)return(s:gsub('.',function(c)return string.format('%02x',c:byte())end))end
local function unhex(s)return(s:gsub('%x%x',function(c)return string.char(tonumber(c,16))end))end
function M.reference(expected,raw)
 if expected.category~=1 then return expected end
 local out=copy(expected);local header=unhex(expected.header)
 out.header=hex(header:sub(1,28)..raw:sub(29,32)..header:sub(33))
 out.passive_enum=u32(raw,28);out.passive_variant_id=nil
 out.bodies={}
 for i,body in ipairs(expected.bodies)do
  out.bodies[i]=copy(body);out.bodies[i].pieces={}
  for j,piece in ipairs(body.pieces)do out.bodies[i].pieces[j]=copy(piece)end
 end
 out.helmet_changed=out.passive_enum~=expected.passive_enum
 return out
end
function M.piece(expected,raw,kit)
 if kit.category~=1 then return end
 local original=unhex(expected.raw);local weight=u32(raw,16)
 if weight>2 then return end
 -- Only weight and passive are gameplay fields supported by this kit layout.
 -- Visuals, slots, classifications and all remaining bytes stay validated.
 expected.raw=hex(original:sub(1,16)..raw:sub(17,20)..original:sub(21))
 expected.weight=weight
 if original:sub(17,20)~=raw:sub(17,20)then kit.helmet_changed=true end
end
function M.capabilities(kits,passives)
 local changed,present=false,false
 for _,kit in pairs(kits)do if kit.category==1 then
  changed=changed or kit.helmet_changed==true
  local passive=passives[kit.passive_enum]
  if passive then
   if #passive.stat_modifiers>0 or passive.behavior_tag~=0 then present=true end
   for _,effect in ipairs(passive.modifiers)do if effect.modifier_id~=0 then present=true end end
  end
 end end
 return {enabled=changed or present,passives_present=present,stats_or_passive_changed=changed}
end
return M
