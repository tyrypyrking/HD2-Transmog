-- state.lua — HD2 Transmog domain + persistence encoding (pure LuaJIT 5.1)
--
-- Pure domain module: no game hooks, no memory/FFI, no file I/O (the parent
-- owns persistence), no account-ownership source. Ownership comes ONLY from
-- the authoritative owned-kit list supplied by the caller; no fake unlocks.
-- No loadstring/load anywhere: decode is data-only.
--
-- ============================================================================
-- API CONTRACT
-- ============================================================================
-- local S = dofile("src/state.lua")           -- returns module table
--
-- S.SCHEMA_VERSION -> 1
--
-- S.new(opts?) -> state
--   opts: { catalog = { [kit_id] = {appearance_id=, stats_id=, passive_variant_id=} },
--           owned   = { [kit_id] = true } }   -- both optional, copied
--   Only TRUTHY owned entries count ({kit=false} grants nothing).
--   state = { schema_version, catalog, owned, requested, selected, presets }
--     requested : nil | {appearance_id, stats_id, passive_variant_id}
--         player's pick; persisted verbatim, survives temporary ownership loss
--     selected  : ownership-resolved request; NOT evidence of in-game application
--     presets   : { [utf8 label] = {appearance_id, stats_id, passive_variant_id} }
--
-- S.validate(state) -> true | nil, err
--   Shape check: schema_version, id strings (non-empty, no whitespace/control,
--   <=128 chars), valid UTF-8 non-empty preset labels, owned subset of catalog.
--
-- S.encode(state) -> string | nil, err
--   Deterministic bounded line encoding (sorted, LF lines, header "HD2TM 1").
--   Does NOT throw: returns nil, err on invalid state (main can pcall anyway).
--
-- S.decode(text) -> state | nil, err
--   Parses encode() output (data only, never executes). Rejects bad magic,
--   unknown/absent schema version, unknown/malformed/duplicate lines, malformed
--   %-escapes, invalid ids/labels, input >1MB or unbounded record counts.
--   PERSISTED OWNERSHIP IS A CACHE, NEVER AUTHORIZATION: decode returns
--   selected=nil, ownership_verified=false; reconcile with a fresh owned list.
--
-- S.reconcile_owned(state, catalog, owned_kit_ids) -> state
--   Installs the authoritative catalog + owned set (array {id,...} or set
--   {id=true}, falsy entries ignored), then re-resolves `selected` from the
--   persisted `requested`: active iff appearance_id, stats_id and the EXACT
--   passive_variant_id are EACH provided by some owned kit (independent
--   resolution — the three parts may come from three different kits, that is
--   the point of transmog). Otherwise selected=nil, requested PRESERVED.
--
-- S.select(state, appearance_id, stats_id, passive_variant_id) -> true | nil, err
--   Cross-kit composition: each of the three ids must independently belong to
--   some OWNED kit (kit A's look + kit B's stats + kit C's exact passive
--   variant are all allowed together). Missing/unowned ids are rejected with
--   the offending part. On success sets requested; selected stays nil until
--   reconcile_owned confirms against fresh ownership.
-- ============================================================================

local M = {}
M.SCHEMA_VERSION = 1

-- decode bounds
local MAX_INPUT = 1024 * 1024       -- 1MB
local MAX_RECORDS = 4096            -- catalog/owned lines
local MAX_PRESETS = 256

-- ids: non-empty strings, no whitespace/control chars (encode-safe), <=128
local function is_id(v)
  return type(v) == "string" and #v > 0 and #v <= 128 and v:find("[%c%s]") == nil
end

