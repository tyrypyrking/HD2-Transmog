-- Optional, version-gated Lua adapter. No DiverKit require, file dependency,
-- native offsets, or writes to its installation. Metadata lives in its normal
-- atomic preset snapshot; original equipment paths remain unchanged if absent.
local M={}
local fields={'label','appearance_id','stats_id','passive_variant_id'}
local function metadata(value,armor)
 if value==nil or value==false then return value end
 assert(type(value)=='table'and getmetatable(value)==nil and value.version==1,'Unsupported Transmog preset metadata')
 local out={version=1}
 for _,k in ipairs(fields)do
  local v=value[k];assert(type(v)=='string'and #v>0 and #v<=256 and not v:find('%c'),'Invalid Transmog preset field: '..k)
  out[k]=v
 end
 for k in pairs(value)do assert(k=='version'or out[k]~=nil,'Unknown Transmog preset field')end
 assert(type(armor)=='string'and out.appearance_id=='armor:'..armor:sub(3):lower(),'Transmog preset armor differs')
 return out
end
M.metadata=metadata
local function upvalue(fn,key)
 if type(fn)~='function'or not debug or type(debug.getupvalue)~='function'then return end
 for i=1,64 do local name,v=debug.getupvalue(fn,i);if not name then break end;if name==key then return v,i end end
end
local function fingerprint(fn)
 local available,util=pcall(require,'jit.util');if not available then return end
 -- Traces rewrite loop bytecodes; restore only this function's prototypes before hashing.
 if jit and jit.flush then pcall(jit.flush,fn,true)end
 local hash=0
 local function feed(value)
  value=tostring(value)
  for i=1,#value do hash=(hash*65599+value:byte(i))%4294967296 end
  hash=(hash*65599+255)%4294967296
 end
 local proto
 local function constant(value)
  local kind=type(value);feed(kind)
  if kind=='string'or kind=='boolean'then feed(value)
  elseif kind=='number'then feed(string.format('%.17g',value))
  elseif kind=='table'then
   local keys={};for k in pairs(value)do
    assert(type(k)=='string'or type(k)=='number'or type(k)=='boolean','Unsupported constant key')
    keys[#keys+1]=k
   end
   table.sort(keys,function(a,b)return type(a)..tostring(a)<type(b)..tostring(b)end)
   feed(#keys);for _,k in ipairs(keys)do
    constant(k);if value[k]==value then feed('template-slot')else constant(value[k])end
   end
  elseif kind=='proto'or kind=='function'then proto(value)
  elseif kind~='nil'then error('Unsupported Lua constant')end
 end
 proto=function(value)
  local info=util.funcinfo(value)
  assert(info.bytecodes and info.bytecodes<10000,'Unsupported Lua prototype')
  for _,key in ipairs({'params','isvararg','stackslots','upvalues','bytecodes','gcconsts','nconsts'})do feed(info[key])end
  for i=1,info.bytecodes-1 do feed(util.funcbc(value,i))end
  for i=0,info.nconsts-1 do constant(util.funck(value,i))end
  for i=1,info.gcconsts do constant(util.funck(value,-i))end
 end
 local ok,why=pcall(proto,fn);if not ok then return nil,tostring(why)end
 return string.format('%08x',hash)
end
M.fingerprint=fingerprint
-- Normalized LuaJIT prototypes of the inspected Alpha 8.8.1 source.
-- Table constants are sorted because string.dump order varies between runs.
-- Unknown builds fail closed instead of borrowing unverified private methods.
local supported={
 MODEL_HASHES={new='f52dad72',mask='8d968f67',compose='0a85fcfb',copy_snapshot='681281cc',validate_snapshot='9091224e'},
 APPLY_HASHES={new='2b86d0de',profile_differences='6ab384ec',bind='54a891ec',preflight='1425abae',session='ec5254ae',differences='da4b5661'}
}
function M.supported(model,apply)
 for name,wanted in pairs(supported.MODEL_HASHES)do
  local actual=fingerprint(model[name]);if actual~=wanted then return false,'Model.'..name..':'..tostring(actual)end
 end
 for name,wanted in pairs(supported.APPLY_HASHES)do
  local actual=fingerprint(apply[name]);if actual~=wanted then return false,'Apply.'..name..':'..tostring(actual)end
 end
 return next(supported.MODEL_HASHES)~=nil and next(supported.APPLY_HASHES)~=nil
end
function M.find(root,state)
 local seen,queue={},{{fn=root,depth=0}};local at=1
 while at<=#queue and at<=128 do
  local node=queue[at];at=at+1
  if type(node.fn)=='function'and not seen[node.fn]then
   seen[node.fn]=true
   local s=upvalue(node.fn,'state')
   if s==state then
    local model,apply=upvalue(node.fn,'Model'),upvalue(node.fn,'Apply')
    local capture,index=upvalue(node.fn,'capture')
    if type(model)=='table'and type(apply)=='table'and type(capture)=='function'and index then
     return {tick=node.fn,state=state,model=model,apply=apply,raw_capture=capture,capture_index=index,
      context=function()return upvalue(node.fn,'context')end}
    end
   end
   if node.depth<8 then
    for i=1,64 do
     local name,fn=debug.getupvalue(node.fn,i);if not name then break end
     if type(fn)=='function'and not seen[fn]and #queue<128 then queue[#queue+1]={fn=fn,depth=node.depth+1}end
    end
   end
  end
 end
end
function M.attach(binding,host)
 assert(upvalue(binding.tick,'capture')==binding.raw_capture,'DiverKit capture changed before attachment')
 local model,apply=binding.model,binding.apply
 local originals={copy=model.copy_snapshot,validate=model.validate_snapshot,compose=model.compose,new=apply.new}
 local self={status='attached'};local restorations={};local operations={}
 local function report(key,value)if host.report then host.report('diverkit.'..key,value)end end
 local function replace(t,k,fn)
  local old=t[k];t[k]=fn;restorations[#restorations+1]={t=t,k=k,old=old,fn=fn}
 end
 replace(model,'validate_snapshot',function(s)
  originals.validate(s);metadata(s.transmog,s.armor);return s
 end)
 replace(model,'copy_snapshot',function(s)
  local out=originals.copy(s);out.transmog=metadata(s.transmog,s.armor);return out
 end)
 replace(model,'compose',function(saved,current,mask)
  local out=originals.compose(saved,current,mask)
  local chosen=(mask==nil or mask.armor==true)and saved or current
  out.transmog=metadata(chosen.transmog,out.armor);return out
 end)
 local wrapped_capture=function()
  local sampled,snapshot=pcall(binding.raw_capture);if not sampled or not snapshot then return nil end
  local ok,value,why=pcall(host.capture,snapshot.armor)
  if not ok or value==nil then report('capture_blocked',ok and why or value);return nil end
  local valid,record=pcall(metadata,value,snapshot.armor)
  if not valid then report('capture_blocked',record);return nil end
  snapshot.transmog=record;return snapshot
 end
 assert(debug.setupvalue(binding.tick,binding.capture_index,wrapped_capture)=='capture','DiverKit capture binding changed')
 local function decorate(instance,context,raw_capture,reporter)
  if operations[instance]then return instance end
  local original_start,original_poll,original_cancel=instance.start,instance.poll,instance.cancel
  local state={};operations[instance]=state
  local methods={session=apply.session,preflight=apply.preflight,bind=apply.bind,profile_differences=apply.profile_differences}
  local driver={model=model,apply=apply,context=context,capture=binding.raw_capture,report=reporter or function()end,
   current=function()
    for name,fn in pairs(methods)do if apply[name]~=fn then return false end end
    return true
   end}
  local function stop(message)
   if state.op then pcall(state.op.cancel,message)end
   state.op=nil;state.stage=nil;instance.busy=false
   report('apply_failed',message);return message
  end
  replace(instance,'start',function(_,snapshot,now,mask)
   if state.op or instance.busy then return false,'A preset is already being applied'end
   local ok,target=pcall(function()
    local current=assert(binding.raw_capture(),'Current equipment unavailable')
    return model.compose(snapshot,current,mask)
   end)
   if not ok then return false,'Cannot apply: '..tostring(target)end
   if mask~=nil and mask.armor~=true then return original_start(instance,snapshot,now,mask)end
   if not target.transmog then
    local checked,active=pcall(host.active)
    if not checked then return false,'Cannot verify Transmog equipment: '..tostring(active)end
    if not active then return original_start(instance,snapshot,now,mask)end
   end
   local allowed,op,why=pcall(host.prepare,target.transmog or false,target.armor,driver)
   if not allowed or not op then return false,'Cannot apply: '..tostring(allowed and why or op)end
   state.op=op;state.last_poll=now;state.started=now;state.native_notice=nil
   local others=model.mask(mask,'apply');others.armor=false
   local has_others=false;for k,v in pairs(others)do if v and target[k]~=nil then has_others=true end end
   if has_others then
    local ran,accepted,message=pcall(original_start,instance,snapshot,now,others)
    if not ran or not accepted then return false,stop('Apply incomplete: '..tostring(ran and message or accepted))end
    state.stage='equipment';instance.busy=true
   else state.stage='armor';instance.busy=true end
   report('apply_requested',target.transmog and target.transmog.label or 'original armor')
   return true,'Applying preset and Transmog armor...'
  end)
  replace(instance,'poll',function(_,now)
   if not state.op then return original_poll(instance,now)end
   state.last_poll=now
   local ok,message=pcall(function()
    if now<state.started or now-state.started>20000 then return stop('Apply incomplete: compatibility operation timed out')end
    if state.stage=='equipment'then
     local result=original_poll(instance,now)
     if instance.busy then return nil end
     if result~='Preset applied'and result~='Preset applied; booster in use - skipped'then
      return stop(result or 'Apply incomplete: native equipment was not verified')
     end
     state.native_notice=result;state.stage='armor';instance.busy=true
    end
    if state.stage=='armor'then
     local began,why=state.op.begin(now)
     if not began then return stop('Apply incomplete: '..tostring(why))end
     state.stage='verify'
    end
    local phase,why=state.op.poll(now)
    if phase=='complete'then
     state.op=nil;state.stage=nil;instance.busy=false;report('apply_verified',true)
     return state.native_notice or 'Preset applied'
    elseif phase=='failed'then return stop('Apply incomplete: '..tostring(why))end
   end)
   if not ok then return stop('Apply incomplete: '..tostring(message))end
   return message
  end)
  replace(instance,'cancel',function(_,message)
   if not state.op then return original_cancel(instance,message)end
   pcall(original_cancel,instance,message)
   return stop('Apply verification interrupted: '..tostring(message))
  end)
  return instance
 end
 replace(apply,'new',function(context,capture,reporter)
  return decorate(originals.new(context,capture,reporter),context,capture,reporter)
 end)
 local existing=upvalue(binding.tick,'activation')
 if existing then decorate(existing,binding.context(),binding.raw_capture,host.report)end
 function self:busy()for _,s in pairs(operations)do if s.op then return true end end;return false end
 function self:watch(now)
  for instance,s in pairs(operations)do
   if s.op and (now<s.last_poll or now-s.last_poll>2000)then instance:cancel('DiverKit stopped polling')end
  end
 end
 function self:shutdown()
  for instance,s in pairs(operations)do if s.op then instance:cancel('Transmog stopped')end end
  if upvalue(binding.tick,'capture')==wrapped_capture then debug.setupvalue(binding.tick,binding.capture_index,binding.raw_capture)end
  for i=#restorations,1,-1 do local r=restorations[i];if r.t[r.k]==r.fn then r.t[r.k]=r.old end end
  self.status='detached'
 end
 report('attached','Alpha 8.8.1 Lua adapter')
 return self
end
function M.new(host)
 local self={status='absent'};local attached,next_scan,last_state=nil,0,nil
 function self:step(now,root,state)
  if attached then
   if state~=last_state then attached:shutdown();attached=nil;self.status='absent';next_scan=0
   else attached:watch(now);return end
  end
  if now<next_scan then return end;next_scan=now+1000
  if type(state)~='table'then self.status='absent';return end
  if last_state==state and self.status=='unsupported'then return end
  last_state=state
  if not(debug and debug.getupvalue and debug.setupvalue)then
   self.status='unsupported'
   if host.report then host.report('diverkit.unsupported','Lua interface inspection unavailable; compatibility adapter disabled')end
   return
  end
  local binding=M.find(root,state);if not binding then self.status='waiting';return end
  local recognized,reason=M.supported(binding.model,binding.apply)
  if not recognized then
   self.status='unsupported'
   if host.report then host.report('diverkit.unsupported','Unrecognized Lua interfaces; compatibility adapter disabled: '..tostring(reason))end
   return
  end
  attached=M.attach(binding,host);self.status='attached'
 end
 function self:busy()return attached and attached:busy()or false end
 function self:shutdown()if attached then attached:shutdown();attached=nil end end
 return self
end
return M
