"""Read-only producer discovery against synthetic PE64 code and metadata."""
import json
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x180000000


def fixture(tmp_path, mode='normal'):
    data = bytearray(0x60000)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<HH', data, 0x84, 0x8664, 2)
    struct.pack_into('<H', data, 0x94, 240)
    struct.pack_into('<H', data, 0x98, 0x20b)
    struct.pack_into('<I', data, 0xd0, len(data))
    struct.pack_into('<I', data, 0x80 + 132, 16)
    for i, (start, length, flags) in enumerate(((0x1000, 0x40000, 0x60000020), (0x45000, 0x10000, 0x40000040))):
        entry = 0x80 + 24 + 240 + i * 40
        struct.pack_into('<II', data, entry + 8, length, start)
        struct.pack_into('<I', data, entry + 36, flags)
    functions = []

    def add(start, code):
        data[start:start + len(code)] = code
        functions.append((start, start + len(code), 0))

    def store(field):
        return b'\xc7\x81' + struct.pack('<II', field, 7)

    if mode == 'hit_cap':
        add(0x21000, b'\xb8\x14\x1f\x09\x00' * 600 + b'\xc3')
    elif mode in ('fragment_cap', 'output_cap'):
        for i in range(70 if mode == 'fragment_cap' else 55):
            add(0x20000 + i * 0x100, store(0x91f14) * (1 if mode == 'fragment_cap' else 9) + b'\xc3')
    elif mode == 'large_fragment':
        add(0x21000, store(0x91f14) + b'\x90' * 8200 + b'\xc3')
    else:
        code = store(0x91f14)
        callsite = 0x21000 + len(code)
        code += b'\xe8' + struct.pack('<i', 0x22000 - callsite - 5)
        code += b'\xc3'
        add(0x21000, code)
        # Reads, immediates and an address calculation are not writes.
        add(0x21100, bytes.fromhex('8b81141f0900b8141f0900488d8148270900c3'))
        # A valid-looking store in unreachable embedded data is not code.
        add(0x21200, b'\xeb\x0a' + store(0x92984) + b'\xc3')
        # A conditional branch reaches a real writer after another path returns.
        add(0x21300, b'\x85\xc0\x74\x01\xc3' + store(0x92748) + b'\xc3')
        add(0x21400, bytes.fromhex('4489848190290900c3'))
        # A leaf call remains a semantic edge; there is no fabricated PE entry.
        code = store(0x92984)
        callsite = 0x21500 + len(code)
        add(0x21500, code + b'\xe8' + struct.pack('<i', 0x24000 - callsite - 5) + b'\xc3')
        add(0x22000, bytes.fromhex('83fa20c3'))
        data[0x24000] = 0xc3
        # Displacement literal straddles the 4KiB scanning chunk boundary.
        add(0x22ffb, store(0x92990) + b'\xc3')
    functions.sort()
    if mode == 'overlap':
        functions[1] = (functions[0][0] + 4, functions[1][1], 0)
    for i, entry in enumerate(functions):
        struct.pack_into('<III', data, 0x45000 + i * 12, *entry)
    struct.pack_into('<II', data, 0x80 + 160, 0x45000, 0 if mode == 'no_pdata' else len(functions) * 12)
    path = tmp_path / 'producer-memory.bin'
    path.write_bytes(data)
    return path


