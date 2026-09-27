"""Section readiness retries and finite construction failures per Armory entry."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(code):
    result = subprocess.run(
        ['luajit', '-'], input="local Section=dofile('src/armory_section.lua')\n" + code,
        text=True, capture_output=True, cwd=ROOT, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_transient_readiness_has_cooldown_without_spending_construction_budget():
    run('''
local s=Section.new{retry_ms=250}
s:observe(0,{token='one',armor=true,ready=false});assert(not s:due(1000))
s:observe(1000,{token='one',armor=true,ready=true});assert(s:begin(1000))
for i=1,300 do
 local now=1000+(i-1)*250
 s:defer(now,'top selection pending')
 assert(not s:due(now+249)and s.failures==0)
 s:observe(now+250,{token='one',armor=true,ready=true})
 assert(s:begin(now+250))
end
s:complete(76250,{phase='active'});assert(s.phase=='active'and not s:due(100000))
''')


def test_unknown_observation_preserves_in_progress_or_failed_entry():
    run('''
local s=Section.new()
s:observe(0,{token='one',armor=true,ready=true});assert(s:begin(0))
local epoch=s.epoch
s:observe(1,{armor=nil});assert(s.phase=='preparing'and s.epoch==epoch)
s:observe(2,{token='one',armor=true,ready=true});assert(not s:due(2))
s:complete(2,{phase='restored',error='construction failed'})
assert(s.phase=='blocked'and s.failures==1)
for now=3,1000 do
 s:observe(now,{armor=nil})
 s:observe(now,{token='one',armor=true,ready=true})
 assert(not s:due(now)and s.epoch==epoch)
end
''')


def test_confirmed_tab_exit_and_reentry_rearms_even_with_reused_menu_token():
    run('''
local s=Section.new()
s:observe(0,{token='one',armor=true,ready=true});assert(s:begin(0))
s:complete(0,{phase='blocked'});assert(not s:due(10))
s:observe(10,{token='one',armor=false});assert(not s:due(10))
s:observe(20,{token='one',armor=true,ready=true})
assert(s:begin(20)and s.failures==0)
s:complete(20,{phase='active'})
s:observe(30,{token='two',armor=true,ready=true});assert(s:begin(30))
''')


def test_native_list_recreation_rearms_same_menu_and_readiness_change_does_not():
    run('''
local s=Section.new()
s:observe(0,{token='one',armor=true,ready=true,model_key='original'})
assert(s:begin(0));s:complete(0,{phase='active'});local epoch=s.epoch
s:observe(1,{token='one',armor=true,ready=false,model_key='original'})
s:observe(2,{token='one',armor=true,ready=true,model_key='original'})
assert(s.epoch==epoch and not s:due(2))
local result=s:observe(3,{token='one',armor=true,ready=true,model_key='replacement'})
assert(result.changed and s:begin(3))
s:complete(3,{phase='active'});s:invalidate(4,'native lease generation changed')
assert(s:begin(4))
''')


def test_failure_budget_is_per_entry_and_restore_failure_never_retries_itself():
    run('''
local s=Section.new{retry_ms=10,max_failures=2}
s:observe(0,{token='one',armor=true,ready=true});assert(s:begin(0))
s:complete(0,{phase='restored'});assert(not s:due(9)and s:begin(10))
s:complete(10,{phase='restored'});assert(s.phase=='blocked'and not s:due(1000))
s:observe(1000,{token='two',armor=true,ready=true});assert(s:begin(1000))
s:complete(1000,{phase='restore_failed'});assert(s.phase=='restore_failed')
assert(not s:defer(1001,'temporarily unreadable')and not s:due(10000))
''')


def test_long_session_has_no_global_menu_attempt_limit():
    run('''
local s=Section.new()
for i=1,600 do
 s:observe(i,{token='entry:'..i,armor=true,ready=true})
 assert(s:begin(i));s:complete(i,{phase='active'})
end
assert(s.phase=='active'and s.failures==0)
''')


def test_saved_variant_refresh_and_guard_pause_are_explicit():
    run('''
local s=Section.new()
s:observe(0,{token='one',armor=true,ready=true});assert(s:begin(0))
s:complete(0,{phase='active'});s:request(1);assert(s:begin(1))
s:complete(1,{phase='active'});s:pause('input capture refused')
assert(not s:due(1000))
s:observe(1000,{armor=nil});s:observe(1001,{token='one',armor=true,ready=true})
assert(not s:due(1001))
''')
