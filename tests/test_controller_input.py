"""Read-only pad selection and disconnect observations."""
from test_runtime import run_lua


def test_xinput_a_across_slots_and_disconnect_never_fabricates_release():
    run_lua(r'''
local M=dofile('src/controller_input.lua')
local pads={[2]=0};local calls={};local now=0
local read=M.new(nil,function(i)calls[#calls+1]=i;return pads[i]end,function()return now end)
local s=read();assert(s.controller_source=='XInput2'and s.confirm_down==false)
pads[2]=4096;assert(read().confirm_down)
pads[2]=8192;assert(not read().confirm_down)
pads[2]=nil;pads[0]=4096
assert(read()==nil,'disconnect must not synthesize release or change device in-frame')
now=250;s=read();assert(s.controller_source=='XInput0'and s.confirm_down)
''')


def test_missing_or_malformed_controller_is_optional():
    run_lua(r'''
local M=dofile('src/controller_input.lua')
assert(M.new(nil)()==nil)
for _,bad in ipairs({-1,65536,0.5,'4096',false})do
 local read=M.new(nil,function()return bad end);assert(read()==nil)
end
assert(M.new(nil,function()error('disconnected')end)()==nil)
''')


def test_disconnected_slots_are_scanned_at_most_four_times_per_second():
    run_lua(r'''
local M=dofile('src/controller_input.lua')
local now,calls,buttons=0,0,nil
local read=M.new(nil,function(index)calls=calls+1;if index==0 then return buttons end end,function()return now end)
for t=0,999 do now=t;assert(read()==nil)end
assert(calls==16,'disconnected controller discovery ran every frame')
buttons=4096;now=1000;assert(read().confirm_down)
buttons=0;assert(read().confirm_down==false,'connected controller input was throttled')
buttons=4096;assert(read().confirm_down,'connected button press was delayed')
''')


def test_clock_failure_or_rollback_cannot_synthesize_a_release():
    run_lua(r'''
local M=dofile('src/controller_input.lua');local now=100
local read=M.new(nil,function()return 4096 end,function()return now end)
assert(read().confirm_down);now=0;assert(read()==nil);assert(read().confirm_down)
now=0/0;assert(read()==nil)
''')


def test_xinput_navigation_buttons_and_stick_are_reported_with_dpad_priority():
    run_lua(r'''
local M=dofile('src/controller_input.lua')
local input={buttons=8192+32768+256+512+2+8,lx=-32768,ly=32767}
local read=M.new(nil,function()return input end,function()return 0 end)
local v=read()
assert(v.back_down and v.cancel_down and v.page_prev_down and v.page_next_down and not v.confirm_down)
assert(v.nav_x==1 and v.nav_y==-1)
input={buttons=0,lx=-32768,ly=16384};v=read();assert(v.nav_x==-1 and v.nav_y>.49 and v.nav_y<.51)
input={buttons=0,lx=0/0,ly=90000};v=read();assert(v.nav_x==0 and v.nav_y==0)
''')


def test_idle_first_pad_does_not_hide_a_second_controller_and_release_stays_on_source():
    run_lua(r'''
local M=dofile('src/controller_input.lua');local pads={[0]=0,[1]=0};local now=0
local read=M.new(nil,function(i)return pads[i]end,function()return now end)
assert(read().controller_source=='XInput0')
pads[1]=2;assert(read().controller_source=='XInput1')
pads[1]=0;assert(read().controller_source=='XInput1')
pads[1]=4096;assert(read().confirm_down)
pads[0]=4096;pads[1]=0
local release=read();assert(release.controller_source=='XInput1'and not release.confirm_down)
assert(read().controller_source=='XInput0')
''')