def run(tmp_path, code, mode='normal'):
    path = fixture(tmp_path, mode)
    script = r'''
local P=dofile('src/native_grid_producers.lua')
local f=assert(io.open(PATH,'rb'));local memory=f:read('*a');f:close()
local alive=true;local reads,bytes=0,0;local read_hits={}
local bridge={base=BASE,verify=function()return alive end,read=function(at,n)
 reads=reads+1;bytes=bytes+n
 local rva=at-BASE;assert(rva>=0 and n<=8192 and rva+n<=#memory)
 read_hits[rva..':'..n]=(read_hits[rva..':'..n]or 0)+1
 return memory:sub(rva+1,rva+n)
end}
local p=P.new(bridge,{solver=0x22000,highlight=0x21000})
assert(reads==0 and p.phase=='scanning')
local function finish()
 for i=1,2000 do
  reads,bytes=0,0;p:step()
  assert(reads<=64 and bytes<=16384,'per-frame read limit exceeded')
  if p.phase~='scanning'then return p.phase,p:report()end
 end
 error('producer scan did not finish')
end
'''.replace('PATH', json.dumps(str(path))).replace('BASE', str(BASE))
    result = subprocess.run(['luajit', '-'], input=script + code, text=True,
                            capture_output=True, cwd=ROOT, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_exact_explicit_store_classifier_rejects_sources_immediates_and_nearby_offsets(tmp_path):
    run(tmp_path, '''
assert(P.write_field('mov dword [rcx+0x91f14], 0x0')=='row_count')
assert(P.write_field('mov [rcx+rax*4+0x92990], r8d')=='offers')
assert(P.write_field('inc dword [rdi+0x92748]')=='group_count')
assert(P.write_field('xchg eax, [rbx+0x92984]')=='item_count')
for _,op in ipairs({'mov eax, [rcx+0x91f14]','cmp [rcx+0x91f14], eax','test [rcx+0x91f14], eax',
 'lea rax, [rcx+0x91f14]','mov eax, 0x91f14','mov [rcx+0x929900], eax',
 'mov [rcx-0x91f14], eax','mov [rip+0x91f14], eax'})do assert(P.write_field(op)==nil,op)end
''')


def test_semantic_scan_uses_reachable_pe_fragments_and_reports_direct_callees(tmp_path):
    run(tmp_path, '''
local phase,text=finish();assert(phase=='complete',text)
assert(text:find('candidate fragment=0x00021000',1,true))
assert(text:find('candidate fragment=0x00021300',1,true))
assert(text:find('candidate fragment=0x00021400',1,true))
assert(text:find('candidate fragment=0x00022ffb',1,true))
assert(not text:find('candidate fragment=0x00021100',1,true))
assert(not text:find('candidate fragment=0x00021200',1,true))
assert(text:find('callee target=0x00022000',1,true) and text:find('cmp edx, +0x20',1,true))
assert(text:find('target=0x00024000 executable=true declared_fragment=none',1,true))
assert(text:find('model_object_identity_unproven=true',1,true))
assert(not text:find('c781141f0900',1,true))
assert(p.window_last-p.window_first<=262144)
''')


@pytest.mark.parametrize('mode,reason', [('no_pdata', 'metadata unavailable'), ('overlap', 'overlapping')])
def test_absent_or_invalid_metadata_fails_without_publishing_candidates(tmp_path, mode, reason):
    run(tmp_path, f'''
local phase,text=finish();assert(phase=='failed' and text:find({json.dumps(reason)},1,true),text)
assert(not text:find('candidate fragment=',1,true))
''', mode)


@pytest.mark.parametrize('mode,reason', [('hit_cap', 'raw_hit_cap'), ('fragment_cap', 'fragment_cap'),
                                        ('output_cap', 'output_cap'), ('large_fragment', 'large_fragments')])
def test_caps_are_terminal_and_explicit_about_incomplete_coverage(tmp_path, mode, reason):
    run(tmp_path, f'''
local phase,text=finish();assert(phase=='complete',text)
assert(text:find('coverage=partial',1,true) and text:find('limitation={reason}',1,true),text)
assert(#text<70000)
local before=reads;p:step();assert(reads==before,'completed scan unexpectedly repeated')
''', mode)


def test_changed_anchor_or_candidate_invalidates_the_report(tmp_path):
    run(tmp_path, '''
p:step();alive=false
local phase,text=finish();assert(phase=='failed' and not text:find('candidate fragment=',1,true))
''')
    run(tmp_path, '''
local original=bridge.read
bridge.read=function(at,n)
 local value=original(at,n)
 if at==bridge.base+0x21000 and n==16 and read_hits['135168:16']>=2 then return string.rep('\0',n)end
 return value
end
local phase,text=finish();assert(phase=='failed' and text:find('changed during scan',1,true),text)
assert(not text:find('candidate fragment=',1,true))
''')


def test_pending_report_contains_progress_only_not_unverified_snippets(tmp_path):
    run(tmp_path, '''
for i=1,3 do p:step()end
assert(p.phase=='scanning')
local text=p:report();assert(text:find('phase=scanning',1,true))
assert(not text:find('candidate fragment=',1,true))
''')


@pytest.mark.parametrize('marker',['(unknown)','(incomplete)'])
def test_unproved_decoder_instruction_stops_reachability_before_a_writer(tmp_path,marker):
    run(tmp_path, f'''
local rows={{{{rva=0x21000,op={json.dumps(marker)}}},
 {{rva=0x21001,op='mov dword [rcx+0x91f14], 0x0'}},{{rva=0x2100b,op='ret'}}}}
local reach,edges=P.reachable(rows,0x21000,0x2100c)
assert(not reach[1] and not reach[2] and edges==1)
''')


def test_native_grid_producer_scan_is_explicit_and_separate_from_active_grid_state():
    from test_native_grid import run_lua, SELECTION, HIGHLIGHT
    from test_native_grid_model import LOGICAL_PROOF
    run_lua(SELECTION + HIGHLIGHT + LOGICAL_PROOF + '''
local created,steps=0,0
NativeGridProducers={new=function(reader,anchors)
 created=created+1;assert(anchors.solver==solver_rva and anchors.highlight==highlight_rva)
 assert(reader.verify() and type(reader.read)=='function')
 local job={phase='scanning'}
 function job:step()steps=steps+1;if steps==2 then self.phase='complete'end;return self.phase end
 function job:report()return 'phase='..self.phase end
 return job
end}
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
assert(created==0 and g:producer_status()=='idle' and g:producer_report()==nil)
assert(g:start_producer_scan()=='scanning' and created==1 and steps==0)
assert(g:start_producer_scan()=='scanning' and created==1)
assert(g:step()=='ready' and steps==1)
assert(g:step_producer_scan()=='complete' and steps==2 and g.phase=='ready')
assert(g:producer_report()=='phase=complete')
assert(consumed==0 and moves==0 and highlighted==0)
assert(g:snapshot(catalog).identity_mapping_verified)
''')


def test_unavailable_producer_anchors_do_not_affect_normal_grid_operation():
    from test_native_grid import run_lua
    run_lua('''
local g=G.new(bridge,nil,backend);assert(ready(g)=='ready')
local phase,why=g:start_producer_scan();assert(not phase and why:find('anchors unavailable'))
assert(g:producer_status()=='idle' and g:consume_select())
''')
