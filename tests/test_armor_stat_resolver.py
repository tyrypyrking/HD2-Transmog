"""Synthetic PE + real x64 decoder; semantic proof never calls generated code."""
import json
from pathlib import Path
import re
import struct
import subprocess

import pytest
from test_runtime_adapter import BASE, DATA, ROOT, TEXT, fixture


def recipes():
    text=(ROOT/'src/armor_stat_semantics.lua').read_text()
    return {key:[json.loads(line.rstrip(',')) for line in body.splitlines() if line]
            for key,body in re.findall(r'\["(\w+)"\]=\{\n(.*?)\n\},',text,re.S)}


def assembly_recipe(kind,ops,prefix):
    calls={'ui':['coefficient','modifier'],'coefficient':['cookie_stub'],
           'rounding':['truncation'],'modifier':[],'truncation':[]}
    scalars={'ui':['armor_scale','speed_scale'],'modifier':['one'],
             'rounding':['minus_one','one'],'coefficient':[],'truncation':[]}
    lines=[]
    for i,op in enumerate(ops,1):
        lines.append(f'{prefix}_row_{i}:')
        op=re.sub(r'row:(\d+)',lambda m:f'{prefix}_row_{m[1]}',op)
        op=re.sub(r'outside:(\d+)',lambda m:f'{prefix}_outside_{m[1]}',op)
        op=re.sub(r'call:(\d+)',lambda m:calls[kind][int(m[1])-1],op)
        op=re.sub(r'\[scalar:(\d+)\]',lambda m:'[rip+'+scalars[kind][int(m[1])-1]+']',op)
        op=op.replace('[catalog]','[rip+catalog_slot]').replace('[image_base]','[rip+image_base]')
        op=op.replace('coefficient:1','stamina_coeff').replace('coefficient:2','speed_coeff').replace('coefficient:3','armor_coeff')
        op=op.replace('initial_float','INITIAL')
        op=re.sub(r'\b(byte|word|dword|qword) \[',r'\1 ptr [',op)
        lines.append(op)
    return '\n'.join(lines)


