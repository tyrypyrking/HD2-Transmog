-- Optional read-only localization lookup. The extra_localized_text signature
-- proves the engine-root / +0x10 / +0x3e8 chain and uint32_t -> const char* ABI.
-- Call its engine lookup directly: the game's wrapper has a scratch-buffer
-- fallback, which is unnecessary here. No fixed code address is used.
local M={}
local function u32(s,o)
 if type(s)~='string' or #s<o+4 then return nil end
 local a,b,c,d=s:byte(o+1,o+4);return a+256*b+65536*c+16777216*d
end
local function ptr(s)
 local lo,hi=u32(s,0),u32(s,4)
 if not hi or hi>=32768 then return nil end
 local n=lo+4294967296*hi;return n>=65536 and n or nil
end
local lookup_type
local function native()
 local ffi=require('ffi')
 pcall(ffi.cdef,'size_t VirtualQuery(const void*,void*,size_t);')
 lookup_type=lookup_type or ffi.typeof('const char *(*)(uint32_t)')
 local kernel=ffi.load('kernel32')
 local region=ffi.new('uint8_t[48]')
 return {
  executable=function(at)
   if kernel.VirtualQuery(ffi.cast('const void*',at),region,48)~=48 then return false end
   local info=ffi.string(region,48)
   -- MEM_COMMIT, executable protection with no PAGE_GUARD, and MEM_IMAGE.
   return u32(info,32)==0x1000 and u32(info,40)==0x1000000
    and ({[0x10]=true,[0x20]=true,[0x40]=true,[0x80]=true})[u32(info,36)]==true
  end,
  lookup=function(at,key)
   local value=ffi.cast(lookup_type,at)(key)
   if value==nil then return nil end
   return tonumber(ffi.cast('uintptr_t',value))
  end,
 }
end
function M.bind(bridge,backend)
 if type(bridge)~='table' or type(bridge.read)~='function' or type(bridge.verify)~='function'
  or type(bridge.engine_root)~='number'then return nil,'localization signature unavailable'end
 local ok,result,reason=pcall(function()
  if not bridge.verify()then return nil,'localization proof changed'end
  local root=ptr(bridge.read(bridge.engine_root,8));if not root then return nil,'localization root unavailable'end
  local engine=ptr(bridge.read(root+16,8));if not engine then return nil,'localization engine unavailable'end
  local target=ptr(bridge.read(engine+0x3e8,8));if not target then return nil,'localization function unavailable'end
  backend=backend or native()
  if not backend.executable(target)then return nil,'localization target is not an executable image'end
  local function valid()
   return bridge.verify()and ptr(bridge.read(bridge.engine_root,8))==root
    and ptr(bridge.read(root+16,8))==engine and ptr(bridge.read(engine+0x3e8,8))==target
    and backend.executable(target)
  end
  local cached={}
  return function(key)
   if type(key)~='number' or key%1~=0 or key<=0 or key>4294967295 then return nil end
   if not valid()then return nil end
   if cached[key]~=nil then return cached[key]or nil end
   local success,at=pcall(backend.lookup,target,key)
   if not success or type(at)~='number' or at<65536 or at>=140737488355328 then return nil end
   local chunks,offset={},0
   while offset<1024 do
    local text=bridge.read(at+offset,math.min(32,1024-offset))
    -- Reading a chunk can cross a page boundary; a readable terminator still
    -- counts, so fall back to one guarded byte rather than direct ffi.string.
    if type(text)~='string'or #text==0 then text=bridge.read(at+offset,1)end
    if type(text)~='string'or #text==0 then return nil end
    local stop=text:find('\0',1,true)
    if stop then
     chunks[#chunks+1]=text:sub(1,stop-1)
     if not valid()then return nil end
     local value=table.concat(chunks):gsub('[%c]',' ')
     if value==''or value:match('^#ID%[')then cached[key]=false;return nil end
     cached[key]=value;return value
    end
    chunks[#chunks+1]=text;offset=offset+#text
   end
   return nil
  end
 end)
 if not ok then return nil,'localization binding unavailable'end
 return result,reason
end
return M
