"""Tests for src/platform.lua (LuaJIT 5.1 host platform layer).

Windows FFI is not exercisable on Linux, so these tests drive the module
through its documented `natives` injection point: a Lua-side fake of the
kernel32/user32 surface plus a fake engine (stingray) table. Focus failure,
atomic preservation policy, and cursor->Gui mapping are covered; the real FFI
declarations are compile-checked only when a Windows host runs this suite.

Runner strategy mirrors tests/test_state.py: lupa if importable, else the
`luajit` binary via subprocess. Run:  python3 -m pytest tests/test_platform.py -q
"""

import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLATFORM_LUA = os.path.join(ROOT, "src", "platform.lua")

lupa = None
try:
    import lupa.luajit21 as lupa  # noqa: F401
except Exception:
    try:
        import lupa as lupa  # noqa: F401
    except Exception:
        lupa = None

if lupa is None and shutil.which("luajit") is None:
    pytest_skip = True
else:
    pytest_skip = False

import pytest  # noqa: E402

if pytest_skip:
    pytest.skip("no lupa and no luajit binary available", allow_module_level=True)


# The fake native surface + fake engine, executed inside Lua. CopyFileA /
# MoveFileExA are backed by real io/os so preservation semantics are exercised
# end-to-end against a temp directory.
FAKE_NATIVE_LUA = r"""
local tmp = ...
local nat = {}
-- POSIX directory reads differ between LuaJIT builds (nil vs empty string).
-- Inject a real read-error result for these Windows unreadable-file tests,
-- while keeping real temporary files for writes, backups and restoration.
nat.unreadable = {}
local real_open = io.open
io.open = function(path, mode)
    if nat.unreadable[path] and mode == 'rb' then
        return {read=function() return nil, 'Permission denied', 13 end,
                seek=function(_, origin) return origin == 'end' and 1 or 0 end,
                close=function() return true end}
    end
    return real_open(path, mode)
end
local function exists(p) local f = io.open(p, 'rb'); if f then f:close() return true end return false end
function nat.GetFileAttributesA(p) return exists(p) and 0x20 or 0xffffffff end
function nat.GetLastError() return nat.last_error or 2 end
function nat.CreateDirectoryA(d) os.execute('mkdir -p "' .. d .. '" 2>/dev/null') return 1 end
function nat.CopyFileA(src, dst, fail)
    if fail == 1 and exists(dst) then nat.last_error = 80 return 0 end
    if not exists(src) then nat.last_error = 2 return 0 end
    local f = io.open(src, 'rb'); if not f then nat.last_error = 5 return 0 end
    local data = f:read('*a'); f:close()
    local g = io.open(dst, 'wb'); if not g then nat.last_error = 5 return 0 end
    g:write(data); g:close()
    return 1
end
function nat.MoveFileExA(src, dst, flags)
    if not exists(src) then nat.last_error = 2 return 0 end
    if exists(dst) then os.remove(dst) end
    if os.rename(src, dst) then return 1 end
    nat.last_error = 5 return 0
end
-- user32/kernel32 focus + cursor surface
nat.own_pid = 4242
nat.fg_pid = 4242
nat.fg_window = 999
nat.cursor = { x = 10, y = 20 }
nat.client = { left = 0, top = 0, right = 1920, bottom = 1080 }
function nat.GetForegroundWindow() return nat.fg_window end
function nat.GetWindowThreadProcessId(win, out) out[0] = nat.fg_pid return 1 end
function nat.GetCurrentProcessId() return nat.own_pid end
function nat.GetCursorPos(out) out[0].x = nat.cursor.x out[0].y = nat.cursor.y return 1 end
function nat.ScreenToClient(win, out) return 1 end
function nat.GetClientRect(win, out)
    out[0].left = nat.client.left out[0].top = nat.client.top
    out[0].right = nat.client.right out[0].bottom = nat.client.bottom
    return 1
end
function nat.GetTickCount64() return nat.tick or 12345 end
-- the module reads the kernel32/user32 surfaces off these two fields
nat.kernel = nat
nat.user = nat
function nat.buffers()
    return { [0] = { x = 0, y = 0 } },
           { [0] = { left = 0, top = 0, right = 0, bottom = 0 } },
           { [0] = 0 }
end
return nat
"""