-- valid UTF-8 (rejects overlongs, surrogates, >U+10FFFF), <=256B
local function utf8_ok(s)
  if type(s) ~= "string" or #s > 256 then return false end
  local i, n = 1, #s
  while i <= n do
    local b = s:byte(i)
    local len, lo, hi
    if b < 0x80 then len = 1
    elseif b >= 0xC2 and b <= 0xDF then len, lo, hi = 2, 0x80, 0xBF
    elseif b >= 0xE0 and b <= 0xEF then len, lo, hi = 3, 0x80, 0xBF
    elseif b >= 0xF0 and b <= 0xF4 then len, lo, hi = 4, 0x80, 0xBF
    else return false end
    if i + len - 1 > n then return false end
    for j = 1, len - 1 do
      local c = s:byte(i + j)
      if c < lo or c > hi then return false end
    end
    if len >= 3 then
      local b2 = s:byte(i + 1)
      if (b == 0xE0 and b2 < 0xA0) or (b == 0xED and b2 > 0x9F)
        or (b == 0xF0 and b2 < 0x90) or (b == 0xF4 and b2 > 0x8F) then
        return false
      end
    end
    i = i + len
  end
  return true
end

local function triple(a, s, p)
  if not (is_id(a) and is_id(s) and is_id(p)) then return nil end
  return { appearance_id = a, stats_id = s, passive_variant_id = p }
end

local function copy(t)
  return type(t) == 'table' and triple(t.appearance_id, t.stats_id, t.passive_variant_id) or nil
end

function M.new(opts)
  opts = opts or {}
  local st = {
    schema_version = M.SCHEMA_VERSION, catalog = {}, owned = {},
    requested = nil, selected = nil, presets = {},
    ownership_verified = type(opts.owned) == 'table',
  }
  for id, t in pairs(opts.catalog or {}) do
    st.catalog[id] = copy(t)
  end
  for id, v in pairs(opts.owned or {}) do
    if v then st.owned[id] = true end          -- falsy never grants ownership
  end
  return st
end

function M.validate(st)
  if type(st) ~= "table" then return nil, "state must be a table" end
  if st.schema_version ~= M.SCHEMA_VERSION then
    return nil, "unsupported schema version: " .. tostring(st.schema_version)
  end
  for _, k in ipairs({ "catalog", "owned", "presets" }) do
    if type(st[k]) ~= "table" then return nil, k .. " must be a table" end
  end
  for id, t in pairs(st.catalog) do
    if not is_id(id) or not copy(t) then
      return nil, "invalid catalog entry: " .. tostring(id)
    end
  end
  for id in pairs(st.owned) do
    if not is_id(id) then return nil, "invalid owned kit id" end
    if not st.catalog[id] then return nil, "owned kit not in catalog: " .. id end
  end
  for _, k in ipairs({ "requested", "selected" }) do
    local t = st[k]
    if t ~= nil and not copy(t) then
      return nil, "invalid " .. k
    end
  end
  for label, t in pairs(st.presets) do
    if not utf8_ok(label) or #label == 0
      or not copy(t) then
      return nil, "invalid preset: " .. tostring(label)
    end
  end
  return true
end

-- ---------------------------------------------------------------------------
-- encode / decode
-- ---------------------------------------------------------------------------
-- HD2TM 1
-- K <kit_id> <appearance_id> <stats_id> <passive_variant_id>
-- O <kit_id>                                  (cache only, not authorization)
-- S <appearance_id> <stats_id> <passive_variant_id>          (requested, 0..1)
-- P <escaped_label> <appearance_id> <stats_id> <passive_variant_id>

