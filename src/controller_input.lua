-- Read-only XInput confirmation. Steam Input exposes supported pads here too.
-- Device changes/disconnects are observations, never synthetic button releases.
local M={}
local function native_reader(ffi)
 if not ffi then return nil end
 local lib,buffer,arg
 local ok=pcall(function()
  pcall(ffi.cdef,'typedef struct { uint32_t packet; uint16_t buttons; uint8_t lt,rt; int16_t lx,ly,rx,ry; } HD2TransmogPadState;')
  pcall(ffi.cdef,'uint32_t XInputGetState(uint32_t,void*);')
  for _,name in ipairs({'xinput1_4','xinput1_3','xinput9_1_0'})do
   local loaded,value=pcall(ffi.load,name)
   if loaded and pcall(function()assert(value.XInputGetState)end)then lib=value;break end
  end
  if lib then buffer=ffi.new('HD2TransmogPadState[1]');arg=ffi.cast('void*',buffer)end
 end)
 if not ok or not lib then return nil end
 return function(index)
  if lib.XInputGetState(index,arg)~=0 then return nil end
  return tonumber(buffer[0].buttons)
 end
end
function M.new(ffi,reader,clock)
 reader=reader or native_reader(ffi)
 clock=clock or function()return os.clock()*1000 end
 local current,next_scan,last_time=nil,0,nil
 local function read(index)
  local ok,bits=pcall(reader,index)
  if not ok or type(bits)~='number'or bits%1~=0 or bits<0 or bits>65535 then return nil end
  return {controller_source='XInput'..index,confirm_down=math.floor(bits/4096)%2==1}
 end
 return function()
  if not reader then return nil end
  local ok,now=pcall(clock)
  if not ok or type(now)~='number'or now~=now or now<0 or now==math.huge then return nil end
  if last_time and now<last_time then current=nil;next_scan=now;last_time=now;return nil end
  last_time=now
  if current~=nil then
   local state=read(current)
   if state then return state end
   current=nil;next_scan=now+250;return nil
  end
  if now<next_scan then return nil end
  next_scan=now+250
  for index=0,3 do
   local state=read(index)
   if state then current=index;return state end
  end
 end
end
return M