FAKE_ENGINE_LUA = r"""
local res = {...}
return {
    Gui = { resolution = function() return res[1], res[2] end },
    Mouse = {
        button_id = function(name) return name == 'left' and 7 or nil end,
        button = function(id) return res[3] end,
    },
}
"""


class Lua:
    """Runs a Lua snippet with platform.lua as P, natives as N, engine as E."""

    def __init__(self, tmpdir):
        self.tmpdir = tmpdir

    def run(self, code, engine=(1920, 1080, False)):
        loader = 'local loader = { log_directory = "%s" }' % (
            os.path.join(self.tmpdir, "logs").replace("\\", "/"))
        prelude = loader + "\n"
        natives = "local N = (function(...) local tmp = ... \n%s\nend)()" % FAKE_NATIVE_LUA
        eng = "local E = (function(...) local res = ...\n%s\nend)(%d, %d, %s)" % (
            FAKE_ENGINE_LUA, engine[0], engine[1], "true" if engine[2] else "false")
        body = (
            "local P = assert(dofile(%r))\n" % PLATFORM_LUA
            + "return (function(P, N, E, loader)\n" + code + "\nend)(P, N, E, loader)"
        )
        snippet = natives + "\n" + eng + "\n" + prelude + body
        if lupa is not None:
            rt = lupa.LuaRuntime(unpack_returned_tuples=True)
            fn = rt.execute("return function(code) return loadstring(code) end")
            chunk = fn(snippet)
            if chunk is None:
                raise AssertionError("lua syntax error")
            result = chunk()
        else:
            proc = subprocess.run(
                ["luajit", "-e", "local c=loadstring(io.read('*a'));assert(c) print(c())"],
                input=snippet.encode(), capture_output=True)
            if proc.returncode != 0:
                raise AssertionError("luajit failed:\n%s" % proc.stderr.decode())
            result = proc.stdout.decode()
        return result


@pytest.fixture
def env(tmp_path):
    return Lua(str(tmp_path))


# --------------------------------------------------------------------------- #
# safe_name: no traversal, strict charset
# --------------------------------------------------------------------------- #

def test_safe_name_policy(env):
    snippet = '''
local cases = {
    {'state.json', 'state.json'},
    {'a-b_C9.txt', 'a-b_C9.txt'},
    {'state.json.bak', nil},        -- second dot rejected
    {'', nil},
    {'.hidden', nil},
    {'no_ext', nil},
    {'a/b.json', nil},
    {'a\\\\b.json', nil},
    {'..', nil},
    {'a..b.json', nil},
    {'state json', nil},
    {'st\\195\\164te.json', nil},     -- non-ASCII byte rejected
    {'a.json\u00e4', nil},            -- trailing non-ASCII rejected
    {'a.json/', nil},
}
local failures = {}
for i, c in ipairs(cases) do
    local got = P.safe_name(c[1])
    if tostring(got) ~= tostring(c[2]) then
        failures[#failures+1] = string.format('%d:%s->%s', i, tostring(c[1]), tostring(got))
    end
end
return #failures == 0 and 'OK' or table.concat(failures, ';')
'''
    out = env.run(snippet)
    assert out.strip() == "OK", out


def test_directory_is_logdir_sibling(env):
    out = env.run('return P.new(loader, E, N).directory')
    assert out.strip().endswith("/logs/../Transmog")


# --------------------------------------------------------------------------- #
# map_cursor: client pixels -> Gui bottom-left coordinates
# --------------------------------------------------------------------------- #

def test_map_cursor_math(env):
    snippet = '''
local function fmt(x, y) return string.format('%.2f,%.2f', x, y) end
local function chk(desc, expected, ...)
    local x, y = ...
    assert(x, desc .. ': expected success, got nil')
    assert(fmt(x, y) == expected, desc .. ' got ' .. fmt(x, y) .. ' want ' .. expected)
end
chk('top-left', '0.00,1080.00', P.map_cursor(0, 0, 1920, 1080, 1920, 1080))
chk('center', '960.00,540.00', P.map_cursor(960, 540, 1920, 1080, 1920, 1080))
chk('bottom scaled', '0.00,2.00', P.map_cursor(0, 1080 - 1, 1920, 1080, 3840, 2160))
chk('resolution scale', '640.00,360.00', P.map_cursor(960, 540, 1920, 1080, 1280, 720))
-- rejections
assert(not P.map_cursor(1920, 5, 1920, 1080, 1920, 1080), 'x at width rejected')
assert(not P.map_cursor(5, -1, 1920, 1080, 1920, 1080), 'negative y rejected')
assert(not P.map_cursor(5, 5, 0, 1080, 1920, 1080), 'degenerate rect rejected')
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


# --------------------------------------------------------------------------- #
# sample_input: focus gating + cursor mapping + button contract
# --------------------------------------------------------------------------- #

def test_sample_input_focus_and_cursor(env):
    snippet = '''
