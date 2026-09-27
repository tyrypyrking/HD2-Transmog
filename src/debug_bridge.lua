-- Development-only file commands, with a per-launch token against stale replay.
-- Data-only allowlist; no executable payloads or arbitrary native calls.
local M={}
function M.new(fs,engine,report)
 if fs.read('debug.enabled')~='HD2TM_DEBUG 1\n' then return nil end
 local session=tostring(os.time())..'-'..tostring(math.floor(fs.now()))
 local seen,command_count,next_poll={},0,0
 fs.write_atomic('debug.session','HD2TM_DEBUG_SESSION 1\n'..session..'\n')
 local self={session=session}
 function self:poll(handlers)
  if fs.now()<next_poll then return end
  next_poll=fs.now()+250
  local request=fs.read('debug.request')
  if not request or #request>2048 then return end
  local token,id,command,args=request:match('^HD2TM_DEBUG_REQUEST 1\n([%w%-]+)\n([%w%-]+)\n([a-z_]+)\n(.*)$')
  if token~=session or not id or #id>80 or seen[id] then return end
  if command_count>=1024 then return end
  seen[id]=true;command_count=command_count+1
  local ok,value=pcall(function()
   assert(handlers[command],'Unknown debug command')
   return assert(handlers[command](args),'Command did not return a result')
  end)
  local text=tostring(value):gsub('[\r\n]',' '):sub(1,1000)
  fs.write_atomic('debug.response','HD2TM_DEBUG_RESPONSE 1\n'..session..'\n'..id..'\n'..(ok and 'ok' or 'error')..'\n'..text..'\n')
  report('debug.'..command,(ok and 'ok: ' or 'error: ')..text)
 end
 function self:inspect()
  local lines={}
  local function names(prefix,t)
   if type(t)~='table'then return end
   local keys={};for k,v in pairs(t)do
    if type(k)=='string' and #k<128 then keys[#keys+1]=prefix..'.'..k..' '..type(v)end
   end;table.sort(keys)
   for i=1,math.min(#keys,2048)do lines[#lines+1]=keys[i]end
  end
  names('_G',_G);names('stingray',engine)
  local keys={};for k,v in pairs(engine)do if type(k)=='string' and type(v)=='table'then keys[#keys+1]=k end end
  table.sort(keys);for _,k in ipairs(keys)do names('stingray.'..k,engine[k])end
  local alternate=rawget(_G,'s3d')
  if alternate==engine then lines[#lines+1]='s3d.alias_of_stingray true'
  elseif type(alternate)=='table'then
   names('s3d',alternate)
   local nested={};for k,v in pairs(alternate)do if type(k)=='string'and type(v)=='table'then nested[#nested+1]=k end end
   table.sort(nested);for _,k in ipairs(nested)do names('s3d.'..k,alternate[k])end
  end
  fs.write_atomic('debug-api.txt',table.concat(lines,'\n')..'\n')
  return 'API names recorded'
 end
 function self:inspect_world()
  local markers={weapon_wall='be0be6b1875a4a66',bridge_shell='ce2566805c9e893a',galaxy_table='3b9bcf29e38da0a6'}
  local lines={'HD2TRANSMOG_WORLD_MARKERS 1'}
  local main=engine.Application.main_world()
  for index,world in ipairs(engine.Application.worlds()or{})do
   if index>16 then break end
   lines[#lines+1]='world='..index..' main='..tostring(world==main)
   for name,hash in pairs(markers)do
    local ok,units=pcall(engine.World.units_by_resource,world,engine.IdString64.from_hex(hash))
    lines[#lines+1]=name..'='..(ok and type(units)=='table' and tostring(#units)or 'unavailable')
   end
  end
  fs.write_atomic('debug-world.txt',table.concat(lines,'\n')..'\n')
  return 'Scene marker observations recorded'
 end
 self:inspect()
 return self
end
return M
