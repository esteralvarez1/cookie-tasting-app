"""Tests for the conversational dialog flow.

All tests that require controlled analysis output monkeypatch `service.analyzer`
with a FakeAnalyzer.  The real services.dialogue logic is always exercised;
only the analysis layer is replaced.

Message used in 'all complete' tests is deliberately descriptive so that the
deterministic vague pre-filter (_looks_clearly_vague) does not override the
fake analysis result.
"""
from __future__ import annotations

import pytest

from app.api.routes.evaluations import service
from app.models.enums import EvaluationState, EvaluationStatus
from app.services.modality_questions import COMPARISON_REFORMULATION, OPEN_REPROMPT, SAMPLE_COMPLETED_MESSAGE
from tests.fakes import FakeAnalyzer

# A rich enough message to bypass the deterministic vague pre-filter
_RICH_MESSAGE = (
    'El color es dorado y la forma redonda, la textura es muy crujiente, '
    'sabe dulce con un toque de vainilla y huele muy bien, me gusta mucho'
)


def _send_dialog(client, eval_id: str, headers: dict, message: str = _RICH_MESSAGE) -> dict:
    resp = client.post(
        f'/api/v1/evaluations/{eval_id}/dialog',
        json={'user_message': message},
        headers=headers,
    )
    assert resp.status_code == 200
    return resp.json()['data']


class TestBasicDialogInfrastructure:
    def test_user_turn_is_saved_and_bot_responds(self, client, evaluation, session_headers):
        """Sending any message should persist a user turn and produce a bot turn."""
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers)

        assert data['bot_message']
        turns = data['turns']
        speakers = [t['speaker'] for t in turns]
        assert 'USER' in speakers
        assert 'BOT' in speakers

    def test_response_contains_analysis_block(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers)
        assert data['analysis'] is not None
        analysis = data['analysis']
        assert 'is_vague' in analysis
        assert 'has_comparison' in analysis
        assert 'next_action' in analysis
        assert 'modalities' in analysis
        for m in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR'):
            assert m in analysis['modalities']

    def test_requires_valid_session_token(self, client, evaluation):
        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Hola'},
            headers={'X-Session-Token': 'bad-token'},
        )
        assert resp.status_code == 401

    def test_rejects_empty_message(self, client, evaluation, session_headers):
        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': '   '},
            headers=session_headers,
        )
        assert resp.status_code == 422


class TestVagueResponseFlow:
    def test_vague_initial_response_triggers_reprompt(self, client, evaluation, session_headers, monkeypatch):
        """A clearly vague first answer must produce an open reprompt."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.VAGUE))
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers, message='Está bien')

        assert data['analysis']['is_vague'] is True
        assert data['current_state'] == EvaluationState.OPEN_REPROMPT.value
        assert data['analysis']['next_action'] == 'ASK_OPEN_REPROMPT'
        assert data['bot_message'] == OPEN_REPROMPT
        # Evaluation must still be IN_PROGRESS — a vague answer must not close the sample
        assert data['status'] == EvaluationStatus.IN_PROGRESS.value

    def test_vague_response_does_not_advance_to_modality_question(
        self, client, evaluation, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.VAGUE))
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers, message='Ok')
        assert 'ASK_MODALITY' not in (data['analysis']['next_action'] or '')


class TestComparisonFlow:
    def test_comparison_triggers_reformulation_request(
        self, client, evaluation, session_headers, monkeypatch
    ):
        """Comparing with another sample must produce the reformulation message."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(
            client, eval_id, session_headers,
            message='Esta galleta tiene mejor aspecto que la anterior',
        )

        assert data['analysis']['has_comparison'] is True
        assert data['current_state'] == EvaluationState.COMPARISON_REFORMULATION.value
        assert data['analysis']['next_action'] == 'ASK_REFORMULATION_NO_COMPARISON'
        assert data['bot_message'] == COMPARISON_REFORMULATION
        assert data['status'] == EvaluationStatus.IN_PROGRESS.value

    def test_comparison_does_not_mark_any_modality_complete(
        self, client, evaluation, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.COMPARISON))
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers, message='Es mejor que la otra')
        for modality_data in data['analysis']['modalities'].values():
            assert modality_data['is_complete'] is False


