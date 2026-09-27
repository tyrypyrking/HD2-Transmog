-- Read-only type/boxing evidence for an engine-created Material userdata.
-- A successful pointer conversion is NOT a usable Gui.bitmap argument.
local M={}
local function u32(s,o)
 if type(s)~='string'or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function ptr(s,o)
 local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local p=lo+hi*4294967296;return p>=65536 and p or nil
end
local function hash(s)
 if type(s)~='string'or #s~=8 then return nil end
 local out={};for i=8,1,-1 do out[#out+1]=string.format('%02x',s:byte(i))end
 return table.concat(out)
end
function M.inspect(engine,material,bridge,address_of)
 local ok,result=pcall(function()
  assert(material~=nil and bridge.verify(),'existing material and current UI proof required')
  local ffi=require('ffi')
  local result={material_type=type(material),raw_pointer_bitmap_supported=false,candidates={}}
  local id=engine.Material.id64(material)
  local expected=engine.IdString64.to_hex(id):lower()
  assert(expected:match('^%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x%x$'),'material resource identity unavailable')
  result.resource=expected
  local at=address_of and address_of(material)or tonumber(ffi.cast('uintptr_t',material))
  assert(type(at)=='number'and at%1==0 and at>=65536 and at<140737488355296,'material userdata address unavailable')
  local raw=bridge.read(at,32);assert(type(raw)=='string'and #raw==32,'material userdata unreadable')
  -- Inspect at most four pointer-sized fields and 128 bytes per candidate.
  -- Publish offsets/resource identities only, never payload bytes or addresses.
  for o=0,24,8 do
   local candidate=ptr(raw,o)
   if candidate then
    local bytes=bridge.read(candidate,128)
    if type(bytes)=='string'and #bytes==128 then
     for p=0,120,8 do
      if hash(bytes:sub(p+1,p+8))==expected then
       result.candidates[#result.candidates+1]={payload_offset=o,resource_offset=p}
      end
     end
     assert(bridge.read(candidate,128)==bytes,'material candidate changed during inspection')
    end
   end
  end
  assert(bridge.read(at,32)==raw and bridge.verify(),'material or UI proof changed during inspection')
  return result
 end)
 if not ok then return nil,tostring(result)end
 return result
end
function M.format(result)
 local rows={'HD2TM_MATERIAL_BOX 1','read_only=true','material_type='..result.material_type,
  'resource='..result.resource,'raw_pointer_bitmap_supported=false'}
 for _,v in ipairs(result.candidates)do
  rows[#rows+1]='payload_offset='..v.payload_offset..' resource_offset='..v.resource_offset
 end
 return table.concat(rows,'\n')..'\n'
end
return M