def image(tmp_path,mode='ok',shift=0,timestamp=123456789):
    path,_=fixture(tmp_path)
    memory=bytearray(path.read_bytes());parts=recipes()
    ui=TEXT+shift;constant=DATA+0x1000+shift
    lines=['.intel_syntax noprefix','.section .text','.global image_base','image_base:',
           '.equ INITIAL, 0x42c80000',f'.org {ui}','ui_start:']
    def ui_code(prefix):
        return '\n'.join([
            'movss xmm8, [rip+one]','xorps xmm9,xmm9',
            f'jmp {prefix}_row_1',
            f'{prefix}_outside_1:','xor eax,eax','mov [rbp],rax','mov [rbp+8],eax',
            f'{prefix}_outside_2:','lea rcx,[rsi+0x16c0]','mov dword ptr [rsi+0x6308],3',
            'mov edx,0x81b743c1','call label_stub','lea rcx,[rsi+0x1978]',
            'mov edx,0x5c2d0ceb','call label_stub','lea rcx,[rsi+0x1c30]',
            'mov edx,0x10fb893b','call label_stub',
            f'jmp {prefix}_round',
            assembly_recipe('ui',parts['ui'],prefix),
            f'{prefix}_round:','movaps xmm0,xmm7','call rounding','cvttss2si ebx,xmm0','ret',
            f'{prefix}_early_ret:','ret'])
    lines += [ui_code('ui'),'ui_end:','int3']
    if mode=='ambiguous':
        lines += [f'.org {TEXT+0x1000+shift}','ui_second:',ui_code('other'),'ui_second_end:','int3']
    for kind,offset in [('coefficient',0x3000),('modifier',0x4000),('rounding',0x5000),('truncation',0x6000)]:
        lines += [f'.org {offset+shift}',kind+':']
        if kind=='coefficient':
            lines += ['mov r11,rsp','sub rsp,0x128','xor r10d,r10d','movss xmm3,[rip+one]']
        lines += [assembly_recipe(kind,parts[kind],kind),'int3']
    lines += [f'.org {0x7000+shift}','cookie_stub:','ret','int3','label_stub:','ret','int3',
              f'.org {constant}','catalog_slot:','.quad 0','one:','.float 1','minus_one:','.float -1',
              'armor_scale:','.float 50','speed_scale:','.float 5','stamina_coeff:','.float .75,1,1.5',
              'speed_coeff:','.float 1.1,1,.9','armor_coeff:','.float 0,1,2',
              'low_masks:','.short '+','.join(str(2**i-1) for i in range(16)),
              '.balign 8','word_indices:','.quad 0,1']
    source='\n'.join(lines)+'\n'
    if mode=='arithmetic':source=source.replace('subss xmm4, xmm8','addss xmm4, xmm8',1)
    if mode=='gather':source=source.replace('divss xmm1, xmm2','mulss xmm1, xmm2',1)
    if mode=='label':source=source.replace('mov edx,0x5c2d0ceb','mov edx,0x5c2d0cec',1)
    if mode=='continuation':source=source.replace('jmp ui_outside_2','jmp ui_early_ret',1)
    if mode=='unreachable_rounding':source=source.replace('jmp ui_round','jmp ui_early_ret',1)
    if mode=='changed_values':
        source=source.replace('.equ INITIAL, 0x42c80000','.equ INITIAL, 0x42f00000').replace('.float 50','.float 60').replace('.float 1.1,1,.9','.float 1.2,1,.9')
    asm=tmp_path/'stat.S';obj=tmp_path/'stat.o';elf=tmp_path/'stat.elf';binary=tmp_path/'stat.bin'
    asm.write_text(source)
    for command in [['as','--64','-o',str(obj),str(asm)],['ld','-Ttext=0','-e','image_base','-o',str(elf),str(obj)],
                    ['objcopy','-O','binary','--only-section=.text',str(elf),str(binary)]]:
        completed=subprocess.run(command,capture_output=True,text=True)
        assert completed.returncode==0,completed.stderr
    symbols={}
    output=subprocess.check_output(['nm','-n',str(elf)],text=True)
    for line in output.splitlines():
        cells=line.split()
        if len(cells)==3:symbols[cells[2]]=int(cells[0],16)
    raw=binary.read_bytes()
    memory[ui:0x7010+shift]=raw[ui:0x7010+shift]
    memory[constant:len(raw)]=raw[constant:]
    struct.pack_into('<I',memory,0x80+8,timestamp)
    # Read-only data, with writable/execute variants rejected by the resolver.
    flags=0x40000040 if mode!='writable_constants'else 0xc0000040
    struct.pack_into('<I',memory,0x80+24+240+40+36,flags)
    pdata=DATA+0x200
    entries=[(symbols['ui_start'],symbols['ui_end'])]
    if mode=='ambiguous':entries.append((symbols['ui_second'],symbols['ui_second_end']))
    struct.pack_into('<I',memory,0x80+132,16)
    struct.pack_into('<II',memory,0x80+160,pdata,len(entries)*12)
    for i,(a,b)in enumerate(entries):struct.pack_into('<III',memory,pdata+i*12,a,b,0)
    if mode=='mask':struct.pack_into('<H',memory,symbols['low_masks']+26,0)
    if mode=='word_index':struct.pack_into('<Q',memory,symbols['word_indices']+8,0)
    path.write_bytes(memory)
    return path,symbols


