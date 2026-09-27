"""Creator-driver parser and simulated UI flow; no desktop/native input."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

TOOLS=Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0,str(TOOLS))
SPEC=importlib.util.spec_from_file_location('creator_flow_driver',TOOLS/'test_creator_flow.py')
creator=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=creator
SPEC.loader.exec_module(creator)
sys.path.pop(0)

LOOK='armor:12345678'
STATS='base:50/550/125'
PASSIVE='passive:wanted'


def region(action,value='',x=100,y=100,w=100,h=100,target='',delta=''):
    return '\t'.join(map(str,('region',action,value,x,y,w,h,target,delta)))


def status_text(*regions,step=0,label='',can_create=False,selection=None,stats_tuple=''):
    fields=['HD2TM_UI_STATUS 1','viewport=1920,1080',f'step={step}',f'open={str(step!=0).lower()}',
            f'can_create={str(can_create).lower()}',f'label={label}',f'stats_tuple_id={stats_tuple}',
            'frames=25','panel.rebuild_count=2']
    fields += [f'selection.{key}={value}' for key,value in (selection or {}).items()]
    return '\n'.join(fields+list(regions))+'\n'


def test_parse_actual_tsv_shapes_and_bottom_left_to_client_conversion():
    state=creator.parse_ui_status(status_text(region('select_look',LOOK,200,600,180,180),step=1,label='Новый вариант 2'))
    assert state.open and state.step==1 and state.label=='Новый вариант 2'
    control=creator.choose_region(state,'select_look',LOOK)
    assert control.point(state.viewport)==pytest.approx((290/1920,1-690/1080))
    assert creator.choose_region(state,'create',optional=True) is None


@pytest.mark.parametrize('bad',[
    lambda raw:raw.replace('viewport=1920,1080','viewport=nan,1080'),
    lambda raw:raw.replace('open=false','open=true'),
    lambda raw:raw.replace('can_create=false','can_create=true'),
    lambda raw:raw.replace('stats_tuple_id=\n',''),
    lambda raw:raw+'step=1\n',
    lambda raw:raw+region('open',x=-1)+'\n',
    lambda raw:raw+region('open',y=1050,h=100)+'\n',
    lambda raw:raw+region('open',w=float('inf'))+'\n',
    lambda raw:raw+region('panel_page',target='options',delta=2)+'\n',
    lambda raw:raw+'region\tcreate\n',
])
def test_malformed_stale_schema_or_outside_viewport_status_is_rejected(bad):
    with pytest.raises(creator.CreatorError):
        creator.parse_ui_status(bad(status_text()))


def test_action_selection_is_exact_and_ambiguous_controls_are_rejected():
    state=creator.parse_ui_status(status_text(region('select_passive','passive:a'),region('select_passive',PASSIVE,x=300),
        region('panel_page',x=500,target='options',delta=1),region('panel_page',x=700,target='review',delta=1),step=3))
    assert creator.choose_region(state,'select_passive',PASSIVE).x==300
    assert creator.choose_region(state,'panel_page',page_target='options',delta=1).x==500
    with pytest.raises(creator.CreatorError,match='Ambiguous'):
        creator.choose_region(state,'panel_page',delta=1)
    with pytest.raises(creator.CreatorError,match='unavailable'):
        creator.choose_region(state,'select_passive','passive:want')
    duplicated=creator.parse_ui_status(status_text(region('open'),region('open',x=300)))
    with pytest.raises(creator.CreatorError,match='Ambiguous'):
        creator.choose_region(duplicated,'open')


class SimulatedUi:
    def __init__(self,tmp_path,monkeypatch,execute=True):
        self.step=0
        self.page=0
        self.can_create=False
        self.label='Custom Variant 2'
        self.selection={}
        self.stats_tuple=''
        self.labels={'Existing'}
        self.visible_look=True
        self.commands=[]
        self.actions=[]
        self.counter=0
        self.clock=0
        self.status_override=None
        self.stop_publish=False
        self.wrong_request=False
        self.focus_ok=True
        self.frame_state='unknown'
        self.frame_size=(1920,1080)
        self.saved_card_visible=True
        self.fail_create=False
        self.change_before_create=False
        self.create_statuses=0
        self.state_dir=tmp_path/'state';self.state_dir.mkdir()
        (self.state_dir/'debug.enabled').write_text('HD2TM_DEBUG 1\n')
        (self.state_dir/'debug.session').write_text('HD2TM_DEBUG_SESSION 1\nsession-test\n')
        journal=creator.game.Journal(tmp_path/'artifacts')
        self.session=SimpleNamespace(args=SimpleNamespace(execute=execute),journal=journal,
                                     focus=self.focus,assert_focus=self.guard,observe=self.observe,action=self.action)
        monkeypatch.setattr(creator.game,'debug_command',self.debug)
        monkeypatch.setattr(creator.time,'monotonic',lambda:self.clock)
        monkeypatch.setattr(creator.time,'sleep',lambda seconds:setattr(self,'clock',self.clock+seconds))

    def focus(self):
        self.guard()

    def guard(self):
        if not self.focus_ok:
            raise creator.CreatorError('game focus lost')

    def observe(self):
        self.guard()
        return {'state':self.frame_state,'width':self.frame_size[0],'height':self.frame_size[1],
                'path':str(self.session.journal.path/'fake-frame.png')}

    def raw(self):
        if self.status_override:
            return self.status_override
        if self.step==0:
            rows=[region('open',x=100,y=700),region('select_variant','Existing',x=300,y=700)]
            if self.label in self.labels and self.saved_card_visible:
                rows.append(region('select_variant',self.label,x=500,y=700))
        elif self.step==1:
            rows=[region('select_look',LOOK,x=100,y=500)] if self.visible_look else []
        else:
            action='select_stats' if self.step==2 else 'select_passive'
            values=['base:100/500/100',STATS] if self.step==2 else ['passive:other',PASSIVE]
            rows=[region(action,values[self.page],x=300,y=500)]
            if self.page:
                rows.append(region('panel_page',x=1300,y=100,w=40,h=32,target='options',delta=-1))
            else:
                rows.append(region('panel_page',x=1450,y=100,w=40,h=32,target='options',delta=1))
            if self.can_create:
                rows.append(region('create',x=1500,y=300,w=180,h=48))
        return status_text(*rows,step=self.step,label=self.label if self.step else '',can_create=self.can_create,
                           selection=self.selection,stats_tuple=self.stats_tuple if self.step else '')

    def publish(self,name,text):
        temporary=self.state_dir/(name+'.tmp')
        temporary.write_text(text)
        temporary.replace(self.state_dir/name)

    def debug(self,command,**kwargs):
        assert kwargs['execute'] and command in ('ui_status','variant_status')
        kwargs['guard']()
        self.counter+=1
        self.commands.append(command)
        request_id=f'request-{self.counter}'
        actual_id='different-request' if self.wrong_request else request_id
        self.publish('debug.request',f'HD2TM_DEBUG_REQUEST 1\nsession-test\n{actual_id}\n{command}\n')
        if command=='ui_status':
            if self.can_create:
                self.create_statuses+=1
                if self.change_before_create and self.create_statuses==2:
                    if self.change_before_create=='stats':self.stats_tuple='base:1/2/3'
                    elif self.change_before_create=='label':self.label='Changed label'
                    else:self.selection['passive_variant_id']='passive:changed'
            filename,raw='debug-ui-status.txt',self.raw()
        else:
            filename='debug-variant-status.txt'
            raw='HD2TM_VARIANT_STATUS 1\n'+''.join(f'saved {label}\n' for label in sorted(self.labels))
        if not self.stop_publish:
            self.publish(filename,raw)
        return {'session_token':'session-test','request_id':request_id,'status':'ok'}

    def action(self,action,expected,observation):
        self.guard()
        assert action['kind']=='click' and observation['state'] in expected
        state=creator.parse_ui_status(self.raw())
        x,y=action['x']*1920,(1-action['y'])*1080
        hits=[r for r in state.regions if r.x<=x<r.x+r.width and r.y<=y<r.y+r.height]
        assert len(hits)==1
        control=hits[0];self.actions.append(control)
        if control.action=='open':self.step=1
        elif control.action=='select_look':
            self.selection['appearance_id']=control.value;self.step=2;self.page=0
        elif control.action=='panel_page':self.page+=control.delta
        elif control.action=='select_stats':
            self.stats_tuple=control.value;self.selection['stats_id']='native-stats:abcdef01';self.step=3;self.page=0
        elif control.action=='select_passive':
            self.selection['passive_variant_id']=control.value;self.can_create=True
        elif control.action=='create' and not self.fail_create:
            self.labels.add(self.label);self.step=0;self.can_create=False;self.selection={}
        return {'after':self.observe()}


def test_complete_mouse_flow_pages_exact_options_creates_once_and_logs_evidence(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch)
    result=creator.CreatorDriver(sim.session,sim.state_dir,timeout=2).run(LOOK,STATS,PASSIVE)
    assert result['saved'] and result['label']==sim.label and result['saved_card_visible']
    assert result['equip_action_sent'] is False and result['create_clicks']==1
    assert [r.action for r in sim.actions]==['open','select_look','panel_page','select_stats','panel_page','select_passive','create']
    assert all(r.page_target=='options' for r in sim.actions if r.action=='panel_page')
    assert (sim.session.journal.path/'creator-result.json').is_file()
    assert list(sim.session.journal.path.glob('debug-ui-status-*.txt'))
    assert set(sim.commands)=={'ui_status','variant_status'}


def test_dry_run_does_not_focus_inspect_status_or_send_input(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch,execute=False)
    sim.focus_ok=False
    result=creator.CreatorDriver(sim.session,tmp_path/'absent').run(LOOK,STATS,PASSIVE)
    assert result['dry_run'] and not result['saved'] and not sim.commands and not sim.actions


def test_invisible_look_is_reported_without_paging_or_teleporting(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.visible_look=False
    with pytest.raises(creator.CreatorError,match='visible control is unavailable: select_look'):
        creator.CreatorDriver(sim.session,sim.state_dir).run(LOOK,STATS,PASSIVE)
    assert [r.action for r in sim.actions]==['open'] and sim.labels=={'Existing'}


def test_page_budget_stops_before_extra_page_or_create_click(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch)
    with pytest.raises(creator.CreatorError,match='page search exhausted'):
        creator.CreatorDriver(sim.session,sim.state_dir,max_pages=0).run(LOOK,STATS,PASSIVE)
    assert [r.action for r in sim.actions]==['open','select_look']


@pytest.mark.parametrize('kind',['stale','wrong_request','session_change'])
def test_status_must_be_fresh_and_bound_to_current_request_and_session(tmp_path,monkeypatch,kind):
    sim=SimulatedUi(tmp_path,monkeypatch)
    sim.publish('debug-ui-status.txt',sim.raw())
    driver=creator.CreatorDriver(sim.session,sim.state_dir)
    driver.state_dir=sim.state_dir;driver.token='session-test'
    if kind=='stale':sim.stop_publish=True
    elif kind=='wrong_request':sim.wrong_request=True
    else:(sim.state_dir/'debug.session').write_text('HD2TM_DEBUG_SESSION 1\nnew-session\n')
    with pytest.raises(creator.CreatorError):driver.status()
    assert not sim.actions


@pytest.mark.parametrize('kind',['viewport','known_wrong_screen','focus'])
def test_click_requires_matching_viewport_game_view_and_focus(tmp_path,monkeypatch,kind):
    sim=SimulatedUi(tmp_path,monkeypatch)
    if kind=='viewport':sim.frame_size=(1280,720)
    elif kind=='known_wrong_screen':sim.frame_state='ship'
    else:sim.focus_ok=False
    with pytest.raises(creator.CreatorError):
        creator.CreatorDriver(sim.session,sim.state_dir).run(LOOK,STATS,PASSIVE)
    assert not sim.actions


@pytest.mark.parametrize('change',[True,'stats','label'])
def test_changed_precreate_selection_is_rejected_before_save_click(tmp_path,monkeypatch,change):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.change_before_create=change
    with pytest.raises(creator.CreatorError,match='changed before Create'):
        creator.CreatorDriver(sim.session,sim.state_dir,timeout=2).run(LOOK,STATS,PASSIVE)
    assert not any(r.action=='create' for r in sim.actions) and sim.labels=={'Existing'}


def test_uncertain_create_never_replays_the_click(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.fail_create=True
    driver=creator.CreatorDriver(sim.session,sim.state_dir,timeout=1)
    with pytest.raises(creator.CreatorError,match='closed saved wizard'):
        driver.run(LOOK,STATS,PASSIVE)
    assert sum(r.action=='create' for r in sim.actions)==1 and driver.created_click


def test_persisted_but_invisible_saved_card_is_reported_without_a_second_create(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.saved_card_visible=False
    driver=creator.CreatorDriver(sim.session,sim.state_dir,timeout=1)
    with pytest.raises(creator.CreatorError,match='new saved card'):
        driver.run(LOOK,STATS,PASSIVE)
    assert driver.persistence_confirmed and sim.label in sim.labels
    assert sum(r.action=='create' for r in sim.actions)==1


def test_exact_stats_tuple_is_required_even_if_donor_id_exists(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch)
    action=sim.session.action
    def wrong_tuple(*args):
        result=action(*args)
        if sim.step==3:sim.stats_tuple='base:999/999/999'
        return result
    sim.session.action=wrong_tuple
    with pytest.raises(creator.CreatorError,match='selected base tuple'):
        creator.CreatorDriver(sim.session,sim.state_dir,timeout=1).run(LOOK,STATS,PASSIVE)
    assert not any(r.action=='create' for r in sim.actions)


def test_retained_option_page_can_move_back_without_using_review_pager(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.step=2;sim.page=1
    driver=creator.CreatorDriver(sim.session,sim.state_dir,timeout=2)
    driver.state_dir=sim.state_dir;driver.token='session-test'
    driver.choose_paged('select_stats','base:100/500/100',2)
    assert [(r.action,r.delta) for r in sim.actions]==[('panel_page',-1),('select_stats',None)]


def test_unresponsive_page_is_not_clicked_repeatedly(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch);sim.step=2
    action=sim.session.action
    def unchanged_page(*args):
        result=action(*args)
        sim.page=0
        return result
    sim.session.action=unchanged_page
    driver=creator.CreatorDriver(sim.session,sim.state_dir,timeout=1)
    driver.state_dir=sim.state_dir;driver.token='session-test'
    with pytest.raises(creator.CreatorError,match='changed option page'):
        driver.choose_paged('select_stats',STATS,2)
    assert len(sim.actions)==1 and sim.actions[0].action=='panel_page'


def test_disabled_create_is_not_clicked_even_if_a_stale_region_remains(tmp_path,monkeypatch):
    sim=SimulatedUi(tmp_path,monkeypatch)
    sim.status_override=status_text(region('create'),step=3,label='Pending',can_create=False,stats_tuple=STATS)
    driver=creator.CreatorDriver(sim.session,sim.state_dir)
    driver.state_dir=sim.state_dir;driver.token='session-test'
    state=creator.parse_ui_status(sim.status_override)
    with pytest.raises(creator.CreatorError,match='Create is disabled'):
        driver.click('create',step=3,create_state=state)
    assert not sim.actions and not driver.created_click