local p = P.new(loader, E, N)
-- Focused own process, cursor at client top-left -> Gui bottom-left-ish.
local s = p.sample_input()
assert(s, 'expected a sample when focused')
assert(math.abs(s.x - 10 * 1920 / 1920) < 0.01, 'x=' .. s.x)
assert(math.abs(s.y - (1080 - 20) * 1080 / 1080) < 0.01, 'y=' .. s.y)
assert(s.down == false, 'down should be false from fake engine')
return 'OK'
'''
    out = env.run(snippet, engine=(1920, 1080, False))
    assert "OK" in out, out


def test_sample_input_focus_failure(env):
    snippet = '''
local p = P.new(loader, E, N)
N.fg_pid = 1111  -- foreground window belongs to another process
assert(p.sample_input() == nil, 'foreign foreground must yield nil')
N.fg_pid = N.own_pid
N.fg_window = nil
assert(p.sample_input() == nil, 'no foreground window must yield nil')
N.fg_window = 999
-- cursor outside client rect
N.cursor = { x = 5000, y = 20 }
assert(p.sample_input() == nil, 'cursor outside client must yield nil')
-- no engine / no Gui
assert(P.new(loader, nil, N).sample_input() == nil, 'nil engine must yield nil')
assert(P.new(loader, { Gui = {} }, N).sample_input() == nil, 'Gui without resolution must yield nil')
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


def test_sample_input_down_number_contract(env):
    snippet = '''
-- DiverKit evidence: down = value == true or (number and value > 0).
local p = P.new(loader, E, N)
return p.sample_input().down
'''
    assert "false" in env.run(snippet, engine=(1920, 1080, False))
    assert "true" in env.run(snippet, engine=(1920, 1080, True))


# --------------------------------------------------------------------------- #
# typed pointer injection: real FFI cdata buffers + explicit void* casts
# --------------------------------------------------------------------------- #

def test_sample_input_typed_pointer_injection(env):
    snippet = '''
-- Inject REAL LuaJIT cdata buffers and a real ffi table so the explicit
-- void* cast path (not the stub pass-through) is exercised.
local ok, ffi = pcall(require, 'ffi')
assert(ok, 'ffi required')
-- LuaJIT does not predefine the stdint typedefs; mirror build_natives()
pcall(ffi.cdef, 'typedef int int32_t;')
pcall(ffi.cdef, 'typedef struct { int32_t x, y; } CodexTestPoint;')
pcall(ffi.cdef, 'typedef struct { int32_t left, top, right, bottom; } CodexTestRect;')
N.ffi = ffi
N.buffers = function()
    return ffi.new('CodexTestPoint[1]'), ffi.new('CodexTestRect[1]'), ffi.new('uint32_t[1]')
end
-- The module now hands us void* casts (as the real Win32 API receives); the
-- fakes must cast back to the matching typed pointers to write through them.
N.GetForegroundWindow = function() return N.fg_window end
N.GetWindowThreadProcessId = function(win, out)
    ffi.cast('uint32_t *', out)[0] = N.fg_pid return 1
end
N.GetCursorPos = function(out)
    local p = ffi.cast('CodexTestPoint *', out)
    p[0].x = N.cursor.x p[0].y = N.cursor.y return 1
end
N.ScreenToClient = function(win, out) return 1 end
N.GetClientRect = function(win, out)
    local p = ffi.cast('CodexTestRect *', out)
    p[0].left = N.client.left p[0].top = N.client.top
    p[0].right = N.client.right p[0].bottom = N.client.bottom
    return 1
end
local p = P.new(loader, E, N)
N.cursor = { x = 100, y = 200 }
local s = p.sample_input()
assert(s, 'typed buffers must still sample')
assert(math.abs(s.x - 100) < 0.01 and math.abs(s.y - (1080 - 200)) < 0.01,
    string.format('got %s,%s', tostring(s.x), tostring(s.y)))
-- GetWindowThreadProcessId returning 0 must abort BEFORE the pid buffer is read
N.GetWindowThreadProcessId = function(win, out) return 0 end
assert(p.sample_input() == nil, 'zero tid must yield nil')
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


# --------------------------------------------------------------------------- #
# write_atomic: existing-but-unreadable primary is never replaced
# --------------------------------------------------------------------------- #

def test_write_atomic_never_replaces_unreadable_primary(env):
    snippet = '''