function M.encode(st)
  local ok, err = M.validate(st)
  if not ok then return nil, "encode: " .. tostring(err) end
  local lines = { "HD2TM " .. M.SCHEMA_VERSION }
  local ids = {}
  for id in pairs(st.catalog) do ids[#ids + 1] = id end
  table.sort(ids)
  for _, id in ipairs(ids) do
    local t = st.catalog[id]
    lines[#lines + 1] = "K " .. id .. " " .. t.appearance_id .. " "
      .. t.stats_id .. " " .. t.passive_variant_id
  end
  ids = {}
  for id in pairs(st.owned) do ids[#ids + 1] = id end
  table.sort(ids)
  for _, id in ipairs(ids) do lines[#lines + 1] = "O " .. id end
  if st.requested then
    local r = st.requested
    lines[#lines + 1] = "S " .. r.appearance_id .. " " .. r.stats_id
      .. " " .. r.passive_variant_id
  end
  ids = {}
  for label in pairs(st.presets) do ids[#ids + 1] = label end
  table.sort(ids)
  for _, label in ipairs(ids) do
    local t = st.presets[label]
    local esc = label:gsub("[%%%c]", function(c)
      return string.format("%%%02X", c:byte())
    end)
    lines[#lines + 1] = "P " .. esc .. " " .. t.appearance_id .. " "
      .. t.stats_id .. " " .. t.passive_variant_id
  end
  return table.concat(lines, "\n") .. "\n"
end

local function unescape(s)
  if not s:find("%%") then return s end
  -- every '%' must start a two-hex-digit escape; anything else is malformed
  if s:gsub("%%%x%x", ""):find("%%") then return nil end
  return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

function M.decode(text)
  if type(text) ~= "string" then return nil, "decode: text must be a string" end
  if #text > MAX_INPUT then return nil, "decode: input too large" end
  local magic, ver = text:match("^(HD2TM) (%d+)")
  if not magic then return nil, "decode: bad header" end
  if tonumber(ver) ~= M.SCHEMA_VERSION then
    return nil, "decode: unsupported schema version " .. ver
  end
  local body = text:sub(#ver + 7)               -- skip "HD2TM <ver>"
  if body ~= "" and body:sub(1, 1) ~= "\n" then return nil, "decode: bad header" end

  local st = M.new()
  local n = 0
  for line in (body .. "\n"):gmatch("(.-)\n") do
    if line ~= "" then
      n = n + 1
      if n > MAX_RECORDS + MAX_PRESETS then
        return nil, "decode: too many records"
      end
      local kind = line:sub(1, 1)
      local a, s, p
      if kind == "K" then
        local id = line:match("^K (%S+) (%S+) (%S+) (%S+)$")
        local t = id and not st.catalog[id] and triple(line:match("^K %S+ (%S+) (%S+) (%S+)$"))
        if not t then return nil, "decode: bad K line " .. n end
        st.catalog[id] = t
      elseif kind == "O" then
        local id = line:match("^O (%S+)$")
        if not id or st.owned[id] then return nil, "decode: bad O line " .. n end
        st.owned[id] = true                       -- cached, not authorization
      elseif kind == "S" then
        if st.requested then return nil, "decode: duplicate S line " .. n end
        a, s, p = line:match("^S (%S+) (%S+) (%S+)$")
        st.requested = triple(a, s, p)
        if not st.requested then return nil, "decode: bad S line " .. n end
      elseif kind == "P" then
        local esc = line:match("^P (.-) (%S+) (%S+) (%S+)$")
        local label = esc and unescape(esc)
        if not label or not utf8_ok(label) or #label == 0 or st.presets[label] then
          return nil, "decode: bad P line " .. n
        end
        a, s, p = line:match("^P .- (%S+) (%S+) (%S+)$")
        st.presets[label] = triple(a, s, p)
        if not st.presets[label] then return nil, "decode: bad P line " .. n end
      else
        return nil, "decode: unknown line " .. n
      end
    end
  end
  local pc = 0
  for _ in pairs(st.presets) do
    pc = pc + 1
    if pc > MAX_PRESETS then return nil, "decode: too many presets" end
  end

  local ok, err = M.validate(st)
  if not ok then return nil, "decode: " .. err end
  st.selected = nil     -- persisted ownership is a cache, never authorization
  st.ownership_verified = false
  return st
end

-- ---------------------------------------------------------------------------
-- reconcile_owned / select
-- ---------------------------------------------------------------------------

-- Does some OWNED kit provide `id` as its appearance/stats/exact passive variant?
local function owned_provides(cat, own, field, id)
  for kit_id, t in pairs(cat) do
    if own[kit_id] == true and type(t) == 'table' and t[field] == id then
      return true
    end
  end
  return false
end

function M.reconcile_owned(st, catalog, owned_kit_ids)
  if type(st) ~= "table" then return nil, "state must be a table" end
  if type(catalog) ~= "table" then return nil, "catalog must be a table" end
  local cat, own = {}, {}
  for id, t in pairs(catalog) do cat[id] = copy(t) end
  if type(owned_kit_ids) == "table" and owned_kit_ids[1] ~= nil then
    for _, id in ipairs(owned_kit_ids) do own[id] = true end
  elseif type(owned_kit_ids) == "table" then
    for id, v in pairs(owned_kit_ids) do
      if v then own[id] = true end            -- falsy never grants ownership
    end
  end
  st.catalog, st.owned = cat, own
  st.ownership_verified = type(owned_kit_ids) == 'table'

  st.selected = nil
  local r = st.requested
  if r and owned_provides(cat, own, 'appearance_id', r.appearance_id)
    and owned_provides(cat, own, 'stats_id', r.stats_id)
    and owned_provides(cat, own, 'passive_variant_id', r.passive_variant_id) then
    st.selected = copy(r)
  end
  return st
end

function M.select(st, appearance_id, stats_id, passive_variant_id)
  local want = triple(appearance_id, stats_id, passive_variant_id)
  if not want then return nil, "select: invalid ids" end
  if st.ownership_verified ~= true then return nil, 'select: current ownership unavailable' end
  local cat, own = st.catalog or {}, st.owned or {}
  -- independent resolution: each part may come from a different owned kit
  if not owned_provides(cat, own, 'appearance_id', appearance_id) then
    return nil, "select: appearance not owned: " .. appearance_id
  end
  if not owned_provides(cat, own, 'stats_id', stats_id) then
    return nil, "select: stats not owned: " .. stats_id
  end
  if not owned_provides(cat, own, 'passive_variant_id', passive_variant_id) then
    return nil, "select: passive variant not owned: " .. passive_variant_id
  end
  st.requested = want
  st.selected = nil          -- activation is reconcile_owned's job (fresh list)
  return true
end

-- ---------------------------------------------------------------------------
-- Variant editor: transient drafts and transactional save proposals.
-- Display labels/effect descriptions come from the adapter, never authorize a
-- choice, and never replace durable ids. There is deliberately no apply action.
-- ---------------------------------------------------------------------------
local FIELDS = {appearance='appearance_id', stats='stats_id', passive='passive_variant_id'}
local FIELD_ORDER = {'appearance_id', 'stats_id', 'passive_variant_id'}
local STAT_FIELDS = {'armor_rating', 'speed', 'stamina_regen'}
local STAT_LABELS = {'Armor', 'Speed', 'Stamina regen'}
local SAVED_PAGE_SIZE = 3

local function sorted_keys(t)
  local keys = {}
  for key in pairs(t or {}) do keys[#keys+1] = key end
  table.sort(keys)
  return keys
end

local function available(st, value)
  if st.ownership_verified ~= true or not copy(value) then return false end
  for _, field in ipairs(FIELD_ORDER) do
    if not owned_provides(st.catalog, st.owned, field, value[field]) then return false end
  end
  return true
end

local function options(st, field)
  local found = {}
  if st.ownership_verified == true then
    for kit, value in pairs(st.catalog) do
      if st.owned[kit] == true then found[value[field]] = true end
    end
  end
  return sorted_keys(found)
end

local function label_for(context, field, id)
  local labels = context.labels and context.labels[field]
  local label = labels and labels[id]
  return type(label) == 'string' and label ~= '' and label or id or 'Not selected'
end

local function next_label(st, base)
  -- Numbered names keep creation usable before native text input is connected.
  base = type(base) == 'string' and utf8_ok(base) and #base <= 220 and base or 'Variant'
  for i = 1, MAX_PRESETS+1 do
    local label = base..' '..i
    if not st.presets[label] then return label end
  end
end

local function seed_kit(st, context)
  if st.ownership_verified ~= true then return nil end
  if context.current_kit_id then
    if st.owned[context.current_kit_id] == true and st.catalog[context.current_kit_id] then
      return context.current_kit_id, 'native_selection'
    end
    return nil -- Never silently substitute an unowned native selection.
  end
  if st.requested then
    local donor, ambiguous
    for id, kit in pairs(st.catalog) do
      if st.owned[id] == true and kit.stats_id == st.requested.stats_id then
        if donor then ambiguous=true else donor=id end
      end
    end
    if donor and not ambiguous then return donor, 'saved_stats_donor' end
  end
  for _, id in ipairs(sorted_keys(st.catalog)) do
    if st.owned[id] == true then return id, 'first_owned' end
  end
end

function M.editor_new()
  return {draft=nil, label=nil, source_label=nil, dirty=false, detail_page=1, saved_page=1}
end

local function load_draft(editor, value, label, source, dirty)
  editor.draft, editor.label = copy(value), label
  editor.source_label, editor.dirty, editor.detail_page = source, dirty, 1
end

function M.editor_saved(editor)
  editor.dirty, editor.source_label = false, editor.label
  editor.saved_focus_label=nil
end

-- Stable action labels, independent of list order or pagination. These are
-- data-only tokens; the controller never evaluates their contents as Lua.
function M.variant_action(label, edit)
  if not utf8_ok(label) or label == '' then return nil end
  return (edit and 'variant_edit:' or 'variant_select:')..label:gsub('[^%w%-_%.]', function(char)
    return string.format('%%%02X', char:byte())
  end)
end

local function number_value(value)
  return type(value)=='number' and value==value and value>=0 and value<=1000000 and value or nil
end

local function icon_for(context, passive_id)
  local explicit=context.passive_icons and context.passive_icons[passive_id]
  if type(explicit)=='table' then return explicit end
  local passive=context.passive_variants and context.passive_variants[passive_id]
  if type(passive)=='table' and type(passive.icon_hash)=='string' then
    return {material=passive.icon_hash}
  end
end

-- The native adapter provides BASE and perk-adjusted values separately. Never
-- copy a donor's already boosted displayed total and add the selected perk.
function M.editor_stats(value, context)
  context=context or {}
  local profile=value and context.stats_profiles and context.stats_profiles[value.stats_id]
  local resolved=value and context.resolved_stats and context.resolved_stats[value.stats_id..'|'..value.passive_variant_id]
  local verified=type(resolved)=='table' and resolved.verified==true
  local base=verified and resolved.base or type(profile)=='table' and profile.base_values
  local effective=verified and resolved.effective or nil
  local rows,complete={},true
  for index,field in ipairs(STAT_FIELDS)do
    local b=type(base)=='table' and number_value(base[field]) or nil
    local e=type(effective)=='table' and number_value(effective[field]) or nil
    rows[index]={field=field,label=STAT_LABELS[index],base=b,effective=e,
      bonus=b and e and e-b or nil,verified=verified and e~=nil}
    if not e then complete=false end
  end
  return {rows=rows,verified=verified and complete,
    note=verified and complete and 'Totals include this perk once.' or 'Base profile selected; perk-adjusted values need verification.'}
end

local function saved_cards(st,editor,context)
  local labels=sorted_keys(st.presets)
  if editor.source_label and editor.saved_focus_label~=editor.source_label then
    for index,label in ipairs(labels)do
      if label==editor.source_label then editor.saved_page=math.floor((index-1)/SAVED_PAGE_SIZE)+1;break end
    end
    editor.saved_focus_label=editor.source_label
  end
  local pages=math.max(1,math.ceil(#labels/SAVED_PAGE_SIZE))
  local page=math.min(pages,math.max(1,editor.saved_page or 1))
  local cards={}
  for index=(page-1)*SAVED_PAGE_SIZE+1,math.min(page*SAVED_PAGE_SIZE,#labels)do
    local label=labels[index]
    local value=editor.source_label==label and editor.draft or st.presets[label]
    cards[#cards+1]={label=label,action=M.variant_action(label),edit_action=M.variant_action(label,true),
      selected=editor.source_label==label,dirty=editor.source_label==label and editor.dirty or false,
      available=available(st,value),can_select=not editor.dirty,
      appearance=label_for(context,'appearance_id',value.appearance_id),
      stats=label_for(context,'stats_id',value.stats_id),
      passive=label_for(context,'passive_variant_id',value.passive_variant_id),
      passive_icon=icon_for(context,value.passive_variant_id),
      preview=context.appearance_previews and context.appearance_previews[value.appearance_id],
      request=copy(value)}
  end
  return {cards=cards,page=page,pages=pages,count=#labels,can_previous=page>1,can_next=page<pages}
end

-- A text-input integration may call this without bypassing label validation.
function M.editor_rename(st, editor, label)
  if not editor.draft then return nil, 'Create or select a variant first' end
  if not utf8_ok(label) or label == '' or label:find('%c') then return nil, 'Invalid variant name' end
  if st.presets[label] and label ~= editor.source_label then return nil, 'That name is already saved' end
  editor.label, editor.dirty = label, true
  return true
end

function M.editor_view(st, editor, tab, context)
  context = context or {}
  local seed, seed_source = seed_kit(st, context)
  local field = FIELDS[tab]
  local saved = sorted_keys(st.presets)
  local choices = field and options(st, field) or saved
  local current = field and editor.draft and editor.draft[field] or editor.source_label
  local index
  for i, id in ipairs(choices) do if id == current then index = i end end
  local details = {}
  if field and current then
    local source = context.details and context.details[field] and context.details[field][current]
    if type(source) == 'table' then
      for _, line in ipairs(source) do
        if type(line) == 'string' then details[#details+1] = line end
      end
    end
    if #details == 0 then
      details[1] = field == 'appearance_id' and 'The native preview shows the native armor selection.'
        or 'Verified details are not available for this choice.'
    end
  elseif not field and editor.draft then
    for i, key in ipairs(FIELD_ORDER) do
      details[i] = ({'Look: ', 'Stats: ', 'Passive: '})[i]..label_for(context, key, editor.draft[key])
    end
  else
    details[1] = #saved > 0 and 'Use the arrows to open a saved variant.' or 'Create a variant from an owned armor.'
  end
  local resolved = available(st, editor.draft)
  local stats=M.editor_stats(editor.draft,context)
  local notice = st.ownership_verified ~= true and 'Ownership unavailable - saved choices are preserved.'
    or editor.draft and not resolved and 'A selected donor is unavailable. Choose an owned replacement.'
    or 'Only verified owned donors are offered.'
  return {
    label=editor.label or 'No variant selected', dirty=editor.dirty,
    choice=field and label_for(context, field, current) or editor.source_label or 'Saved variants',
    count=#choices, index=index, details=details, detail_page=editor.detail_page,
    saved_section=saved_cards(st,editor,context),
    appearance_label=label_for(context,'appearance_id',editor.draft and editor.draft.appearance_id),
    stats_label=label_for(context,'stats_id',editor.draft and editor.draft.stats_id),
    passive_label=label_for(context,'passive_variant_id',editor.draft and editor.draft.passive_variant_id),
    passive_icon=editor.draft and icon_for(context,editor.draft.passive_variant_id),stats_summary=stats,
    can_new=seed ~= nil and not editor.dirty and #saved < MAX_PRESETS,
    seed_kit_id=seed, seed_source=seed_source,
    can_duplicate=editor.draft ~= nil and not editor.dirty and #saved < MAX_PRESETS,
    can_discard=editor.dirty == true,
    can_previous=#choices > 0 and (field and editor.draft ~= nil or not field and not editor.dirty),
    can_next=#choices > 0 and (field and editor.draft ~= nil or not field and not editor.dirty),
    can_save=editor.draft ~= nil and resolved and editor.dirty,
    ownership=notice, apply_notice='Saving stores a variant. Applying is not connected.',
    saved_count=#saved,
  }
end

function M.editor_action(st, editor, action, tab, context)
  context = context or {}
  local field = FIELDS[tab]
  local intent,encoded
  if type(action)=='string'then intent,encoded=action:match('^(variant_[a-z]+):(.*)$')end
  if intent=='variant_select' or intent=='variant_edit' then
    local label=unescape(encoded)
    local value=label and st.presets[label]
    if not value then return true,'Saved variant is unavailable' end
    if editor.dirty and (editor.source_label~=label or intent~='variant_edit') then return true,'Save or discard this draft first' end
    if not editor.dirty then load_draft(editor,value,label,label,false)end
    return true,intent=='variant_edit' and 'Editing saved variant' or 'Saved variant selected',nil,
      {intent=intent,label=label,request=copy(editor.draft),open_editor=intent=='variant_edit',
       ownership_resolved=available(st,editor.draft)}
  elseif action=='previous_variants' or action=='next_variants' then
    local pages=math.max(1,math.ceil(#sorted_keys(st.presets)/SAVED_PAGE_SIZE))
    editor.saved_page=math.min(pages,math.max(1,(editor.saved_page or 1)+(action=='next_variants' and 1 or -1)))
    return true
  elseif action == 'new_variant' then
    if editor.dirty then return true, 'Save or discard this draft first' end
    if #sorted_keys(st.presets) >= MAX_PRESETS then return true, 'The saved variant limit is reached' end
    local kit, source = seed_kit(st, context)
    if not kit then return true, 'A current owned armor catalog is required' end
    local title = context.kit_labels and context.kit_labels[kit]
    title = title or context.labels and context.labels.appearance_id and context.labels.appearance_id[st.catalog[kit].appearance_id]
    load_draft(editor, st.catalog[kit], next_label(st, title or 'Variant'), nil, true)
    return true, source == 'saved_stats_donor' and 'Draft copied from the saved stat donor'
      or source == 'first_owned' and 'Draft copied from the first owned armor'
      or 'Draft copied from the selected native armor',nil,{intent='new_variant',open_editor=true}
  elseif action == 'duplicate_variant' then
    if editor.dirty then return true, 'Save or discard this draft first' end
    if not editor.draft then return true, 'Select a saved variant first' end
    if #sorted_keys(st.presets) >= MAX_PRESETS then return true, 'The saved variant limit is reached' end
    load_draft(editor, editor.draft, next_label(st, editor.label..' copy'), nil, true)
    return true, 'Independent copy created',nil,{intent='duplicate_variant',open_editor=true}
  elseif action == 'discard_variant' then
    local source = editor.source_label
    load_draft(editor, source and st.presets[source], source, source, false)
    return true, 'Draft changes discarded'
  elseif action == 'previous_option' or action == 'next_option' then
    if not field and editor.dirty then return true, 'Save or discard this draft first' end
    if field and not editor.draft then return true, 'Create or select a variant first' end
    local choices = field and options(st, field) or sorted_keys(st.presets)
    if #choices == 0 then return true, field and 'No verified owned choices available' or 'No variants saved yet' end
    local current = field and editor.draft[field] or editor.source_label
    local index
    for i, id in ipairs(choices) do if id == current then index = i end end
    local step = action == 'next_option' and 1 or -1
    index = index and ((index-1+step)%#choices)+1 or (step == 1 and 1 or #choices)
    if field then
      editor.draft[field], editor.dirty, editor.detail_page = choices[index], true, 1
    else
      load_draft(editor, st.presets[choices[index]], choices[index], choices[index], false)
    end
    return true, field and 'Draft updated - save to keep this choice' or 'Saved variant selected - armor is unchanged'
  elseif action == 'previous_details' or action == 'next_details' then
    editor.detail_page = math.max(1, (editor.detail_page or 1)+(action == 'next_details' and 1 or -1))
    return true
  elseif action == 'save_variant' then
    if not editor.draft or not editor.label then return true, 'Create or select a variant first' end
    if not available(st, editor.draft) then return true, 'Current ownership is required before saving changes' end
    local candidate = M.new{catalog=st.catalog, owned=st.owned}
    for label, value in pairs(st.presets) do candidate.presets[label] = copy(value) end
    if editor.source_label and editor.source_label ~= editor.label then candidate.presets[editor.source_label] = nil end
    candidate.presets[editor.label] = copy(editor.draft)
    candidate.requested = copy(editor.draft)
    local valid, why = M.validate(candidate)
    if not valid then return true, why end
    -- Caller must persist this candidate first. Failed writes keep both the
    -- previous in-memory domain and file intact; the draft remains editable.
    return true, nil, candidate
  end
  return false
end

return M
