-- Read-only development observation of the known kind-224 Armory controller.
-- It inventories candidate virtual functions; it NEVER calls a candidate.
-- Input: signature-verified {base,read,manager_global,menu_global,verify,decode?}.
-- Output contains semantic offsets/function RVAs, not raw bytes or heap pointers.
local M={}
local function u16(s,o)
 if type(s)~='string'or #s<o+2 then return nil end
 local a,b=s:byte(o+1,o+2);return a+256*b
end
local function u32(s,o)
 if type(s)~='string'or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+256*b+65536*c+16777216*d
end
local function ptr(s,o)
 o=o or 0;local lo,hi=u32(s,o),u32(s,o+4)
 if not hi or hi>=32768 then return nil end
 local n=lo+hi*4294967296;return n>=65536 and n or nil
end
function M.inspect(bridge)
 local ok,result=pcall(function()
  assert(type(bridge)=='table'and type(bridge.read)=='function'and type(bridge.verify)=='function','verified debug bridge required')
  assert(bridge.verify()==true,'UI signature proof changed')
  local reads,total,watched=0,0,{}
  local function read(at,size)
   assert(type(at)=='number'and at>=65536 and at%1==0 and at+size<140737488355328 and size>=1 and size<=4096,'observation bounds rejected')
   reads,total=reads+1,total+size
   assert(reads<=2048 and total<=65536,'controller observation budget exceeded')
   local raw=bridge.read(at,size);assert(type(raw)=='string'and #raw==size,'controller evidence unreadable')
   return raw
  end
  local function watch(at,size)
   local raw=read(at,size);watched[#watched+1]={at=at,size=size,raw=raw};return raw
  end
  local base=assert(bridge.base,'module base required')
  local dos=watch(base,64);assert(dos:sub(1,2)=='MZ','invalid module header')
  local pe=u32(dos,60);assert(pe>=64 and pe<=65536,'invalid PE offset')
  local nt=watch(base+pe,24+144)
  assert(nt:sub(1,4)=='PE\0\0'and u16(nt,4)==0x8664 and u16(nt,24)==0x20b,'PE64 image required')
  local count,opt,image_size=u16(nt,6),u16(nt,20),u32(nt,80)
  assert(count>=1 and count<=96 and opt>=144 and opt<=4096 and image_size>=4096 and image_size<=536870912,'invalid PE bounds')
  local sections={}
  for i=0,count-1 do
   local h=watch(base+pe+24+opt+i*40,40)
   local size,rva,flags=u32(h,8),u32(h,12),u32(h,36)
   assert(rva+size<=image_size,'invalid section bounds')
   if size>0 then
    sections[#sections+1]={first=base+rva,last=base+rva+size,
     readable=math.floor(flags/0x40000000)%2==1,executable=math.floor(flags/0x20000000)%2==1}
   end
  end
  local function image_kind(at,size)
   for _,section in ipairs(sections)do
    if at>=section.first and at+size<=section.last and section.readable then
     return section.executable and 'code'or 'data'
    end
   end
  end
  local pdata_rva,pdata_size=u32(nt,24+112+24),u32(nt,24+112+28)
  -- A packed image may store its exception directory in readable executable
  -- .winlice memory. Protection alone does not invalidate that metadata.
  local pdata_valid,pdata_reason=pcall(function()
   assert(u32(nt,24+108)>=4 and pdata_size>=12 and pdata_size%12==0 and pdata_size<=2400000
    and image_kind(base+pdata_rva,pdata_size),'bounded readable PE function table required')
   local entries=pdata_size/12
   local previous,previous_index
   for i=0,math.min(16,entries-1)do
    local index=entries==1 and 0 or math.floor(i*(entries-1)/math.min(16,entries-1))
    if index~=previous_index then
     local row=watch(base+pdata_rva+index*12,12)
     local first,last=u32(row,0),u32(row,4)
     assert(first<last and image_kind(base+first,last-first)=='code','invalid sampled function range')
     assert(not previous or first>previous,'unsorted sampled function table')
     previous,previous_index=first,index
    end
   end
  end)
  local pdata_status=pdata_valid and 'sampled readable function table'or 'unavailable: '..tostring(pdata_reason)
  local function bounds(rva)
   if not pdata_valid then return nil end
   local lo,hi=0,pdata_size/12-1
   while lo<=hi do
    local mid=math.floor((lo+hi)/2)
    local row=read(base+pdata_rva+mid*12,12)
    local first,last=u32(row,0),u32(row,4)
    assert(first<last and image_kind(base+first,last-first)=='code','invalid function-table range')
    if rva<first then hi=mid-1
    elseif rva>=last then lo=mid+1
    else
     return first,last-first
    end
   end
  end
  local manager=assert(ptr(watch(bridge.manager_global,8)),'UI manager unavailable')
  local menu=assert(ptr(watch(bridge.menu_global,8)),'menu manager unavailable')
  local row_count=u32(watch(manager+0x166c,4),0)
  assert(row_count>=1 and row_count<=64,'UI registry bounds rejected')
  local rows=watch(manager+0x1670,row_count*16)
  local controller
  for i=0,row_count-1 do
   if u32(rows,i*16+8)==224 then
    assert(not controller,'ambiguous Armory controller')
    controller=assert(ptr(rows,i*16),'invalid Armory controller')
   end
  end
  local menu_state=watch(menu+0x4288,44)
  if not controller then
   local output={status='Armory controller is not registered',menu_owner_offsets={},slots={},
    vtable_status='unavailable',menu_current=u32(menu_state,12),menu_pending=u32(menu_state,16),
    menu_stack_depth=u32(menu_state,40)}
   if output.menu_stack_depth>=1 and output.menu_stack_depth<=5 then
    output.menu_stack_top=u32(menu_state,20+(output.menu_stack_depth-1)*4)
   end
   for _,item in ipairs(watched)do assert(read(item.at,item.size)==item.raw,'controller observation changed')end
   assert(bridge.verify()==true,'UI signature proof changed')
   output.reads,output.bytes_read=reads,total
   return output
  end
  local header=watch(controller,16)
  local menu_header=watch(menu,512)
  local menu_offsets={}
  for offset=0,504,8 do
   if ptr(menu_header,offset)==controller then menu_offsets[#menu_offsets+1]=offset end
  end
  local output={status='controller_observed',menu_owner_offsets=menu_offsets,
   controller_u32_at_8=u32(header,8),vtable_status='first word is not an image data pointer',slots={},
   menu_current=u32(menu_state,12),menu_pending=u32(menu_state,16),menu_stack_depth=u32(menu_state,40)}
  if output.menu_stack_depth and output.menu_stack_depth>=1 and output.menu_stack_depth<=5 then
   output.menu_stack_top=u32(menu_state,20+(output.menu_stack_depth-1)*4)
  end
  local vtable=ptr(header)
  if vtable and image_kind(vtable,8)=='data'then
   output.vtable_status='candidate image vtable';output.vtable_rva=vtable-base
   local functions={}
   for slot=0,23 do
    if image_kind(vtable+slot*8,8)~='data'then break end
    local target=ptr(watch(vtable+slot*8,8))
    if not target or image_kind(target,1)~='code'then break end
    local rva=target-base
    local entry={slot=slot,rva=rva}
    if not functions[rva]then
     local valid,first,size=pcall(bounds,rva)
     if not valid then
      pdata_valid=false;pdata_status='unavailable: '..tostring(first);first,size=nil,nil
     end
     functions[rva]={first=first,size=size}
     if first and type(bridge.decode)=='function'then
      local bytes=watch(base+first,math.min(size,256))
      functions[rva].instructions=bridge.decode(bytes,first)
     end
    end
    entry.function_start=functions[rva].first;entry.function_size=functions[rva].size
    entry.instructions=functions[rva].instructions
    output.slots[#output.slots+1]=entry
   end
   if #output.slots==0 then output.vtable_status='image data pointer has no executable slots'end
  end
  for _,item in ipairs(watched)do assert(read(item.at,item.size)==item.raw,'controller observation changed')end
  assert(bridge.verify()==true,'UI signature proof changed')
  output.function_metadata=pdata_status
  output.reads,output.bytes_read=reads,total
  return output
 end)
 if not ok then return nil,tostring(result)end
 return result
end
function M.format(result)
 local lines={'Armory controller metadata (read-only)',
  'status='..tostring(result.status),
  'menu_current='..tostring(result.menu_current),
  'menu_pending='..tostring(result.menu_pending),
  'menu_stack_depth='..tostring(result.menu_stack_depth),
  'menu_stack_top='..tostring(result.menu_stack_top),
  'controller_u32_at_8='..tostring(result.controller_u32_at_8),
  'function_metadata='..tostring(result.function_metadata),
  'vtable_status='..tostring(result.vtable_status),
  'vtable_rva='..(result.vtable_rva and string.format('0x%x',result.vtable_rva)or 'none')}
 for _,offset in ipairs(result.menu_owner_offsets or {})do
  lines[#lines+1]=string.format('menu_owner_offset=0x%x',offset)
 end
 for _,entry in ipairs(result.slots or {})do
  lines[#lines+1]=string.format('slot=%d target_rva=0x%x function_start=%s function_size=%s',entry.slot,entry.rva,
   entry.function_start and string.format('0x%x',entry.function_start)or 'no_pdata',tostring(entry.function_size or 'unknown'))
  for _,instruction in ipairs(entry.instructions or {})do
   if type(instruction)=='table'and type(instruction.rva)=='number'and type(instruction.op)=='string'then
    lines[#lines+1]=string.format('  %08x %s',instruction.rva,instruction.op)
   end
  end
 end
 lines[#lines+1]='reads='..tostring(result.reads)..' bytes_read='..tostring(result.bytes_read)
 return table.concat(lines,'\n')..'\n'
end
return M