local function exists(p_) local g = io.open(p_, 'rb'); if g then g:close() return true end return false end
local p = P.new(loader, E, N)
local d = p.directory
-- establish a good generation pair so a known-good .bak exists
assert(p.write_atomic('state.json', '{"older":0}') == true)
assert(p.write_atomic('state.json', '{"good":1}') == true)
local f = io.open(d .. '/state.json.bak', 'rb')
assert(f and f:read('*a') == '{"older":0}', 'setup backup mismatch'); f:close()
-- swap the primary for an EXISTING but UNREADABLE object (a directory): the
-- fake GetFileAttributesA sees it as existing, the bounded read says read_error
os.remove(d .. '/state.json')
os.execute('mkdir -p "' .. d .. '/state.json" 2>/dev/null')
N.unreadable[d .. '/state.json'] = true
local w1, w2 = p.write_atomic('state.json', '{"v":9}')
assert(w1 == nil, 'must refuse to replace an unreadable primary')
assert(w2 == 'primary_unreadable', 'reason=' .. tostring(w2))
-- inaccessible primary preserved untouched for the caller; no temp litter
assert(exists(d .. '/state.json'), 'primary must survive')
assert(not exists(d .. '/state.json.tmp'), 'temp cleaned')
-- and the untouched .bak is still the last known-good generation
f = io.open(d .. '/state.json.bak', 'rb')
assert(f and f:read('*a') == '{"older":0}', 'bak untouched'); f:close()
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out

def test_write_atomic_happy_path_and_backup(env):
    snippet = '''
local function exists(p_) local g = io.open(p_, 'rb'); if g then g:close() return true end return false end
local p = P.new(loader, E, N)
local d = p.directory
assert(p.write_atomic('state.json', '{"v":1}') == true, 'first write failed')
local f = io.open(d .. '/state.json', 'rb')
assert(f and f:read('*a') == '{"v":1}', 'content mismatch'); f:close()
-- second write: current file readable -> .bak gets the previous content
assert(p.write_atomic('state.json', '{"v":2}') == true, 'second write failed')
f = io.open(d .. '/state.json.bak', 'rb')
assert(f and f:read('*a') == '{"v":1}', 'backup must hold previous content'); f:close()
assert(not exists(d .. '/state.json.tmp'), 'temp file must not survive')
-- verify read path too
local text = p.read('state.json')
assert(text == '{"v":2}', 'read mismatch: ' .. tostring(text))
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


def test_write_atomic_never_clobbers_bak_when_current_corrupt(env):
    snippet = '''
local p = P.new(loader, E, N)
local d = p.directory
-- two generations so a readable current file has produced a .bak
assert(p.write_atomic('state.json', '{"older":0}') == true)
assert(p.write_atomic('state.json', '{"good":1}') == true)
local f = io.open(d .. '/state.json.bak', 'rb')
assert(f and f:read('*a') == '{"older":0}', 'setup backup mismatch'); f:close()
-- Remove the current file: the 'absent' branch of the policy.
os.remove(d .. '/state.json')
-- .bak currently holds {"good":1}; a fresh write with current absent must NOT
-- silently overwrite the backup (preserve defaults to true).
assert(p.write_atomic('state.json', '{"v":2}') == true, 'write failed')
local f = io.open(d .. '/state.json.bak', 'rb')
assert(f, 'existing backup must survive')
assert(f:read('*a') == '{"older":0}', 'backup must not be clobbered'); f:close()
-- explicit preserve == false allows overwriting the stale backup
assert(p.write_atomic('state.json', '{"v":3}', false) == true)
f = io.open(d .. '/state.json.bak', 'rb')
assert(f and f:read('*a') == '{"v":2}', 'preserve=false must refresh backup'); f:close()
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