@pytest.mark.parametrize('mode',['ok','arithmetic','gather','label','mask','word_index','writable_constants','ambiguous','changed_values','continuation','unreachable_rounding'])
def test_semantic_resolver_extracts_current_contract_or_isolates_failure(tmp_path,mode):
    path,symbols=image(tmp_path,mode)
    script=f'''
local M=dofile('src/armor_stat_resolver.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local bytes=f:read('*a');f:close()
local reads,large,valid=0,0,true
local bridge={{base={BASE},armor_catalog={BASE+symbols['catalog_slot']},verify=function()return valid end,
 read=function(at,n)
  reads=reads+1;assert(n>0 and n<=262144);if n>200000 then large=large+1 end
  local off=at-{BASE};if off<0 or off+n>#bytes then return nil end;return bytes:sub(off+1,off+n)
 end}}
local probe=M.new(bridge);local state,result
for i=1,1000 do local before=large;state,result=probe:step();assert(large-before<=1);if state~='resolving'then break end end
if {json.dumps(mode)}=='ok'or {json.dumps(mode)}=='changed_values'then
 assert(state=='ready',tostring(result));assert(result.contract.verified and result.verify())
 assert(result.provenance.image_timestamp==123456789,'timestamp should be provenance only')
 local c=result.contract
 assert(c.rounding=='nearest_ties_away'and c.one==1 and c.zero==0)
 local Stats=dofile('src/armor_base_stats.lua');local Data=dofile('src/catalog_data.lua')
 local value=assert(Stats.calculate(Data.kits[0x1f9bfa78],0,c))
 if {json.dumps(mode)}=='ok'then assert(c.armor_scale==50 and value.base_values.armor_rating==50 and value.base_values.speed==550)
 else assert(c.armor_scale==60 and c.initial_value==120 and value.base_values.armor_rating==60 and value.base_values.speed==720)end
 local at={symbols['low_masks']};bytes=bytes:sub(1,at)..string.char(99)..bytes:sub(at+2)
 assert(not result.verify(),'changed read-only table must invalidate retained contract')
else
 assert(state=='failed','unexpected stat capability: '..state..' '..tostring(result))
 if {json.dumps(mode)}=='ambiguous'then assert(tostring(result):find('ambiguous',1,true),tostring(result))end
 if {json.dumps(mode)}=='arithmetic'then assert(tostring(result):find('changed ui operation',1,true),tostring(result))end
 if {json.dumps(mode)}=='gather'then assert(tostring(result):find('changed coefficient operation',1,true),tostring(result))end
 local before=reads;probe:step();assert(reads==before,'terminal optional failure must not rescan')
end
'''
    run=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr


def test_relocated_code_tables_and_new_timestamp_do_not_require_new_rvas(tmp_path):
    path,symbols=image(tmp_path,shift=0x20000,timestamp=987654321)
    script=f'''
local M=dofile('src/armor_stat_resolver.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local bytes=f:read('*a');f:close()
local valid=true
local p=M.new({{base={BASE+0x10000000},armor_catalog={BASE+0x10000000+symbols['catalog_slot']},verify=function()return valid end,
 read=function(at,n)local off=at-{BASE+0x10000000};return bytes:sub(off+1,off+n)end}})
local phase,result;for i=1,1000 do phase,result=p:step();if phase~='resolving'then break end end
assert(phase=='ready',tostring(result));assert(result.contract.verified and result.provenance.image_timestamp==987654321)
valid=false;assert(not result.verify())
'''
    result=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_constant_race_during_resolution_never_publishes_a_contract(tmp_path):
    path,symbols=image(tmp_path)
    script=f'''
local M=dofile('src/armor_stat_resolver.lua')
local f=assert(io.open({json.dumps(str(path))},'rb'));local bytes=f:read('*a');f:close()
local reads=0;local p=M.new({{base={BASE},armor_catalog={BASE+symbols['catalog_slot']},verify=function()return true end,
 read=function(at,n)
  local off=at-{BASE};local raw=bytes:sub(off+1,off+n)
  if off=={symbols['one']} and n==4 then reads=reads+1;if reads==2 then return string.char(0,0,0,64)end end
  return raw
 end}})
local phase,reason;for i=1,1000 do phase,reason=p:step();if phase~='resolving'then break end end
assert(phase=='failed'and p.result==nil,tostring(reason))
assert(tostring(reason):find('changed',1,true),tostring(reason))
'''
    result=subprocess.run(['luajit','-'],input=script,text=True,cwd=ROOT,capture_output=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
