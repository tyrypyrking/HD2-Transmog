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


def resource(package,folder):
    archive=package.read(folder+'/9ba626afa44a3aa3.patch_0')
    assert struct.unpack_from('<III',archive)==(0xf0000011,1,1)
    entry=struct.unpack_from('<7Q6I',archive,104)
    assert entry[1]==0xa14e8dfa2cd117e2
    offset,length=entry[2],entry[7]
    assert struct.unpack_from('<II',archive,offset)==(length-8,2)
    return entry[0],archive[offset+8:offset+length]


def test_installable_package_and_luajit_discovery_entry():
    subprocess.run([sys.executable,'tools/build.py'],cwd=ROOT,check=True,capture_output=True,text=True)
    package=ROOT/'dist/HD2-Transmog-Foundation-0.1.3.zip'
    first=package.read_bytes()
    settings=[('stats_follow_look','IndependentStats','LookStats'),
              ('helmet_transmog','HelmetOff','HelmetOn'),
              ('passive_preview_icons','PassiveIconsOff','PassiveIconsOn')]
    with zipfile.ZipFile(package) as z:
        folders=['Addon']+[folder for _,off,on in settings for folder in (off,on)]
        expected={'manifest.json','README.txt','THIRD-PARTY-LICENSES.txt','mod-icon.png'}
        expected.update(folder+'/9ba626afa44a3aa3.patch_0'+suffix
                        for folder in folders for suffix in ['', '.stream', '.gpu_resources'])
        assert set(z.namelist())==expected
        assert b'0.1.3' in z.read('README.txt')
        manifest=json.loads(z.read('manifest.json'))
        assert z.read(manifest['IconPath'])==(ROOT/'assets/mod-icon.png').read_bytes()
        assert manifest['Guid']=='46b51e90-d243-457a-ae92-8d7e6875c0ea'
        groups=manifest['Options']
        assert [group['Name'] for group in groups]==['HD2 Transmog Foundation','Helmet transmog','Armor thumbnail passive icons']
        assert [group['Include'] for group in groups]==[['Addon'],[],[]]
        assert [[c['Include'] for c in group['SubOptions']] for group in groups]==[
            [['IndependentStats'],['LookStats']],[['HelmetOff'],['HelmetOn']],[['PassiveIconsOn'],['PassiveIconsOff']]]
        assert [c['Name'] for c in groups[0]['SubOptions']]==['Independent armor stats (default)','Disable armor stat selection']
        key,body=resource(z,'Addon')
        assert key==resource_hash('mods/hd2transmog/foundation')
        assert body.startswith(b'-- HD2-Addon: mods/hd2transmog/foundation\n')
        assert body==(ROOT/'dist/hd2_transmog.lua').read_bytes()
        parser=['luajit','-e','assert(loadstring(io.read("*a")))']
        assert subprocess.run(parser,input=body,capture_output=True).returncode==0
        assert subprocess.run(parser,input=b'local x = 5 // 2',capture_output=True).returncode!=0
        payloads={}
        keys={key}
        for name,off,on in settings:
            for enabled,folder in ((False,off),(True,on)):
                key,payload=resource(z,folder)
                assert key==resource_hash('mods/hd2transmog/options/'+name)
                assert key not in keys or folder==on
                if folder==off: keys.add(key)
                assert len(payload)>=1024
                assert payload.endswith(('return '+str(enabled).lower()+'\n').encode())
                assert not payload.startswith(b'-- HD2-Addon:')
                payloads[name,enabled]=payload.decode()
        # Execute the packaged settings through the same require path as main,
        # in all eight combinations. Missing settings retain runtime defaults.
        import itertools
        prefix=body.decode().split('-- Bundled after State, Platform, Adapter and Panel by tools/build.py.')[1].split('local UiLayout=')[0]
        for values in itertools.product((False,True),repeat=3):
            preload='\n'.join("package.preload['mods/hd2transmog/options/"+name+"']=function() "+payloads[name,value]+" end"
                              for (name,_,_),value in zip(settings,values))
            checks='\n'.join('assert('+variable+'=='+str(value).lower()+')' for variable,value in
                             zip(['STATS_FOLLOW_LOOK','HELMET_TRANSMOG','PASSIVE_PREVIEW_ICONS'],values))
            result=subprocess.run(['luajit','-'],input=preload+'\nApplication={can_get=function(_,name)return package.preload[name]~=nil end}\n'+prefix+'\n'+checks,text=True,capture_output=True)
            assert result.returncode==0,result.stderr
        defaults='assert(not STATS_FOLLOW_LOOK and not HELMET_TRANSMOG and PASSIVE_PREVIEW_ICONS);assert((missing_calls or 0)==0)'
        for preload in ("missing_calls=0;Application={can_get=function()return false end};require=function()missing_calls=missing_calls+1;error('missing native require must not run')end", '', "package.preload['mods/hd2transmog/options/helmet_transmog']=function()error('unavailable')end",
                        "package.preload['mods/hd2transmog/options/helmet_transmog']=function()return {}end"):
            result=subprocess.run(['luajit','-'],input=preload+'\n'+prefix+'\n'+defaults,text=True,capture_output=True)
            assert result.returncode==0,result.stderr
    subprocess.run([sys.executable,'tools/build.py'],cwd=ROOT,check=True,capture_output=True,text=True)
    assert package.read_bytes()==first


def test_release_tag_must_match_runtime_and_checksum_identifies_exact_zip():
    package=ROOT/'dist/HD2-Transmog-Foundation-0.1.3.zip'
    subprocess.run([sys.executable,'tools/build.py','--release-tag','v0.1.3'],cwd=ROOT,check=True,capture_output=True,text=True)
    before=package.read_bytes()
    import hashlib
    assert package.with_suffix('.zip.sha256').read_text()==f'{hashlib.sha256(before).hexdigest()}  {package.name}\n'
    rejected=subprocess.run([sys.executable,'tools/build.py','--release-tag','v99.0'],cwd=ROOT,capture_output=True,text=True)
    assert rejected.returncode!=0 and 'release tag must be' in rejected.stderr
    assert package.read_bytes()==before
