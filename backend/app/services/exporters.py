from __future__ import annotations

import csv
import io
from typing import Iterable

from openpyxl import Workbook

from app.models.entities import EvaluationAnalysis, ModalityAnalysis, SampleEvaluation
from app.models.enums import AnalysisScope, ModalityType, SpeakerType

CANONICAL_STRUCTURED_HEADER = [
    'Panelist_Code',
    'Sample_Name',
    'Serving_Order',
    'TEXTO',
    'COMPARA',
    'VAGO',
    'ASPECTO:MENCION',
    'ASPECTO:DESCRIPTOR',
    'ASPECTO:VALORACION',
    'OLOR:MENCION',
    'OLOR:DESCRIPTOR',
    'OLOR:VALORACION',
    'TEXTURA:MENCION',
    'TEXTURA:DESCRIPTOR',
    'TEXTURA:VALORACION',
    'SABOR:MENCION',
    'SABOR:DESCRIPTOR',
    'SABOR:VALORACION',
]


def export_conversations_csv(evaluations: Iterable[SampleEvaluation]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['participant_code', 'session_id', 'evaluation_id', 'sample_code', 'presentation_order', 'turn_index', 'speaker', 'message_type', 'message_text', 'created_at'])
    for evaluation in evaluations:
        for turn in sorted(evaluation.turns, key=lambda item: item.turn_index):
            writer.writerow([
                evaluation.session.participant.participant_code,
                evaluation.session_id,
                evaluation.id,
                evaluation.sample.sample_code,
                evaluation.presentation_order,
                turn.turn_index,
                turn.speaker,
                turn.message_type,
                turn.message_text,
                turn.created_at.isoformat(),
            ])
    return output.getvalue()


def export_user_responses_csv(evaluations: Iterable[SampleEvaluation]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['participant_code', 'session_id', 'evaluation_id', 'sample_code', 'presentation_order', 'turn_index', 'message_text', 'created_at'])
    for evaluation in evaluations:
        for turn in sorted(evaluation.turns, key=lambda item: item.turn_index):
            if turn.speaker != SpeakerType.USER.value:
                continue
            writer.writerow([
                evaluation.session.participant.participant_code,
                evaluation.session_id,
                evaluation.id,
                evaluation.sample.sample_code,
                evaluation.presentation_order,
                turn.turn_index,
                turn.message_text,
                turn.created_at.isoformat(),
            ])
    return output.getvalue()


def _pick_export_analysis(analyses: list[EvaluationAnalysis]) -> EvaluationAnalysis | None:
    if not analyses:
        return None
    ordered = sorted(analyses, key=lambda item: item.created_at)
    return next((analysis for analysis in reversed(ordered) if analysis.analysis_scope == AnalysisScope.FINAL.value), ordered[-1])


def _modality_rows(chosen_analysis: EvaluationAnalysis | None) -> dict[str, ModalityAnalysis]:
    if not chosen_analysis:
        return {}
    return {row.modality: row for row in chosen_analysis.modalities}


def _structured_record(evaluation: SampleEvaluation) -> dict[str, object]:
    ordered_analyses = sorted(evaluation.analyses, key=lambda item: item.created_at)
    chosen_analysis = _pick_export_analysis(ordered_analyses)
    modality_rows = _modality_rows(chosen_analysis)
    initial_analysis = next((analysis for analysis in ordered_analyses if analysis.analysis_scope == AnalysisScope.INITIAL.value), None)

    compare_flag = 1 if any(analysis.has_comparison for analysis in ordered_analyses) else 0
    vague_flag = 1 if initial_analysis and initial_analysis.is_vague else 0

    record: dict[str, object] = {
        'Panelist_Code': evaluation.session.participant.participant_code,
        'Sample_Name': evaluation.sample.sample_code,
        'Serving_Order': evaluation.presentation_order,
        'TEXTO': evaluation.accumulated_text,
        'COMPARA': compare_flag,
        'VAGO': vague_flag,
    }

    for modality in ModalityType:
        row = modality_rows.get(modality.value)
        record[f'{modality.value}:MENCION'] = row.mention_text if row and row.mention_text else ''
        record[f'{modality.value}:DESCRIPTOR'] = row.descriptor_text if row and row.descriptor_text else ''
        record[f'{modality.value}:VALORACION'] = row.valuation_text if row and row.valuation_text else ''
    return record


def structured_row_to_api_dict(row: dict[str, object]) -> dict[str, object]:
    return {
        'panelist_code': row['Panelist_Code'],
        'sample_name': row['Sample_Name'],
        'serving_order': row['Serving_Order'],
        'text': row['TEXTO'],
        'compara': row['COMPARA'],
        'vago': row['VAGO'],
        'modalities': {
            modality: {
                'mention_text': row[f'{modality}:MENCION'],
                'descriptor_text': row[f'{modality}:DESCRIPTOR'],
                'valuation_text': row[f'{modality}:VALORACION'],
            }
            for modality in ('ASPECTO', 'OLOR', 'TEXTURA', 'SABOR')
        },
    }


def export_structured_rows(evaluations: Iterable[SampleEvaluation]) -> list[dict[str, object]]:
    return [_structured_record(evaluation) for evaluation in evaluations]


def export_structured_csv(evaluations: Iterable[SampleEvaluation]) -> str:
    rows = export_structured_rows(evaluations)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CANONICAL_STRUCTURED_HEADER)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def export_structured_xlsx(evaluations: Iterable[SampleEvaluation]) -> bytes:
    rows = export_structured_rows(evaluations)
    wb = Workbook()
    ws = wb.active
    ws.title = 'TODOS LOS DATOS'
    ws.append(CANONICAL_STRUCTURED_HEADER)
    for row in rows:
        ws.append([row.get(col, '') for col in CANONICAL_STRUCTURED_HEADER])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
