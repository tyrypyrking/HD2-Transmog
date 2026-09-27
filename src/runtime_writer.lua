-- Small in-process data writer. No external-process access, code patching,
-- executable allocations, protection changes, or persisted addresses.
local M={}
-- The game may retain copied descriptor pointers in preview/spawn work after a
-- reset. Keep immutable private buffers alive for the whole Lua/module session.
-- They are data only, deduplicated, bounded, and never serialized as addresses.
local private_buffers,private_bytes={},0
local PRIVATE_LIMIT=8*1024*1024
local function u32(s,o)
 local a,b,c,d=s:byte(o+1,o+4);return a+b*256+c*65536+d*16777216
end
local function u64(s,o)return u32(s,o)+u32(s,o+4)*4294967296 end
function M.new(read_bridge,result)
 local ffi=require('ffi')
 for _,declaration in ipairs({
  'void *GetCurrentProcess(void);',
  'size_t VirtualQuery(const void*,void*,size_t);',
  'int WriteProcessMemory(void*,void*,const void*,size_t,size_t*);',
 })do pcall(ffi.cdef,declaration)end
 local k=ffi.load('kernel32');local process=k.GetCurrentProcess()
 local info,count=ffi.new('uint8_t[48]'),ffi.new('size_t[1]')
 local function writable(at,n)
  if type(at)~='number' or at%1~=0 or at<65536 or at+n>=140737488355328 then return false end
  if k.VirtualQuery(ffi.cast('const void*',at),info,48)~=48 then return false end
  local s=ffi.string(info,48)
  local base,size=u64(s,0),u64(s,24)
  return at>=base and at+n<=base+size and u32(s,32)==0x1000
    and (u32(s,36)==4 or u32(s,36)==8) -- writable data, never executable
 end
 return {
  read=read_bridge.read,
  verify=function(observation,request,source,target,phase,donors)
   if observation~=result or not read_bridge.verify() or not result.verify_session()then return false end
   if phase=='reset' or phase=='rollback' then return true end
   return result.verify_owned(donors or {source,target})
  end,
  allocate=function(bytes)
   if type(bytes)~='string'or #bytes<1 or #bytes>65536 then return nil,'private data bounds rejected'end
   local existing=private_buffers[bytes]
   if existing then return {address=existing.address,size=#bytes,bytes=bytes}end
   if private_bytes+#bytes>PRIVATE_LIMIT then return nil,'private variant data budget exhausted'end
   local buffer=ffi.new('uint8_t[?]',#bytes);ffi.copy(buffer,bytes,#bytes)
   local address=tonumber(ffi.cast('uintptr_t',buffer))
   if not address or address<65536 or address>=140737488355328 then return nil,'private data pointer rejected'end
   private_buffers[bytes]={buffer=buffer,address=address};private_bytes=private_bytes+#bytes
   return {address=address,size=#bytes,bytes=bytes}
  end,
  write=function(at,s)
   if type(s)~='string' or (#s~=4 and #s~=8 and #s~=16) or not writable(at,#s)then return nil,'write range rejected'end
   count[0]=0
   local ok=k.WriteProcessMemory(process,ffi.cast('void*',at),ffi.cast('const void*',s),#s,count)
   return ok~=0 and tonumber(count[0])==#s
  end,
 }
end
return M
