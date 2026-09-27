-- platform.lua — HD2 Transmog host platform layer (LuaJIT 5.1, FFI optional)
--
-- Thin adapter between the parent addon and the host: file storage under the
-- loader's log directory sibling, focus/cursor sampling via user32, and
-- monotonic time. NO game hooks, NO game memory access, NO global input hooks.
-- The only game-side surface is the optional `engine` (stingray) table for
-- Gui.resolution and Mouse.button — validated before use.
--
-- ============================================================================
-- API CONTRACT
-- ============================================================================
--
-- local platform = dofile("src/platform.lua")
--
-- platform.MAX_STATE_BYTES -> 1024*1024
-- platform.safe_name(name) -> name | nil, reason
--   Name policy: [A-Za-z0-9_-]+ '.' [A-Za-z0-9_-]+ (single dot, no traversal,
--   no spaces, no unicode). This guards every path we ever build.
--
-- platform.map_cursor(cx, cy, w, h, rw, rh) -> x, y | nil, reason
--   Pure coordinate mapping: client-rect pixel (cx,cy) in a w*h client area
--   to Gui.resolution (rw,rh) space with a BOTTOM-LEFT origin (Gui convention,
--   matching DiverKit Pointer.sample). Rejects degenerate rects/out-of-client.
--
-- platform.new(loader, engine?, natives?) -> platform
--   loader : { log_directory = string }  (loader ACP encoding, as supplied)
--   engine : optional stingray table; defaults to rawget(_G, 'stingray')
--   natives: optional injection point for tests (real FFI built when omitted).
--            Table with kernel32/user32-shaped functions + optional
--            `ffi` + `buffers()` for the POINT/RECT/pid scratch objects.
--   platform = {
--     directory  -> loader.log_directory .. '/../Transmog'  (for diagnostics)
--     read(name)      -> text | nil, reason   -- reason in a small closed set
--     write_atomic(name, text, preserve?) -> true | nil, reason
--     sample_input()  -> {x=, y=, down=} | nil  -- nil when not focused/in-client
--     now()           -> milliseconds (GetTickCount64, monotonic-ish)
--   }
--
-- write_atomic(name, text, preserve):
--   1. name validated (see safe_name), |text| <= MAX_STATE_BYTES (1 MiB).
--   2. Temp file written in the SAME directory (state.tmp): every io.open /
--      write / flush / close result is checked; any failure removes the temp.
--   3. Temp is read back and must equal `text` (verify), else abort.
--   4. Classify the current file: readable -> copied to state.bak via
--      CopyFileA. ABSENT -> the existing .bak is NOT silently overwritten
--      unless preserve == false (the last known-good backup is the recovery
--      path). EXISTS BUT UNREADABLE -> abort with nil, 'primary_unreadable'
--      WITHOUT replacing the target: an inaccessible primary is preserved for
--      the caller to inspect; content decode remains the caller's job.
--   5. MoveFileExA(temp, target, REPLACE_EXISTING|WRITE_THROUGH == 0x9).
--   When kernel32 cannot be loaded (FFI unavailable on this host), write_atomic
--   degrades to a best-effort os.rename and returns nil, 'unsupported' on
--   failure; read() works via io and is unaffected.
--
-- FFI declarations are made one-per-pcall with CodexTransmog-prefixed typedef
-- names so a collision with another addon's earlier cdef cannot abort us; all
-- struct pointers are explicitly cast to void * at call sites (LuaJIT treats
-- same-layout structs from other cdefs as distinct types).
--
-- Mouse evidence (vendor/DiverKit-reference/loadouts.lua, Pointer.new ~1981):
--   local mouse = assert(engine.Mouse, 'Mouse unavailable')
--   local left  = mouse.button_id('left')
--   local value = mouse.button(left)
--   down = value == true or (type(value) == 'number' and value > 0)
-- This module mirrors exactly that contract, but tolerates a missing/broken
-- engine.Mouse by returning down=false instead of erroring.

local M = {}

M.MAX_STATE_BYTES = 1024 * 1024
M.STATE_NAME = 'state.json'

