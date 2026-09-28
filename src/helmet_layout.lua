-- Preserve appearance resources and topology; copy weights by body/slot/kind.
-- Reject unmatched topology rather than inventing helmet stat contributions.
local M={}
local function collect(record,kind)
 local out,order={},{}
 for _,body in ipairs(record.bodies)do if body.type==3 or body.type==kind then
  for _,piece in ipairs(body.pieces)do
   assert(piece.slot==0 and piece.kind>=0 and piece.kind<=2 and piece.weight>=0 and piece.weight<=2,'unsupported helmet piece')
   local key=piece.slot..':'..piece.kind
   assert(not out[key],'ambiguous helmet piece')
   out[key]=piece;order[#order+1]=piece
  end
 end end
 assert(#order>0 and #order<=20,'helmet body pieces unavailable')
 return out,order
end
function M.compose(source,stats)
 local out={bodies={},appearance_topology_preserved=true,slot_weights_preserved=true,base_weight_sequence_preserved=true}
 for _,kind in ipairs({0,1})do
  local look,order=collect(source,kind);local donor=collect(stats,kind);local pieces={}
  for key in pairs(donor)do assert(look[key],'helmet stats topology differs')end
  for _,p in ipairs(order)do
   local d=assert(donor[p.slot..':'..p.kind],'helmet stats topology differs')
   pieces[#pieces+1]=p.bytes:sub(1,16)..d.bytes:sub(17,20)..p.bytes:sub(21)
  end
  out.bodies[#out.bodies+1]={type=kind,pieces=pieces}
 end
 return out
end
return M
