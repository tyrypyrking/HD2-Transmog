-- Pure descriptor composition: preserve appearance bytes and every donor
-- contributing Armor slot/weight in native order, including the torso class.
-- Returned null-path / weight-None representations still require independent
-- renderer proof before activation; this module performs no memory operations.
local M={}
local function word(n)return string.char(n%256,math.floor(n/256)%256,math.floor(n/65536)%256,math.floor(n/16777216)%256)end
local function weighted(piece,value)return piece.bytes:sub(1,16)..word(value)..piece.bytes:sub(21)end
local function collect(record,body_type)
 local all,armor={},{}
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==body_type then
  for _,piece in ipairs(body.pieces)do
   assert(#all<20,'source exceeds observed native piece collection capacity')
   all[#all+1]=piece
   if piece.kind==0 and piece.weight~=3 then armor[#armor+1]=piece end
  end
 end end
 return all,armor
end
function M.compose(appearance,stats)
 local out={bodies={},needs_none=false,needs_null=false,ordered_weights={}}
 for _,body_type in ipairs({0,1})do
  local visuals=collect(appearance,body_type)
  local _,donor=collect(stats,body_type)
  assert(#donor>0,'native stats donor has no armor contributors')
  local by={}
  for _,piece in ipairs(visuals)do
   local key=piece.slot..':'..piece.kind
   assert(not by[key],'ambiguous visual slot/kind');by[key]=piece
  end
  local pieces,weights={}, {}
  for index=1,#donor do
   local sample=donor[index];local key=sample.slot..':0';local visual=by[key]
   assert(sample.kind==0 and sample.weight>=0 and sample.weight<=2,'invalid donor armor weight')
   if visual then
    pieces[#pieces+1]=weighted(visual,sample.weight);by[key]=nil
   else
    pieces[#pieces+1]=string.rep('\0',8)..word(sample.slot)..word(0)..word(sample.weight)..string.rep('\0',76)
    out.needs_null=true
   end
   weights[#weights+1]=sample.weight
  end
  for _,piece in ipairs(visuals)do
   local key=piece.slot..':'..piece.kind
   if by[key]then
    if piece.kind==0 then pieces[#pieces+1]=weighted(piece,3);out.needs_none=true
    else pieces[#pieces+1]=piece.bytes end
    by[key]=nil
   end
  end
  assert(#pieces<=20,'composition exceeds observed native piece collection capacity')
  out.bodies[#out.bodies+1]={type=body_type,pieces=pieces}
 out.ordered_weights[body_type]=weights
 end
 -- Keep the byte-identical leading records shared in Any. Moving this exact
 -- prefix changes neither collector order nor either body's appearance, and
 -- preserves native metadata consumers that intentionally request Any alone.
 -- Never move later records forward merely to satisfy a metadata query.
 local stocky,slim=out.bodies[1].pieces,out.bodies[2].pieces
 local shared=0
 while shared<math.min(#stocky,#slim)and stocky[shared+1]==slim[shared+1]do shared=shared+1 end
 if shared>0 then
  local bodies={{type=3,pieces={}}}
  for i=1,shared do bodies[1].pieces[i]=stocky[i]end
  for index,list in ipairs({stocky,slim})do
   if #list>shared then
    local body={type=index-1,pieces={}}
    for i=shared+1,#list do body.pieces[#body.pieces+1]=list[i]end
    bodies[#bodies+1]=body
   end
  end
  out.bodies=bodies;out.shared_prefix_count=shared
 else out.shared_prefix_count=0 end
 return out
end
return M
