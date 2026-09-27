"""Exercise the real backend's FFI parsing past the historical CType limit."""
from test_native_grid import FIXTURE, run_lua


def test_native_select_backend_reuses_types_for_seventy_thousand_frames():
    # Keep real ffi.cast/type parsing, but never invoke a Windows address.
    # The prior anonymous string cast exhausts real LuaJIT CType storage at
    # approximately13,000 iterations; the retained CType survives70,000.
    run_lua(r'''
local real_cast=ffi.cast
local invocations=0
ffi.load=function(name)
 assert(name=='kernel32')
 return {VirtualQuery=function(_,info,n)
  assert(n==48);ffi.fill(info,48);ffi.copy(info+32,b(4096,4)..b(32,4),8);return 48
 end}
end
ffi.cast=function(kind,value)
 local parsed=real_cast(kind,value)
 if tostring(kind):find('(*)',1,true)then
  return function()invocations=invocations+1 end
 end
 return parsed
end
local grid_backend=G.new(bridge)
assert(ready(grid_backend)=='ready')
for i=1,70000 do
 local ok,why=grid_backend:consume_select()
 assert(ok,'frame '..i..': '..tostring(why))
end
assert(invocations==70000)
''')
