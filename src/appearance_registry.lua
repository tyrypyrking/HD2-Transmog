-- Provider API 1: data-only, namespaced cosmetic declarations. This registry
-- never writes kits, loads resources, spawns units or grants equipment ownership.
local M={API=1,ASSET_ABI=1}
local function plain(t)
 assert(type(t)=='table'and getmetatable(t)==nil,'plain data table required')
 return t
end
local function fields(t,allowed)
 plain(t);for key in pairs(t)do assert(allowed[key],'unknown provider field: '..tostring(key))end
end
local function string_value(v,limit)
 return type(v)=='string'and #v>0 and #v<=limit and not v:find('%c')
end
local function identifier(v)
 return string_value(v,96)and v:match('^[a-z][a-z0-9_%-]*/[a-z][a-z0-9_%-]*$')~=nil
end
local function copy(v)
 if type(v)~='table'then return v end
 local out={};for k,item in pairs(v)do out[k]=copy(item)end;return out
end
local function canonical(v)
 if type(v)~='table'then return type(v)..':'..tostring(v)end
 local keys={};for k in pairs(v)do keys[#keys+1]=k end
 table.sort(keys,function(a,b)return tostring(a)<tostring(b)end)
 local out={};for _,k in ipairs(keys)do
  local value=canonical(v[k]);out[#out+1]=tostring(k)..':'..#value..':'..value
 end;return '{'..table.concat(out,'|')..'}'
end
local function array(t,limit)
 plain(t);local count=0
 for k in pairs(t)do assert(type(k)=='number'and k%1==0 and k>=1 and k<=limit,'bounded dense array required');count=count+1 end
 assert(count>=1 and count<=limit and #t==count,'bounded dense array required')
 for i=1,count do assert(t[i]~=nil,'sparse provider array rejected')end
end
function M.validate(manifest)
 local ok,result=pcall(function()
  fields(manifest,{schema=true,api=true,asset_abi=true,id=true,name=true,version=true,appearances=true})
  assert(manifest.schema=='hd2-transmog-appearances','unsupported appearance schema')
  assert(manifest.api==M.API,'unsupported Transmog provider API')
  assert(manifest.asset_abi==M.ASSET_ABI,'unsupported visual asset ABI')
  assert(identifier(manifest.id),'provider id must be author/pack')
  assert(string_value(manifest.name,96),'provider name required')
  assert(string_value(manifest.version,32)and manifest.version:match('^%d+%.%d+%.%d+$'),'content version must be major.minor.patch')
  array(manifest.appearances,64)
  local prefix='mods/hd2transmog/appearances/'..manifest.id..'/'
  local function resource(path)
   assert(string_value(path,240)and path:sub(1,#prefix)==prefix,'visual resources must use the provider namespace')
   local suffix=path:sub(#prefix+1)
   assert(#suffix>0 and not suffix:find('[^a-z0-9_/%-]')and not suffix:find('//',1,true)
    and suffix:sub(-1)~='/','invalid visual resource path')
  end
  local seen={}
  for _,appearance in ipairs(manifest.appearances)do
   fields(appearance,{id=true,name=true,bodies=true})
   assert(string_value(appearance.id,64)and appearance.id:match('^[a-z][a-z0-9_%-]*$'),'invalid appearance id')
   assert(not seen[appearance.id],'duplicate appearance id');seen[appearance.id]=true
   assert(string_value(appearance.name,96),'appearance name required')
   fields(appearance.bodies,{lean=true,muscle=true})
   assert(next(appearance.bodies)~=nil,'at least one supported body type required')
   for _,body in pairs(appearance.bodies)do
    fields(body,{package=true,units=true});resource(body.package);array(body.units,16)
    local units={};for _,unit in ipairs(body.units)do resource(unit);assert(not units[unit],'duplicate root unit');units[unit]=true end
   end
  end
  return copy(manifest)
 end)
 if not ok then return nil,tostring(result):gsub('^.-%.lua:%d+: ','')end
 return result
end
function M.new(report)
 report=report or function()end
 local providers,signatures={},{}
 local public={api=M.API,asset_abi=M.ASSET_ABI}
 local reason='Independent appearance rendering is not yet verified for this game build.'
 function public.capabilities()
  return {api=M.API,asset_abi=M.ASSET_ABI,registration=true,independent_rendering=false,
   vanilla_replacement=false,reason=reason}
 end
 function public.register(manifest)
  local data,why=M.validate(manifest);if not data then return nil,why end
  local fingerprint=canonical(data)
  if signatures[data.id]then
   if signatures[data.id]~=fingerprint then return nil,'provider id already registered with different content'end
   return {id=data.id,status='registered_unavailable',reason=reason,already_registered=true}
  end
  local count=0;for _ in pairs(providers)do count=count+1 end
  if count>=128 then return nil,'provider capacity reached'end
  providers[data.id]=data;signatures[data.id]=fingerprint
  report('appearance.registered',data.id..'@'..data.version)
  return {id=data.id,status='registered_unavailable',reason=reason,already_registered=false}
 end
 function public.list(body_type)
  assert(body_type==nil or body_type=='lean'or body_type=='muscle','unknown body type')
  local out={}
  for id,provider in pairs(providers)do
   for _,appearance in ipairs(provider.appearances)do
    if not body_type or appearance.bodies[body_type]then
     out[#out+1]={id=id..'/'..appearance.id,provider=id,name=appearance.name,version=provider.version,
      bodies=copy(appearance.bodies),available=false,status='registered_unavailable',reason=reason}
    end
   end
  end
  table.sort(out,function(a,b)return a.id<b.id end);return out
 end
 return public
end
return M
