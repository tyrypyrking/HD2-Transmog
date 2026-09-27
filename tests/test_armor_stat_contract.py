"""Captured UI constants plus an explicit witness for binary truncation tables."""
from pathlib import Path
import math
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def run(script):
    result=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr


def test_current_image_and_exact_lookup_witness_are_required():
    run(r'''
local K=dofile('src/armor_stat_contract.lua')
local M=dofile('src/armor_base_stats.lua')
local D=dofile('src/catalog_data.lua')
local bare=K.unverified();assert(not bare.verified and bare.armor_scale==50 and bare.one==1 and bare.zero==0)
assert(not K.for_image(1790161983))
local tables={masks={},word_indices={0,1}}
for i=1,16 do tables.masks[i]=2^(i-1)-1 end
local c=assert(K.for_image(1790161983,tables));assert(c.verified and c.rounding=='nearest_ties_away')
local result=assert(M.calculate(D.kits[0x61b31723],0,c))
assert(result.verified and result.base_values.armor_rating==100 and result.base_values.speed==500 and result.base_values.stamina_regen==100)
assert(not K.for_image(1790161984,tables),'new image must not inherit verified status')
tables.masks[14]=0;assert(not K.for_image(1790161983,tables))
tables.masks[14]=2^13-1;tables.word_indices[1]=1;assert(not K.for_image(1790161983,tables))
bare.coefficients.armor_rating[1]=999;assert(K.unverified().coefficients.armor_rating[1]==0)
''')


def bits(value):
    return struct.unpack('<I',struct.pack('<f',value))[0]


def number(value):
    return struct.unpack('<f',struct.pack('<I',value))[0]


def truncator(value,scale):
    """Emulate the captured integer instructions with the required mask witness."""
    exponent=(value>>23)&255
    if exponent==255:
        return value,2 if value&0x7fffff else 1
    if value&0x7fffffff==0:
        return value,0
    clear=150-exponent-scale
    if clear<=0:
        return value,0
    if clear>=24:
        return value&0x80000000,-1
    masks=[(1<<i)-1 for i in range(16)]
    word_indices=[0,1]
    word=word_indices[clear>>4]
    mask=masks[clear&15]<<(16*word)
    if word:
        mask|=0xffff
    removed=value&mask
    return value&~mask,-1 if removed else 0


def native_round(value):
    value,result=truncator(value,1)
    if result in (1,2):
        return number(value)
    value,result=truncator(value,0)
    if result:
        return number(bits(number(value)+(-1 if value&0x80000000 else 1)))
    return number(value)


def test_truncation_to_half_then_integer_implements_nearest_ties_away():
    values=[0,1,0x80000000,0x80000001,bits(8388607.5),bits(-8388607.5)]
    # Exact half ties and their immediately adjacent float32 values, across
    # every Armor-card range and on both sides of zero.
    for whole in range(-600,601):
        middle=bits(whole+0.5)
        values.extend([middle-1,middle,middle+1])
    for raw in values:
        value=number(raw)
        expected=math.ceil(value-0.5) if value<0 else math.floor(value+0.5)
        assert native_round(raw)==expected,(value,native_round(raw),expected)


def test_verified_rounding_contract_reaches_pure_calculator_at_an_exact_half():
    run(r'''
local K=dofile('src/armor_stat_contract.lua')
local M=dofile('src/armor_base_stats.lua')
local witness={masks={},word_indices={0,1}};for i=1,16 do witness.masks[i]=2^(i-1)-1 end
local c=assert(K.for_image(1790161983,witness))
local r={category=0,bodies={{type=3,pieces={
 {slot=2,kind=0,weight=0},{slot=4,kind=0,weight=1},{slot=5,kind=0,weight=1},{slot=6,kind=0,weight=1}}}}}
local value=assert(M.calculate(r,0,c))
assert(value.verified and value.unrounded.armor_rating==87.5 and value.base_values.armor_rating==88)
''')