def test_write_atomic_failure_paths(env):
    snippet = '''
local function exists(p_) local g = io.open(p_, 'rb'); if g then g:close() return true end return false end
local p = P.new(loader, E, N)
-- bounded 1 MiB
assert(select(1, p.write_atomic('state.json', string.rep('x', 1024 * 1024 + 1))) == nil, 'size limit')
assert(select(2, p.write_atomic('state.json', string.rep('x', 1024 * 1024 + 1))) == 'too_large', 'reason')
assert(p.write_atomic('state.json', string.rep('x', 1024 * 1024)) == true, 'exactly 1 MiB must pass')
-- names are validated on write too
assert(select(1, p.write_atomic('../evil.json', 'x')) == nil, 'traversal name')
assert(select(2, p.write_atomic('bad name.json', 'x')) == 'bad_name', 'name reason')
assert(select(1, p.write_atomic('state.json', 5)) == nil, 'non-string text')
-- MoveFileExA failure aborts and cleans the temp file
local real_move = N.MoveFileExA
N.MoveFileExA = function() N.last_error = 5 return 0 end
assert(select(2, p.write_atomic('state.json', '{"x":1}')):match('replace_failed'), 'replace reason')
assert(not exists(p.directory .. '/state.json.tmp'), 'temp cleaned after replace failure')
N.MoveFileExA = real_move
-- missing read: an ACTUAL absent file must classify as 'missing' (the parent
-- main keys its boot-time decode on exactly this reason)
assert(select(2, p.read('nope.json')) == 'missing', 'missing reason')
-- an existing-but-unreadable target (a directory) is 'read_error', never a
-- successful empty read and never 'missing'
os.execute('mkdir -p "' .. p.directory .. '/not-a-file.json" 2>/dev/null')
N.unreadable[p.directory .. '/not-a-file.json'] = true
local dreason = select(2, p.read('not-a-file.json'))
assert(dreason == 'read_error', 'directory must be read_error: ' .. tostring(dreason))
-- oversized file via read path: > 1 MiB on disk -> too_large (bounded read)
local big = io.open(p.directory .. '/big.json', 'wb')
big:write(string.rep('x', 1024 * 1024 + 1)); big:close()
assert(select(2, p.read('big.json')) == 'too_large', 'oversized read reason')
assert(p.read('big.json') ~= 'too_large')
-- MoveFileExA must receive flags 0x9 (REPLACE_EXISTING|WRITE_THROUGH), not 0x5
local seen_flags = {}
N.MoveFileExA = function(src, dst, flags) seen_flags[#seen_flags+1] = flags
    return real_move(src, dst, flags) end
assert(p.write_atomic('state.json', '{"flags":1}') == true)
assert(#seen_flags >= 1 and seen_flags[#seen_flags] == 9,
    'flags=' .. tostring(seen_flags[#seen_flags]))
N.MoveFileExA = real_move
return 'OK'
'''
    out = env.run(snippet)
    assert "OK" in out, out


def test_now_ms(env):
    snippet = '''
local p = P.new(loader, E, N)
N.tick = 987654321
assert(p.now() == 987654321, 'now=' .. tostring(p.now()))
return 'OK'
'''
    assert "OK" in env.run(snippet)


def test_controller_a_works_with_cursor_outside_but_never_without_focus(env):
    out = env.run('''
local buttons=0
N.read_controller=function(index)if index==0 then return buttons end end
local p=P.new(loader,E,N)
N.cursor.x=-50
local s=p.sample_input();assert(s and s.x==-1 and not s.down and s.confirm_down==false)
buttons=4096;s=p.sample_input();assert(s.confirm_down and s.controller_source=='XInput0')
N.fg_pid=123;assert(p.sample_input()==nil)
N.fg_pid=N.own_pid;buttons=nil
assert(p.sample_input()==nil,'disconnected pad must not allow outside-cursor input')
return 'OK'
''', engine=(1920,1080,False))
    assert 'OK' in out
