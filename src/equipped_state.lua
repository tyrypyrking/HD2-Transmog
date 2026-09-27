-- Mod-private startup intent. Never persist a native pointer or a custom game
-- item ID. The native save continues to contain the ordinary appearance armor.
local M={}
local HEADER='HD2TM_EQUIPPED 1\n'
local OFF=HEADER..'none\n'
local FIELDS={'appearance_id','stats_id','passive_variant_id'}
local function same(a,b)
 if not(a and b)then return false end
 for _,k in ipairs(FIELDS)do if a[k]~=b[k]then return false end end
 return true
end
function M.encode(S,label,request)
 if not label then return OFF end
 local state=S.new();state.presets[label]=request;state.requested=request
 local raw,why=S.encode(state);if not raw then return nil,why end
 if not request.appearance_id:match('^armor:%x%x%x%x%x%x%x%x$')then return nil,'ordinary armor identity required'end
 raw=HEADER..raw
 if #raw>4096 then return nil,'equipped record exceeds bounds'end
 return raw
end
function M.decode(S,raw)
 if raw==OFF then return false end
 if type(raw)~='string'or #raw>4096 or raw:sub(1,#HEADER)~=HEADER then return nil,'invalid equipped record'end
 local state,why=S.decode(raw:sub(#HEADER+1));if not state then return nil,why end
 if next(state.catalog)or next(state.owned)then return nil,'equipped record contains catalog data'end
 local label,request=next(state.presets)
 if not label or next(state.presets,label)or not same(request,state.requested)
  or not request.appearance_id:match('^armor:%x%x%x%x%x%x%x%x$')then return nil,'invalid equipped variant'end
 return {label=label,request=request,target_id=request.appearance_id}
end
function M.matches(record,domain,armor)
 return record and domain and record.target_id==armor and same(domain.presets[record.label],record.request)or false
end
function M.new(fs,S,report)
 report=report or function()end
 local raw,reason=fs.read('equipped.state')
 local record,locked
 if raw then
  record,reason=M.decode(S,raw);locked=record==nil
 elseif reason and reason~='missing'then locked=true end
 if locked then report('restore.record_unavailable',reason)end
 local self={}
 function self:record()return record or nil end
 function self:clear()
  -- Invalid/unreadable records cannot authorize startup restoration. Preserve
  -- them for diagnosis; do not turn a storage failure into an equipment lock.
  if not record then return true end
  local ok,why=fs.write_atomic('equipped.state',OFF)
  if not ok then return nil,'Could not clear startup restoration: '..tostring(why)end
  record=false;return true
 end
 function self:remember(label,request)
  if not label then return self:clear()end
  if locked then return nil,'equipped record needs recovery'end
  local value,why=M.encode(S,label,request);if not value then return nil,why end
  local ok,err=fs.write_atomic('equipped.state',value);if not ok then return nil,err end
  record=assert(M.decode(S,value));return true
 end
 return self
end
return M
