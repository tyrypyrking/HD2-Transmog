-- Flushed event checkpoints and three retained sessions, following DiverKit's
-- loader-log convention. Diagnostics must never interrupt gameplay.
local M={}
local names={'HD2Transmog.log','HD2Transmog.previous.log','HD2Transmog.previous-2.log','HD2Transmog.previous-3.log'}
function M.rotate(directory,files)
 assert(type(directory)=='string'and #directory>0 and not directory:find('\0',1,true),'log directory unavailable')
 for i=#names-1,1,-1 do
  local source=directory..'/'..names[i]
  if files.exists(source)then assert(files.copy(source,directory..'/'..names[i+1]),'log archive copy failed')end
 end
end
local function native_files(directory)
 local ffi=require('ffi')
 for _,decl in ipairs({
  'int MultiByteToWideChar(unsigned int,unsigned long,const char*,int,uint16_t*,int);',
  'uint32_t GetFileAttributesW(const uint16_t*);',
  'int CopyFileW(const uint16_t*,const uint16_t*,int);','uint32_t GetLastError(void);',
 })do pcall(ffi.cdef,decl)end
 local kernel=ffi.load('kernel32');local cp=65001
 if kernel.MultiByteToWideChar(cp,8,directory,#directory,nil,0)==0 then
  assert(tonumber(kernel.GetLastError())==1113,'log path encoding unavailable');cp=0
 end
 local function wide(value)
  local n=kernel.MultiByteToWideChar(cp,8,value,#value,nil,0);assert(n>0,'log path conversion failed')
  local out=ffi.new('uint16_t[?]',n+1)
  assert(kernel.MultiByteToWideChar(cp,8,value,#value,out,n)==n,'log path conversion failed');return out
 end
 return {exists=function(path)
  if tonumber(kernel.GetFileAttributesW(wide(path)))~=4294967295 then return true end
  local err=tonumber(kernel.GetLastError());assert(err==2 or err==3,'log archive inspection failed');return false
 end,copy=function(from,to)return kernel.CopyFileW(wide(from),wide(to),0)~=0 end}
end
function M.open(loader,files)
 local file,archive_error
 local archived,why=pcall(function()
  assert(loader and loader.log_directory,'log directory unavailable')
  M.rotate(loader.log_directory,files or native_files(loader.log_directory))
 end)
 if not archived then archive_error=why end
 pcall(function()if loader and type(loader.open_log)=='function'then file=loader.open_log(names[1])end end)
 local self={};local sequence,bytes,limited=0,0,false
 function self:report(key,value)
  pcall(function()
   if not file or limited then return end
   local function render(v)
    local ok,text=pcall(tostring,v)
    return (ok and text or '<unprintable>'):gsub('[\r\n%z]',' '):sub(1,2048)
   end
   sequence=sequence+1
   local line=render(key)..'='..render(value)..' [seq='..sequence..' utc='..os.time()..']\n'
   if bytes+#line>8*1024*1024 then line='log.limit=8 MiB session limit reached\n';limited=true end
   file:write(line);file:flush();bytes=bytes+#line
  end)
 end
 function self:close()pcall(function()if file then file:close()end end);file=nil end
 if archive_error then self:report('log.archive_error',archive_error)end
 return self
end
return M
