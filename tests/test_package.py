"""Verify the shipped archive, not just the loose source files."""
from pathlib import Path
import json
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor/BingusSharedLoader/scripts'))
from archive import resource_hash


def test_installable_package_and_luajit_discovery_entry():
    subprocess.run([sys.executable,'tools/build.py'],cwd=ROOT,check=True,capture_output=True,text=True)
    package=ROOT/'dist/HD2-Transmog-Foundation-0.1.2-debug.zip'
    first=package.read_bytes()
    with zipfile.ZipFile(package) as z:
        assert set(z.namelist()) == {
            'manifest.json','README.txt','THIRD-PARTY-LICENSES.txt','mod-icon.png','Addon/9ba626afa44a3aa3.patch_0',
            'Addon/9ba626afa44a3aa3.patch_0.stream','Addon/9ba626afa44a3aa3.patch_0.gpu_resources',
            'LookStats/9ba626afa44a3aa3.patch_0','LookStats/9ba626afa44a3aa3.patch_0.stream',
            'LookStats/9ba626afa44a3aa3.patch_0.gpu_resources'}
        assert b'0.1.2-debug' in z.read('README.txt')
        manifest=json.loads(z.read('manifest.json'))
        assert manifest['IconPath']=='mod-icon.png'
        assert z.read(manifest['IconPath'])==(ROOT/'assets/mod-icon.png').read_bytes()
        assert manifest['Guid']=='46b51e90-d243-457a-ae92-8d7e6875c0ea'
        assert manifest['Options'][0]['Include']==[]
        assert manifest['Options'][0]['Image']==manifest['IconPath']
        modes=manifest['Options'][0]['SubOptions']
        assert all(mode['Image']==manifest['IconPath'] for mode in modes)
        assert [mode['Include'] for mode in modes]==[['Addon'],['LookStats']]
        alternate=z.read('LookStats/9ba626afa44a3aa3.patch_0')
        alt_entry=struct.unpack_from('<7Q6I',alternate,104)
        assert alt_entry[0]==resource_hash('mods/hd2transmog/foundation')
        alt_body=alternate[alt_entry[2]+8:alt_entry[2]+alt_entry[7]]
        assert b'local STATS_FOLLOW_LOOK = true' in alt_body
        assert subprocess.run(['luajit','-e','assert(loadstring(io.read("*a")))'],
                              input=alt_body,capture_output=True).returncode==0
        archive=z.read('Addon/9ba626afa44a3aa3.patch_0')
    magic,version,count=struct.unpack_from('<III',archive)
    assert (magic,version,count)==(0xf0000011,1,1)
    entry=struct.unpack_from('<7Q6I',archive,104)
    assert entry[0]==resource_hash('mods/hd2transmog/foundation')
    assert entry[0]!=resource_hash('core/wwise/lua/wwise_flow_callbacks')
    assert entry[1]==0xa14e8dfa2cd117e2
    offset,length=entry[2],entry[7]
    body_length,body_version=struct.unpack_from('<II',archive,offset)
    assert body_version==2 and body_length==length-8
    body=archive[offset+8:offset+length]
    assert body.startswith(b'-- HD2-Addon: mods/hd2transmog/foundation\n')
    assert body== (ROOT/'dist/hd2_transmog.lua').read_bytes()
    assert b'local STATS_FOLLOW_LOOK = false' in body
    import re
    normalize=lambda source: re.sub(rb"build='[0-9a-f]{16}'", b"build='test'", source)
    assert normalize(alt_body)==normalize(body.replace(b'local STATS_FOLLOW_LOOK = false',
                                                       b'local STATS_FOLLOW_LOOK = true',1))
    parser=['luajit','-e','assert(loadstring(io.read("*a")))']
    assert subprocess.run(parser,input=body,capture_output=True).returncode==0
    # Prove the syntax check catches Lua 5.3-only operators.
    assert subprocess.run(parser,input=b'local x = 5 // 2',capture_output=True).returncode!=0
    subprocess.run([sys.executable,'tools/build.py'],cwd=ROOT,check=True,capture_output=True,text=True)
    assert package.read_bytes()==first


def test_release_tag_must_match_runtime_and_checksum_identifies_exact_zip():
    package=ROOT/'dist/HD2-Transmog-Foundation-0.1.2-debug.zip'
    subprocess.run([sys.executable,'tools/build.py','--release-tag','v0.1.2-debug'],cwd=ROOT,check=True,capture_output=True,text=True)
    before=package.read_bytes()
    import hashlib
    assert package.with_suffix('.zip.sha256').read_text()==f'{hashlib.sha256(before).hexdigest()}  {package.name}\n'
    rejected=subprocess.run([sys.executable,'tools/build.py','--release-tag','v99.0'],cwd=ROOT,capture_output=True,text=True)
    assert rejected.returncode!=0 and 'release tag must be' in rejected.stderr
    assert package.read_bytes()==before
