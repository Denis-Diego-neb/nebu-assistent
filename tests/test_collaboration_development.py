import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from services.collaboration.api import CollaborationAPI
from services.collaboration.development_transport import Events, command
from services.collaboration.providers import Reply


class Developer:
    def __init__(self, fail=None, gate=None):
        self.fail, self.gate = fail, gate
        self.calls = []

    def develop(self, actor, prompt, cwd, session_id=None, on_event=None, cancel=None):
        self.calls.append((actor, session_id, cwd))
        session_id = session_id or str(uuid4())
        on_event('session', session_id)
        on_event('tool_activity', 'python -m unittest')
        if self.gate:
            self.gate.wait(4)
        if cancel.is_set():
            raise RuntimeError('Interrompido')
        if actor == self.fail:
            raise RuntimeError('cota indisponível')
        (cwd / (actor + '.txt')).write_text('feito', encoding='utf-8')
        return Reply({'text':'Resultado com testes'}, session_id, 'test-model', 200)


class DevelopmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '.git').mkdir()

    def wait(self, api):
        api.development.thread.join(8)
        self.assertFalse(api.development.thread.is_alive())
        self.assertIsNone(api.store.snapshot().get('active_chat'))
        return api.store.snapshot()

    def test_edit_review_events_and_persisted_sessions_after_reconstruction(self):
        provider = Developer()
        api = CollaborationAPI(self.root, provider)
        status, result = api.handle('POST','/api/collaboration/develop',{'text':'Implemente'})
        self.assertEqual(status, 202)
        state = self.wait(api)
        self.assertEqual([c[0] for c in provider.calls], ['codex','opus'])
        self.assertTrue((self.root/'codex.txt').exists())
        self.assertTrue((self.root/'opus.txt').exists())
        self.assertEqual(len([m for m in state['messages'] if m['kind']=='tool_activity']), 2)
        sessions = state['development_sessions'][result['idea_id']]
        api = CollaborationAPI(self.root, provider)
        api.handle('POST','/api/collaboration/develop',{'text':'Continue','idea_id':result['idea_id']})
        self.wait(api)
        self.assertEqual([c[1] for c in provider.calls[2:]], [sessions['codex'],sessions['opus']])

    def test_busy_rejects_new_idea_and_legacy_execution(self):
        gate = threading.Event()
        api = CollaborationAPI(self.root, Developer(gate=gate))
        _, result = api.handle('POST','/api/collaboration/develop',{'text':'primeira'})
        try:
            self.assertEqual(api.handle('POST','/api/collaboration/develop',{'text':'segunda'})[0],409)
            self.assertEqual(api.handle('POST','/api/collaboration/run',{'idea_id':result['idea_id']})[0],409)
            self.assertEqual(len(api.store.snapshot()['ideas']),1)
        finally:
            gate.set()
            self.wait(api)

    def test_missing_git_rejected_without_creating_idea(self):
        (self.root/'.git').rmdir()
        api = CollaborationAPI(self.root, Developer())
        self.assertEqual(api.handle('POST','/api/collaboration/develop',{'text':'pedido'})[0],400)
        self.assertEqual(api.store.snapshot()['ideas'],[])

    def test_other_agent_can_proceed_after_first_fails(self):
        api = CollaborationAPI(self.root, Developer(fail='codex'))
        api.handle('POST','/api/collaboration/develop',{'text':'pedido'})
        state = self.wait(api)
        self.assertTrue((self.root/'opus.txt').exists())
        self.assertTrue(any(m['kind']=='chat_error' for m in state['messages']))

    def test_cancel_prevents_next_agent_and_releases_round(self):
        gate=threading.Event()
        provider=Developer(gate=gate)
        api=CollaborationAPI(self.root,provider)
        api.handle('POST','/api/collaboration/develop',{'text':'pedido'})
        self.assertEqual(api.handle('POST','/api/collaboration/stop')[0],202)
        gate.set()
        self.wait(api)
        self.assertLessEqual(len(provider.calls),1)
        self.assertFalse((self.root/'opus.txt').exists())

    def test_completed_idea_accepts_followup_and_pause_blocks_new_work(self):
        api=CollaborationAPI(self.root,Developer())
        idea=api.store.create_idea('antigo')['id']
        run=api.store.start_run(idea)
        api.store.end_run(run,'completed')
        self.assertEqual(api.handle('POST','/api/collaboration/develop',{'text':'continue','idea_id':idea})[0],202)
        self.wait(api)
        api.store.pause(True)
        self.assertEqual(api.handle('POST','/api/collaboration/develop',{'text':'mais'})[0],409)


class TransportTests(unittest.TestCase):
    def test_persistent_cli_commands_preserve_workspace_policy_on_resume(self):
        with patch('services.collaboration.development_transport.executable',return_value='agent.exe'):
            for actor in ('codex','opus'):
                args,_=command(actor,str(uuid4()))
                self.assertNotIn('--ephemeral',args)
                self.assertNotIn('--no-session-persistence',args)
                self.assertNotIn('--dangerously-skip-permissions',args)
                self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
                if actor=='codex':
                    self.assertIn('sandbox_mode="workspace-write"',args)
                else:
                    self.assertIn('Read,Edit,Write,Glob,Grep,Bash,PowerShell',args)

    def test_stream_filters_reasoning_and_reports_real_command_result(self):
        log=[]
        events=Events('codex','test',lambda kind,text:log.append((kind,text)))
        events.consume({'type':'thread.started','thread_id':str(uuid4())})
        events.consume({'type':'item.completed','item':{'type':'reasoning','text':'private'}})
        events.consume({'type':'item.completed','item':{'type':'command_execution','command':'pytest','exit_code':0,'aggregated_output':'2 passed'}})
        events.consume({'type':'item.completed','item':{'type':'agent_message','text':'Done'}})
        events.consume({'type':'turn.completed','usage':{'input_tokens':12,'output_tokens':4}})
        self.assertNotIn('private',json.dumps(log))
        self.assertIn('2 passed',json.dumps(log))
        self.assertEqual(events.reply().tokens,16)


class WorkspaceTests(unittest.TestCase):
    def test_project_selection_keeps_separate_stores_and_live_instance(self):
        import remote_server
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary)/'one', Path(temporary)/'two'
            first.mkdir(); second.mkdir()
            with patch.object(remote_server, '_COLABORACAO', {'api':None,'tentado_em':0.0}), \
                 patch.object(remote_server, '_COLABORACAO_PROJETOS', {}), \
                 patch.object(remote_server.STATE, 'selected_project', str(first)), \
                 patch.object(remote_server, 'liberar_rodadas_orfas') as recover:
                one = remote_server.colaboracao()
                self.assertEqual(one.store.root, first)
                one.store.create_idea('Somente no primeiro')
                remote_server.STATE.selected_project = str(second)
                two = remote_server.colaboracao()
                self.assertEqual(two.store.root, second)
                self.assertEqual(two.store.snapshot()['ideas'], [])
                remote_server.STATE.selected_project = str(first)
                self.assertIs(remote_server.colaboracao(), one)
                self.assertEqual(recover.call_count, 2)


if __name__=='__main__':
    unittest.main()