-- Explicit ASCII classes: %w is locale-dependent under some C locales and
-- could admit non-ASCII "letters"; the name policy must be exactly ASCII.
local NAME_RE = '^[A-Za-z0-9_-]+%.[A-Za-z0-9_-]+$'
function M.safe_name(name)
    if type(name) ~= 'string' then return nil, 'bad_name_type' end
    if not name:match(NAME_RE) then return nil, 'bad_name' end
    return name
end

function M.map_cursor(cx, cy, w, h, rw, rh)
    if not (w > 0 and h > 0 and rw > 0 and rh > 0) then return nil, 'degenerate' end
    if not (cx >= 0 and cy >= 0 and cx < w and cy < h) then return nil, 'outside' end
    -- Top-left client pixels -> bottom-left Gui units (DiverKit convention).
    return cx * rw / w, (h - cy) * rh / h
end

-- ---------------------------------------------------------------------------
-- FFI natives (lazy; individually pcall'd cdefs; void* casts at call sites)
-- ---------------------------------------------------------------------------

local function build_natives()
    local ok, ffi = pcall(require, 'ffi')
    if not ok then return nil end
    local decls = {
        -- LuaJIT does not reliably predefine the stdint typedefs; declare them
        -- first (dupes from other addons are fine under pcall).
        'typedef signed char int8_t;',
        'typedef short int16_t;',
        'typedef int int32_t;',
        'typedef long long int64_t;',
        'typedef unsigned char uint8_t;',
        'typedef unsigned short uint16_t;',
        'typedef unsigned int uint32_t;',
        'typedef unsigned long long uint64_t;',
        'typedef uintptr_t size_t;',
        'typedef long intptr_t;',
        'typedef unsigned long uintptr_t;',
        'typedef struct { int32_t x, y; } CodexTransmogPoint;',
        'typedef struct { int32_t left, top, right, bottom; } CodexTransmogRect;',
        'int CreateDirectoryA(const char*, void*);',
        'int CopyFileA(const char*, const char*, int);',
        'int MoveFileExA(const char*, const char*, uint32_t);',
        'uint32_t GetFileAttributesA(const char*);',
        'uint32_t GetLastError(void);',
        'uint64_t GetTickCount64(void);',
        'void *GetForegroundWindow(void);',
        'uint32_t GetWindowThreadProcessId(void*, void*);',
        'uint32_t GetCurrentProcessId(void);',
        'int GetCursorPos(void*);',
        'int ScreenToClient(void*, void*);',
        'int GetClientRect(void*, void*);',
    }
    for _, d in ipairs(decls) do pcall(ffi.cdef, d) end  -- first prototype wins; dupes are fine
    local kok, kernel = pcall(ffi.load, 'kernel32')
    if not kok then return nil end
    local uok, user = pcall(ffi.load, 'user32')
    local INVALID = ffi.cast('void *', ffi.cast('intptr_t', -1))
    return {
        ffi = ffi,
        kernel = kernel,
        user = uok and user or nil,
        invalid = INVALID,
        buffers = function()
            local pb, rb, idb = { [0] = { x = 0, y = 0 } },
                { [0] = { left = 0, top = 0, right = 0, bottom = 0 } }, { [0] = 0 }
            pcall(function() pb = ffi.new('CodexTransmogPoint[1]') end)
            pcall(function() rb = ffi.new('CodexTransmogRect[1]') end)
            pcall(function() idb = ffi.new('uint32_t[1]') end)
            return pb, rb, idb
        end,
    }
end

local MISSING_ATTR = 0xffffffff
local ERROR_ALREADY_EXISTS = 183
local ERROR_FILE_NOT_FOUND = 2
-- MOVEFILE_REPLACE_EXISTING (0x1) | MOVEFILE_WRITE_THROUGH (0x8) == 0x9.
-- (0x4 is MOVEFILE_COPY_ALLOWED, not write-through.)
local MOVE_FLAGS = 0x9

-- ---------------------------------------------------------------------------

function M.new(loader, engine, natives)
    assert(type(loader) == 'table' and type(loader.log_directory) == 'string' and #loader.log_directory > 0,
        'loader.log_directory required')
    engine = engine or rawget(_G, 'stingray')
    natives = natives or build_natives()

    local directory = loader.log_directory .. '/../Transmog'
    local kernel, user = natives and natives.kernel or nil, natives and natives.user or nil
    local point, rect, idbuf = nil, nil, nil
    if natives and natives.buffers then point, rect, idbuf = natives.buffers() end

    local function path(name)
        local ok, why = M.safe_name(name)
        assert(ok, why)
        return directory .. '/' .. name
    end

    local function win_ok(fn, ...)
        local r = fn(...)
        return tonumber(r) ~= 0
    end

    local self = { directory = directory }

    -- -- read ----------------------------------------------------------------

    function self.read(name)
        local ok, why = M.safe_name(name)
        if not ok then return nil, why end
        -- io.open returns (nil, "path: message", errno): classify on the errno,
        -- falling back to the message text when no errno is supplied.
        local f, err, errno = io.open(path(name), 'rb')
        if not f then
            if errno == ERROR_FILE_NOT_FOUND
                or errno == nil and type(err) == 'string'
                and err:find('No such file or directory', 1, true) then
                return nil, 'missing'
            end
            -- anything else (permissions, sharing violation, ...) is not missing
            return nil, 'read_error'
        end
        -- Bound the read: stat the size first, then read at most one byte more
        -- than the limit so an oversized state file is detected without
        -- slurping unbounded input.
        local size = f:seek('end')
        if not size then f:close() return nil, 'read_error' end
        if size > M.MAX_STATE_BYTES then f:close() return nil, 'too_large' end
        f:seek('set')
        local text = f:read(M.MAX_STATE_BYTES + 1)
        local closed = f:close()
        if not closed then return nil, 'read_error' end
        if not text then
            -- EOF: only a legitimate empty read. A nonzero-size object whose
            -- bytes cannot be read (e.g. a directory that fopen accepted) is
            -- an error, not an empty state.
            if size > 0 then return nil, 'read_error' end
            text = ''
        end
        return text
    end

    -- -- write_atomic ---------------------------------------------------------

    function self.write_atomic(name, text, preserve)
        local ok, why = M.safe_name(name)
        if not ok then return nil, why end
        if type(text) ~= 'string' then return nil, 'bad_text' end
        if #text > M.MAX_STATE_BYTES then return nil, 'too_large' end

        local base = path(name)
        local target, temp, backup = base, base .. '.tmp', base .. '.bak'

        if kernel then
            if not win_ok(kernel.CreateDirectoryA, directory, nil) then
                local e = tonumber(kernel.GetLastError())
                if e ~= ERROR_ALREADY_EXISTS then return nil, 'mkdir_' .. e end
            end
        end

        -- 2. bounded temp write in the same directory; every step checked.
        local f = io.open(temp, 'wb')
        if not f then return nil, 'tmp_open_failed' end
        local written = f:write(text)
        local flushed = written and f:flush()
        local closed = flushed and f:close()
        if not (written and flushed and closed) then
            pcall(f.close, f)
            os.remove(temp)
            return nil, 'write_failed'
        end

        -- 3. read-back verify.
        do
            local rf = io.open(temp, 'rb')
            if not rf then os.remove(temp) return nil, 'verify_open_failed' end
            local data = rf:read(M.MAX_STATE_BYTES + 1)
            rf:close()
            if data ~= text then os.remove(temp) return nil, 'verify_failed' end
        end

        -- 4. Classify the current file BEFORE touching anything:
        --    - readable            -> refresh .bak from it (CopyFileA)
        --    - absent              -> leave any existing .bak alone unless the
        --                             caller explicitly passes preserve == false
        --    - exists but UNREADABLE -> abort WITHOUT replacing: an inaccessible
        --                             primary must be preserved for the caller
        --                             to inspect; do not destroy evidence even
        --                             when a good .bak exists.
        local cur_ok, cur_why = self.read(name)
        local cur_exists
        if kernel then
            cur_exists = tonumber(kernel.GetFileAttributesA(target)) ~= MISSING_ATTR
        else
            -- no GetFileAttributesA: infer existence from the read outcome
            cur_exists = cur_ok or cur_why ~= 'missing'
        end
        if cur_exists and not cur_ok then
            os.remove(temp)
            return nil, 'primary_unreadable'
        end
        if kernel then
            if cur_ok then
                if not win_ok(kernel.CopyFileA, target, backup, 0) then
                    os.remove(temp)
                    return nil, 'backup_failed_' .. tonumber(kernel.GetLastError())
                end
            elseif preserve ~= false then
                -- current absent: keep the last known-good .bak
            else
                -- explicit preserve == false: refresh the stale backup anyway
                kernel.CopyFileA(temp, backup, 0)
            end
            -- 5. publish with replace + write-through.
            if not win_ok(kernel.MoveFileExA, temp, target, MOVE_FLAGS) then
                os.remove(temp)
                return nil, 'replace_failed_' .. tonumber(kernel.GetLastError())
            end
        else
            -- kernel32 could not be loaded (FFI unavailable on this host):
            -- best-effort rename keeps the addon usable but WITHOUT the
            -- Win32 atomic-replace / write-through guarantees.
            local renamed = os.rename(temp, target)
            if not renamed then os.remove(temp) return nil, 'unsupported' end
        end
        return true
    end

    -- -- sample_input ----------------------------------------------------------
    -- Focus-gated cursor sample: the foreground window must belong to our own
    -- process (GetForegroundWindow/GetWindowThreadProcessId), the cursor must
    -- sit inside the client rect, and the result is mapped to Gui.resolution
    -- space (bottom-left). down follows the DiverKit Mouse contract.

    function self.sample_input()
        if not (user and kernel and engine and type(engine.Gui) == 'table') then return nil end
        if type(engine.Gui.resolution) ~= 'function' then return nil end
        -- Scratch buffers must exist before we can sample; with the real FFI
        -- these are CodexTransmogPoint/Rect cdata arrays, explicitly cast to
        -- void * at every call site. Without FFI (stub natives) the pass-through
        -- below lets plain { [0]=... } tables stand in for the same buffers.
        if not (point and rect and idbuf) then return nil end
        local ffi = natives and natives.ffi
        local vp = ffi and ffi.cast and function(v) return ffi.cast('void *', v) end
            or function(v) return v end
        local window = user.GetForegroundWindow()
        if window == nil then return nil end
        -- Must report success before the pid buffer is trusted.
        if tonumber(user.GetWindowThreadProcessId(vp(window), vp(idbuf))) == 0 then return nil end
        if idbuf[0] ~= kernel.GetCurrentProcessId() then return nil end
        if user.GetCursorPos(vp(point)) == 0 then return nil end
        if user.ScreenToClient(vp(window), vp(point)) == 0 then return nil end
        if user.GetClientRect(vp(window), vp(rect)) == 0 then return nil end
        local w, h = rect[0].right - rect[0].left, rect[0].bottom - rect[0].top
        local rw, rh = engine.Gui.resolution()
        local x, y = M.map_cursor(point[0].x, point[0].y, w, h, rw, rh)
        if not x then return nil end
        local down = false
        local mouse = engine.Mouse
        if type(mouse) == 'table' and type(mouse.button_id) == 'function' and type(mouse.button) == 'function' then
            local value = mouse.button(mouse.button_id('left'))
            down = value == true or (type(value) == 'number' and value > 0)
        end
        return { x = x, y = y, down = down }
    end

    -- -- now -------------------------------------------------------------------

    function self.now()
        if kernel and kernel.GetTickCount64 then
            local ok, v = pcall(function() return tonumber(kernel.GetTickCount64()) end)
            if ok and v then return v end
        end
        if natives and natives.GetTickCount64 then return natives.GetTickCount64() end
        return os.time() * 1000
    end

    return self
end

return M
