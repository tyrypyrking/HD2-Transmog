"""Session rotation and flushed bounded diagnostics never break the caller."""
from test_runtime import run_lua


def test_rotation_preserves_three_sessions_before_loader_truncates_current():
    run_lua(r'''
local D=dofile('src/diagnostics.lua')
local directory='C:/Users/Тест/Logs'
local memory={};local names={'HD2Transmog.log','HD2Transmog.previous.log','HD2Transmog.previous-2.log','HD2Transmog.previous-3.log'}
for i,name in ipairs(names)do memory[directory..'/'..name]='session'..i end
local writes,flushes={},0
local files={exists=function(p)return memory[p]~=nil end,copy=function(a,b)memory[b]=memory[a];return true end}
local loader={log_directory=directory,open_log=function(name)
 assert(memory[directory..'/'..names[2]]=='session1')
 memory[directory..'/'..name]=''
 return {write=function(_,line)writes[#writes+1]=line end,flush=function()flushes=flushes+1 end,close=function()end}
end}
local log=D.open(loader,files)
assert(memory[directory..'/'..names[4]]=='session3'and memory[directory..'/'..names[3]]=='session2')
log:report('native.begin','armor');log:report('native.returned','armor')
assert(flushes==2 and #writes==2)
assert(writes[1]:find('native.begin=armor [seq=1 utc=',1,true))
log:close();log:report('after.close',true);assert(flushes==2)
''')


def test_archive_and_write_failures_are_nonfatal_and_values_are_bounded():
    run_lua(r'''
local D=dofile('src/diagnostics.lua');local writes={}
local log=D.open({log_directory='C:/Logs',open_log=function()return {
 write=function(_,line)writes[#writes+1]=line end,flush=function()error('disk unavailable')end}end},
 {exists=function()error('archive unavailable')end})
log:report('bad',setmetatable({},{__tostring=function()error('bad value')end}))
log:report('long',string.rep('x',10000)..'\nforged=true')
assert(#writes==3 and writes[1]:find('log.archive_error',1,true))
assert(writes[2]:find('<unprintable>',1,true)and #writes[3]<2200)
log:report('single','a\nb\rc\0d');assert(not writes[4]:sub(1,-2):find('[\r\n%z]'))
D.open(nil):report('missing.loader',true)
D.open({open_log=function()error('cannot open')end}):report('missing.file',true)
''')


def test_log_limit_bounds_disk_writes():
    run_lua(r'''
local D=dofile('src/diagnostics.lua');local bytes,last=0,nil
local log=D.open({log_directory='C:/Logs',open_log=function()return {
 write=function(_,line)bytes=bytes+#line;last=line end,flush=function()end}end},
 {exists=function()return false end,copy=function()error('unexpected')end})
for i=1,5000 do log:report('event',string.rep('x',2048))end
assert(bytes<=8*1024*1024+100 and last:find('log.limit=',1,true))
local before=bytes;log:report('ignored',true);assert(bytes==before)
''')
