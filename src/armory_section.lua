-- Scheduling for the custom Armor section. Readiness observations never spend
-- the native-construction budget; only a completed construction attempt does.
-- This module has no native calls and never interprets unreadable UI as an exit.
local M={}
function M.new(options)
 options=options or {}
 local retry_ms=options.retry_ms or 250
 local max_failures=options.max_failures or 1
 assert(type(retry_ms)=='number'and retry_ms>=0,'nonnegative section retry delay required')
 assert(type(max_failures)=='number'and max_failures%1==0 and max_failures>=1,'positive construction failure budget required')
 local self={phase='waiting',epoch=0,failures=0,next_at=0,ready=false}
 local token,model_key,inside=nil,nil,false
 local function rearm(now,reason)
  self.epoch=self.epoch+1;self.phase='waiting';self.failures=0
  self.next_at=now;self.reason=reason
 end
 local function snapshot(changed)
  return {changed=changed==true,epoch=self.epoch,phase=self.phase,failures=self.failures,
   ready=self.ready,reason=self.reason}
 end
 function self:observe(now,observation)
  observation=observation or {};local changed=false
  if observation.armor==false then
   -- A confirmed departure allows another attempt even when the game reuses
   -- its menu pointer/token on the next entry.
   if inside then rearm(now,'left Armor');changed=true end
   inside=false;self.ready=false;model_key=nil
   return snapshot(changed)
  end
  if observation.armor==nil then self.ready=false;return snapshot(false)end
  local next_token=observation.token
  if not inside or(token~=nil and next_token~=nil and next_token~=token)then
   rearm(now,'entered Armor');changed=true;model_key=nil
  elseif model_key~=nil and observation.model_key~=nil and observation.model_key~=model_key then
   rearm(now,'native Armor model changed');changed=true
  end
  inside=true;if next_token~=nil then token=next_token end
  if observation.model_key~=nil then model_key=observation.model_key end
  self.ready=observation.ready==true
  return snapshot(changed)
 end
 function self:due(now)
  return inside and self.ready and self.phase=='waiting'and now>=self.next_at
 end
 function self:begin(now)
  if not self:due(now)then return false end
  self.phase='preparing';self.reason=nil;return true
 end
 function self:defer(now,reason)
  if self.phase=='blocked'or self.phase=='restore_failed'then return false end
  self.phase='waiting';self.next_at=now+retry_ms;self.reason=reason;return true
 end
 function self:complete(now,result)
  result=result or {};local phase=result.phase
  if phase=='active'then self.phase='active';self.reason=nil
  elseif phase=='waiting'or result.retryable==true then self:defer(now,result.error)
  elseif phase=='retired'then self:invalidate(now,result.error or 'native Armor model retired')
  else
   self.failures=self.failures+1;self.reason=result.error or phase or 'custom construction failed'
   if phase=='restore_failed'then self.phase='restore_failed'
   elseif self.failures>=max_failures then self.phase='blocked'
   else self.phase='waiting';self.next_at=now+retry_ms end
  end
  return snapshot(false)
 end
 function self:invalidate(now,reason)
  rearm(now,reason or 'native Armor model changed');return snapshot(true)
 end
 function self:request(now)
  rearm(now,'custom Armor list changed');return snapshot(true)
 end
 function self:pause(reason)
  self.phase='blocked';self.reason=reason;return snapshot(false)
 end
 function self:status()return snapshot(false)end
 return self
end
return M
