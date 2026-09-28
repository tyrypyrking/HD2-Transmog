-- Read-only XInput creator navigation and confirmation. Steam Input pads work here too.
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
  return {buttons=tonumber(buffer[0].buttons),lx=tonumber(buffer[0].lx),ly=tonumber(buffer[0].ly)}
 end
end
function M.new(ffi,reader,clock)
 reader=reader or native_reader(ffi)
 clock=clock or function()return os.clock()*1000 end
 local current,next_scan,last_time=nil,0,nil
 local connected={};local was_active=false
 local function read(index)
  local ok,value=pcall(reader,index)
  local bits=type(value)=='table'and value.buttons or value
  if not ok or type(bits)~='number'or bits%1~=0 or bits<0 or bits>65535 then return nil end
  local function button(mask)return math.floor(bits/mask)%2==1 end
  local function axis(v)
   if type(v)~='number'or v~=v or v%1~=0 or v< -32768 or v>32767 then return 0 end
   return v/(v<0 and 32768 or 32767)
  end
  local x=type(value)=='table'and axis(value.lx)or 0
  local y=type(value)=='table'and axis(value.ly)or 0
  if button(4)or button(8)then x=(button(8)and 1 or 0)-(button(4)and 1 or 0)end
  if button(1)or button(2)then y=(button(1)and 1 or 0)-(button(2)and 1 or 0)end
  return {controller_source='XInput'..index,confirm_down=button(4096),back_down=button(8192),
   cancel_down=button(32768),page_prev_down=button(256),page_next_down=button(512),nav_x=x,nav_y=y}
 end
 return function()
  if not reader then return nil end
  local ok,now=pcall(clock)
  if not ok or type(now)~='number'or now~=now or now<0 or now==math.huge then return nil end
  if last_time and now<last_time then current=nil;next_scan=now;last_time=now;return nil end
  last_time=now
  local states={}
  local function active(state)
   return state and (state.confirm_down or state.back_down or state.cancel_down
    or state.page_prev_down or state.page_next_down or math.abs(state.nav_x)>.55 or math.abs(state.nav_y)>.55)
  end
  if current~=nil then
   states[current]=read(current)
   if not states[current]then
    connected[current]=nil;current=nil;was_active=false;next_scan=now+250;return nil
   end
  end
  if now>=next_scan then
   next_scan=now+250
   for index=0,3 do
    local state=states[index]or read(index)
    states[index]=state;connected[index]=state~=nil or nil
   end
  else
   for index in pairs(connected)do
    if index~=current then states[index]=read(index);if not states[index]then connected[index]=nil end end
   end
  end
  -- Preserve the active pad's release frame. The UI resets its gesture when
  -- the source changes, so another pad can never complete an armed A press.
  if not current or not active(states[current])and not was_active then
   for index=0,3 do if active(states[index])then current=index;break end end
  end
  if not current then for index=0,3 do if states[index]then current=index;break end end end
  local state=current~=nil and states[current]or nil
  was_active=active(state)==true
  return state
 end
end
return M
