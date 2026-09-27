"""Creator stats use narrow body evidence and recover from transient failures."""
from test_creator_failure_main import run

SETUP=r'''
local body_available=false
local base_calls=0
ArmorStatResolver={new=function()return {step=function()return 'ready',{
 contract={},verify=function()return true end}end}end}
PlayerCustomizationProbe={new=function()return {
 sample=function()error('creator requested full passive/equipment validation')end,
 sample_body_type=function()
  if body_available then return {body_type=1}end
  return nil,'body unavailable'
 end}end}
ArmorBaseStats={choices=function(_,body)
 assert(body==1);base_calls=base_calls+1
 return {{stats_ids={'stats-a'},verified=true,base_values={armor_rating=50,speed=550,stamina_regen=125}}}
end}
'''


def test_body_failure_is_reported_and_recovers_without_restart_or_passive_read():
    run(r'''
assert(result.context.stats_status=='player_unavailable'and base_calls==0)
for i=1,20 do advance()end
assert(logged_count('stats.body_wait=')==1)
body_available=true
for i=1,11 do advance()end
assert(result.context.stats_status=='ready'and base_calls==1)
assert(logged_count('runtime.error=')==0 and logged_count('stats.unavailable=')==0)
''', setup=SETUP)


def test_transient_formula_read_failure_does_not_disable_stats_permanently():
    run(r'''
body_available=true
local original=ArmorBaseStats.choices
ArmorBaseStats.choices=function()error('temporary unreadable stat data')end
for i=1,11 do advance()end
assert(result.context.stats_status=='unavailable')
ArmorBaseStats.choices=original
for i=1,11 do advance()end
assert(result.context.stats_status=='ready'and base_calls==1)
''', setup=SETUP)