class TestModalityQuestionFlow:
    def test_partial_analysis_leads_to_modality_question(
        self, client, evaluation, session_headers, monkeypatch
    ):
        """A non-vague answer with no modality complete should trigger the ASPECTO question.

        With the coverage-based vagueness rule, an INITIAL answer that completes <= 2
        modalities is vague and triggers one open reprompt first; the next turn
        (intermediate) then proceeds to the first modality question.
        """
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        eval_id = evaluation['evaluation_id']
        # Turn 1 (INITIAL): 0 complete → vague → open reprompt.
        warmup = _send_dialog(client, eval_id, session_headers, message=_RICH_MESSAGE)
        assert warmup['bot_message'] == OPEN_REPROMPT
        # Turn 2 (intermediate): not vague → first modality question.
        data = _send_dialog(client, eval_id, session_headers, message=_RICH_MESSAGE)

        assert data['current_state'] == EvaluationState.MODALITY_QUESTION.value
        assert data['analysis']['next_action'] == 'ASK_MODALITY_ASPECTO'
        assert data['current_modality'] == 'ASPECTO'

    def test_aspecto_partial_leads_to_aspecto_valuation_question(
        self, client, evaluation, session_headers, monkeypatch
    ):
        """ASPECTO with mention+descriptor but no valuation should ask for valuation."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ASPECTO_PARTIAL))
        eval_id = evaluation['evaluation_id']
        # Turn 1 (INITIAL): only ASPECTO partially covered → vague → open reprompt.
        warmup = _send_dialog(client, eval_id, session_headers)
        assert warmup['bot_message'] == OPEN_REPROMPT
        # Turn 2 (intermediate): proceeds to the ASPECTO valuation question.
        data = _send_dialog(client, eval_id, session_headers)

        assert data['current_modality'] == 'ASPECTO'
        assert data['current_state'] == EvaluationState.MODALITY_QUESTION.value
        # Bot message should ask for valuation (¿te gusta?), not full re-describe
        assert 'te parece' in data['bot_message'].lower() or 'te gusta' in data['bot_message'].lower()


class TestSampleCloseFlow:
    def test_all_complete_analysis_closes_sample(
        self, client, evaluation, session_headers, monkeypatch
    ):
        """When all modalities are complete the evaluation should be finalized."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        eval_id = evaluation['evaluation_id']
        data = _send_dialog(client, eval_id, session_headers, message=_RICH_MESSAGE)

        assert data['status'] == EvaluationStatus.COMPLETED.value
        assert data['current_state'] == EvaluationState.SAMPLE_COMPLETED.value
        assert data['bot_message'] == SAMPLE_COMPLETED_MESSAGE
        # With 2 samples total and 1 completed, next step must be NEXT_SAMPLE
        assert data['next_step'] == 'NEXT_SAMPLE'

    def test_completed_evaluation_cannot_receive_more_dialog(
        self, client, evaluation, session_headers, monkeypatch
    ):
        """Sending dialog to a completed evaluation must return 409."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        eval_id = evaluation['evaluation_id']
        _send_dialog(client, eval_id, session_headers, message=_RICH_MESSAGE)

        # Restore normal analyzer; second call must fail regardless
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.NORMAL))
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Otro mensaje'},
            headers=session_headers,
        )
        assert resp.status_code == 409


class TestNextSampleAndSurveyFlow:
    def test_next_step_is_sample_comment_after_all_samples_done(
        self, client, participant_session, session_headers, tasting_config, monkeypatch
    ):
        """After all evaluations complete, next-step must return SAMPLE_COMMENT while the
        last per-sample comment is still pending."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']
        last_eval_id = None

        for sample_code in ('MUESTRA_A', 'MUESTRA_B'):
            ev_resp = client.post(
                '/api/v1/evaluations',
                json={'session_id': session_id, 'sample_code': sample_code},
                headers=session_headers,
            )
            assert ev_resp.status_code == 201
            eval_id = ev_resp.json()['data']['evaluation_id']
            _send_dialog(client, eval_id, session_headers, message=_RICH_MESSAGE)
            # Save the comment for every sample except the last to simulate the real flow
            # (comment is saved before moving to the next sample; only the last one is pending).
            if sample_code == 'MUESTRA_A':
                client.post(
                    f'/api/v1/evaluations/{eval_id}/final-comment',
                    json={'comment': 'me gustó'},
                    headers=session_headers,
                )
            else:
                last_eval_id = eval_id

        step_resp = client.get(f'/api/v1/sessions/{session_id}/next-step', headers=session_headers)
        assert step_resp.status_code == 200
        step_data = step_resp.json()['data']
        assert step_data['next_step'] == 'SAMPLE_COMMENT'
        assert step_data['pending_sample_codes'] == []
        assert set(step_data['completed_sample_codes']) == {'MUESTRA_A', 'MUESTRA_B'}
        assert step_data['pending_comment_evaluation_id'] == last_eval_id

    def test_session_completed_after_all_sample_comments_saved(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Session transitions to COMPLETED only after all per-sample comments are saved."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']

        eval_ids = []
        for sample_code in ('MUESTRA_A', 'MUESTRA_B'):
            ev = client.post(
                '/api/v1/evaluations',
                json={'session_id': session_id, 'sample_code': sample_code},
                headers=session_headers,
            ).json()['data']
            _send_dialog(client, ev['evaluation_id'], session_headers, message=_RICH_MESSAGE)
            eval_ids.append(ev['evaluation_id'])

        # After both evaluations complete, session must still be IN_PROGRESS (last comment pending).
        step_data = client.get(
            f'/api/v1/sessions/{session_id}/next-step', headers=session_headers
        ).json()['data']
        assert step_data['next_step'] == 'SAMPLE_COMMENT'

        # Save the first comment; session must still be IN_PROGRESS (second comment pending).
        client.post(
            f'/api/v1/evaluations/{eval_ids[0]}/final-comment',
            json={'comment': ''},
            headers=session_headers,
        )
        step_data = client.get(
            f'/api/v1/sessions/{session_id}/next-step', headers=session_headers
        ).json()['data']
        assert step_data['next_step'] == 'SAMPLE_COMMENT'

        # Save the last comment; session must transition to COMPLETED.
        client.post(
            f'/api/v1/evaluations/{eval_ids[1]}/final-comment',
            json={'comment': ''},
            headers=session_headers,
        )
        step_data = client.get(
            f'/api/v1/sessions/{session_id}/next-step', headers=session_headers
        ).json()['data']
        assert step_data['next_step'] == 'SESSION_COMPLETED'

    def test_survey_submission_marks_session_completed(
        self, client, participant_session, session_headers, monkeypatch
    ):
        """Submitting the final survey must set session status to COMPLETED."""
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']

        for sample_code in ('MUESTRA_A', 'MUESTRA_B'):
            ev = client.post(
                '/api/v1/evaluations',
                json={'session_id': session_id, 'sample_code': sample_code},
                headers=session_headers,
            ).json()['data']
            _send_dialog(client, ev['evaluation_id'], session_headers, message=_RICH_MESSAGE)

        survey_resp = client.post(
            f'/api/v1/sessions/{session_id}/survey',
            json={'payload': {'q1': 'respuesta 1'}},
            headers=session_headers,
        )
        assert survey_resp.status_code == 201
        survey_data = survey_resp.json()['data']
        assert survey_data['survey_saved'] is True
        assert survey_data['status'] == 'COMPLETED'

    def test_next_step_is_session_completed_after_survey(
        self, client, participant_session, session_headers, monkeypatch
    ):
        monkeypatch.setattr(service, 'analyzer', FakeAnalyzer(FakeAnalyzer.ALL_COMPLETE))
        session_id = participant_session['session_id']

        for sample_code in ('MUESTRA_A', 'MUESTRA_B'):
            ev = client.post(
                '/api/v1/evaluations',
                json={'session_id': session_id, 'sample_code': sample_code},
                headers=session_headers,
            ).json()['data']
            _send_dialog(client, ev['evaluation_id'], session_headers, message=_RICH_MESSAGE)

        client.post(
            f'/api/v1/sessions/{session_id}/survey',
            json={'payload': {'q1': 'ok'}},
            headers=session_headers,
        )

        step_resp = client.get(f'/api/v1/sessions/{session_id}/next-step', headers=session_headers)
        assert step_resp.json()['data']['next_step'] == 'SESSION_COMPLETED'

    def test_closed_config_blocks_dialog(
        self, client, admin_headers, tasting_config, participant_session, session_headers, evaluation
    ):
        """After closing the tasting config, the participant must not send more dialog."""
        config_id = tasting_config['tasting_session_id']
        client.post(f'/api/v1/tasting-sessions/{config_id}/close', headers=admin_headers)

        eval_id = evaluation['evaluation_id']
        resp = client.post(
            f'/api/v1/evaluations/{eval_id}/dialog',
            json={'user_message': 'Hola'},
            headers=session_headers,
        )
        assert resp.status_code == 403
