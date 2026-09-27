"""Writer phase authorization checks with a fake Win32 boundary; no real writes."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_recovery_bypasses_ownership_only_and_keeps_session_identity_guards():
    script = '''
local old_ffi=package.loaded.ffi
package.loaded.ffi={
 cdef=function()end,
 new=function()return {}end,
 load=function(name)
  assert(name=='kernel32')
  return {GetCurrentProcess=function()return 'current_process'end,
   VirtualQuery=function()error('unexpected memory query')end,
   WriteProcessMemory=function()error('unexpected native write')end}
 end,
}
local code_fresh,session_fresh,owned=true,true,true
local checks=0
local bridge={read=function()error('unexpected read')end,verify=function()return code_fresh end}
local observation={
 verify_session=function()return session_fresh end,
 verify_owned=function(ids)
  checks=checks+1
  assert(#ids==2 and ids[1]=='appearance-donor' and ids[2]=='stat-donor')
  return owned
 end,
}
local writer=dofile('src/runtime_writer.lua').new(bridge,observation)
package.loaded.ffi=old_ffi
local function allowed(phase,result)
 return writer.verify(result or observation,{},'appearance-donor','stat-donor',phase)
end
for _,phase in ipairs({'plan','apply','readback'})do assert(allowed(phase))end
assert(checks==3)
owned=false
for _,phase in ipairs({'plan','apply','readback'})do assert(not allowed(phase))end
assert(checks==6)
-- Ownership loss must not strand a reversible appearance patch.
assert(allowed('rollback') and allowed('reset') and checks==6)
-- Recovery is still forbidden after identity, code, or session evidence changes.
for _,phase in ipairs({'plan','apply','readback','rollback','reset'})do
 assert(not allowed(phase,{}))
 code_fresh=false;assert(not allowed(phase));code_fresh=true
 session_fresh=false;assert(not allowed(phase));session_fresh=true
end
assert(checks==6)
-- Public boundary rejects unexpected write lengths before touching native APIs.
assert(not writer.write(100000,'12'))
assert(not writer.write(100000,string.rep('x',24)))
'''
    process = subprocess.run(['luajit','-'], input=script, cwd=ROOT,
                             text=True, capture_output=True, timeout=10)
    assert process.returncode == 0, process.stdout + process.stderr


def test_private_variant_buffers_survive_gc_and_perk_writes_are_four_bytes():
    script = r'''
local real=require('ffi')
local captured
local kernel={GetCurrentProcess=function()return 1 end,
 VirtualQuery=function(at,out,n)
  assert(n==48)
  real.cast('uint64_t*',out)[0]=real.cast('uintptr_t',at)
  real.cast('uint64_t*',out)[3]=4096
  real.cast('uint32_t*',out)[8]=4096
  real.cast('uint32_t*',out)[9]=4
  return 48
 end,
 WriteProcessMemory=function(_,at,bytes,n,written)
  assert(tonumber(real.cast('uintptr_t',at))==100000)
  captured=real.string(bytes,n);written[0]=n;return 1
 end}
package.loaded.ffi=setmetatable({load=function()return kernel end},{__index=real})
local verified
local observation={verify_session=function()return true end,verify_owned=function(ids)verified=ids;return true end}
local writer=dofile('src/runtime_writer.lua').new({read=function()end,verify=function()return true end},observation)
package.loaded.ffi=real
local first=assert(writer.allocate('private piece bytes'))
local address=first.address;first=nil
collectgarbage();collectgarbage()
assert(real.string(real.cast('const char*',address),19)=='private piece bytes')
local repeated=assert(writer.allocate('private piece bytes'));assert(repeated.address==address)
local different=assert(writer.allocate('different data'));assert(different.address~=address)
assert(not writer.allocate(''));assert(not writer.allocate(string.rep('x',65537)))
assert(writer.write(100000,string.char(7,0,0,0)))
assert(captured==string.char(7,0,0,0),'passive word write changed width')
assert(writer.verify(observation,{},'look','stats','apply',{'look','stats','perk'}))
assert(#verified==3 and verified[3]=='perk','perk donor omitted from fresh authorization')
'''
    process = subprocess.run(['luajit','-'],input=script,cwd=ROOT,text=True,capture_output=True,timeout=10)
    assert process.returncode==0,process.stdout+process.stderr
