"""Lua debug inbox contract simulations; no game process or live files touched."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which('luajit') is None, reason='LuaJIT is required')

PRELUDE = r'''
local Bridge = dofile('src/debug_bridge.lua')
local files, writes, reports = {}, {}, {}
local clock = 0
local fs = {
 read = function(name) return files[name] end,
 write_atomic = function(name, text)
  files[name] = text
  writes[#writes+1] = {name=name, text=text}
  return true
 end,
 now = function() return clock end,
}
local function report(key, value) reports[#reports+1] = {key=key,value=value} end
files['debug.enabled'] = 'HD2TM_DEBUG 1\n'
local bridge = assert(Bridge.new(fs, {Gui={text=function()end}, flag=true}, report))
local calls, received = 0, nil
local handlers = {
 inspect_api = function(args) calls=calls+1; received=args; return 'inspected' end,
 open_armory = function(args) calls=calls+1; received=args; return 'opened' end,
 explode = function() error('bad\nmessage\rtest') end,
 empty = function() return nil end,
 long_result = function() return string.rep('a', 2000) end,
}
local function request(id, command, args, token)
 return 'HD2TM_DEBUG_REQUEST 1\n'..(token or bridge.session)..'\n'..id..'\n'..command..'\n'..(args or '')
end
local function poll(text, advance)
 if text then files['debug.request']=text end
 clock=clock+(advance or 250)
 bridge:poll(handlers)
end
local function write_count(name)
 local count=0
 for _,w in ipairs(writes) do if w.name==name then count=count+1 end end
 return count
end
'''


def run_lua(script, prelude=True):
    result = subprocess.run(['luajit', '-'], input=(PRELUDE if prelude else '') + script,
                            text=True, capture_output=True, cwd=ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('marker', [None, '', 'true\n', 'HD2TM_DEBUG 1', 'HD2TM_DEBUG 2\n', 'HD2TM_DEBUG 1\nextra'])
def test_disabled_or_inexact_marker_has_no_side_effects(marker):
    marker_lua = 'nil' if marker is None else json.dumps(marker)
    run_lua('''
local Bridge=dofile('src/debug_bridge.lua')
local fs={read=function(name) assert(name=='debug.enabled');return MARKER end,
 write_atomic=function()error('disabled bridge wrote a file')end,
 now=function()error('disabled bridge read the clock')end}
assert(Bridge.new(fs,{},function()error('disabled bridge reported')end)==nil)
'''.replace('MARKER', marker_lua), prelude=False)


def test_session_published_and_current_nonce_acknowledged():
    run_lua(r'''
assert(files['debug.session']=='HD2TM_DEBUG_SESSION 1\n'..bridge.session..'\n')
assert(bridge.session:match('^[%w%-]+$'))
assert(files['debug-api.txt']:find('stingray.Gui.text function',1,true))
assert(files['debug-api.txt']:find('stingray.flag boolean',1,true))
poll(request('current-uuid','open_armory','{"equipment":true}'))
assert(calls==1 and received=='{"equipment":true}')
assert(files['debug.response']=='HD2TM_DEBUG_RESPONSE 1\n'..bridge.session..'\ncurrent-uuid\nok\nopened\n')
assert(reports[#reports].key=='debug.open_armory')
assert(reports[#reports].value=='ok: opened')
''')


def test_duplicate_request_ignored_after_ack():
    run_lua(r'''
poll(request('duplicate-uuid','open_armory'))
local ack=files['debug.response'];local count=write_count('debug.response')
poll(nil);poll(nil)
assert(calls==1)
assert(files['debug.response']==ack and write_count('debug.response')==count)
''')


def test_previous_launch_token_is_ignored_without_poisoning_current_request():
    run_lua(r'''
poll(request('same-id','open_armory','','old-launch-123'))
assert(calls==0 and files['debug.response']==nil)
poll(request('same-id','open_armory'))
assert(calls==1 and files['debug.response']:find('\nsame-id\nok\n',1,true))
''')


@pytest.mark.parametrize('command,fragment', [
    ('not_allowlisted','Unknown debug command'),
    ('explode','bad message test'),
    ('empty','Command did not return a result'),
])
def test_unknown_and_failing_handler_return_bounded_error_ack(command, fragment):
    run_lua(r'''
poll(request('failure-id',COMMAND))
local ack=assert(files['debug.response'])
assert(ack:find('\nfailure-id\nerror\n',1,true),ack)
assert(ack:find(FRAGMENT,1,true),ack)
local _,newlines=ack:gsub('\n','');assert(newlines==5,ack)
assert(calls==0)
'''.replace('COMMAND', json.dumps(command)).replace('FRAGMENT', json.dumps(fragment)))


def test_oversized_request_ignored_and_exact_limit_accepted():
    run_lua(r'''
local header=request('size-id','inspect_api')
poll(header..string.rep('x',2049-#header))
assert(calls==0 and files['debug.response']==nil)
poll(header..string.rep('x',2048-#header))
assert(calls==1 and #received==2048-#header)
''')


def test_long_id_and_malformed_request_are_ignored():
    run_lua(r'''
poll(request(string.rep('x',81),'open_armory'))
assert(calls==0 and files['debug.response']==nil)
poll('HD2TM_DEBUG_REQUEST 2\n'..bridge.session..'\na\nopen_armory\n')
assert(calls==0 and files['debug.response']==nil)
poll(request('valid-id','open_armory'))
assert(calls==1)
''')


def test_poll_is_rate_limited():
    run_lua(r'''
poll(request('one','open_armory'))
poll(request('two','open_armory'),1)
assert(calls==1)
poll(nil,249)
assert(calls==2)
''')


def test_response_payload_is_truncated_to_protocol_limit():
    run_lua(r'''
poll(request('long-result','long_result'))
local text=assert(files['debug.response']):match('\nok\n([^\n]*)\n$')
assert(#text==1000)
''')


def test_nonconsecutive_duplicate_ids_are_never_replayed():
    run_lua(r'''
poll(request('request-a','open_armory'))
poll(request('request-b','open_armory'))
local before=write_count('debug.response')
poll(request('request-a','open_armory'))
assert(calls==2)
assert(write_count('debug.response')==before)
''')


def test_session_command_budget_prevents_unbounded_seen_set():
    run_lua(r'''
for i=1,1024 do poll(request('request-'..i,'inspect_api'))end
assert(calls==1024)
poll(request('over-budget','open_armory'))
assert(calls==1024)
''')
