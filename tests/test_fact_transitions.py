"""Lifecycle chooses actual recorded source facts instead of enrollment predictions."""
import copy
from test_workflow import Fixture, w


class FactTransitionTests(Fixture):
    def enroll(self,arguments):
        arguments["integration_required"]=False
        return super().enroll(arguments)

    def test_optional_integration_actual_source_closes_after_cleanup(self):
        self.integrated()
        self.op('cleanup', dry_run=False)
        self.assertFalse(self.feature.exists())
        fields={'outcome':'completed','notes':'Accepted actual source','evidence':['Integration receipt']}
        self.op('task-complete',**fields)
        version=self.state['version'];closure=copy.deepcopy(self.state['task_lifecycle']['closure'])
        self.assertTrue(self.op('task-complete',**fields)['already_closed'])
        self.assertEqual(self.state['version'],version);self.assertEqual(self.state['task_lifecycle']['closure'],closure)
        self.error('scope_closed',lambda:self.op('task-complete',**{**fields,'outcome':'abandoned'}))
        self.op('task-reopen',reason='Exercise independently copied source proofs')
        # Enrollment predictions are not evidence of what actually happened.
        state = copy.deepcopy(self.state); state['integration_required'] = False
        w.close_scope({'actor':'owner','outcome':'completed','notes':'Accepted actual integration','evidence':['Actual source checks']},state)
        self.assertEqual(state['task_lifecycle']['closure']['outcome'], 'completed')
        bad=copy.deepcopy(self.state); bad['integration_required']=False; bad['integration']['verification']['passed']=False
        self.error('integration_verification_required', lambda:w.close_scope({'actor':'owner','outcome':'completed','notes':'Rejected','evidence':['Source']},bad))

    def test_true_non_success_does_not_require_execution_approval(self):
        result=self.op('task-complete', outcome='stopped', notes='User ended exploration.', evidence=['Actual stop request'])
        self.assertEqual(result['state']['task_lifecycle']['closure']['outcome'],'stopped')
