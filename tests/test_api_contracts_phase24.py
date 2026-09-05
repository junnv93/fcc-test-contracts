import sys
import unittest
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))
sys.path.insert(0, str(Path(__file__).parent))


class TestHeadlessApiContracts(unittest.TestCase):
    def test_submit_measurement_job_request_validates_and_serializes(self):
        from fcc_test_contracts.headless.api_contracts import SubmitMeasurementJobRequest

        request = SubmitMeasurementJobRequest.from_dict({
            'excel_path': ' plan.xlsx ',
            'requested_by': ' web ',
            'payload': {'sample': 'S1'},
            'options': {'report_automation': {'enabled': False}},
        })

        self.assertEqual(request.excel_path, 'plan.xlsx')
        self.assertEqual(request.requested_by, 'web')
        self.assertEqual(request.to_dict()['payload']['sample'], 'S1')

    def test_submit_measurement_job_request_rejects_missing_excel_path(self):
        from fcc_test_contracts.headless.api_contracts import ApiContractError, SubmitMeasurementJobRequest

        with self.assertRaises(ApiContractError):
            SubmitMeasurementJobRequest.from_dict({'requested_by': 'web'})

    def test_submit_measurement_job_request_rejects_non_object_payload(self):
        from fcc_test_contracts.headless.api_contracts import ApiContractError, SubmitMeasurementJobRequest

        with self.assertRaises(ApiContractError):
            SubmitMeasurementJobRequest.from_dict({
                'excel_path': 'plan.xlsx',
                'payload': ['bad'],
            })

    def test_control_request_messages_default_to_empty_string(self):
        from fcc_test_contracts.headless.api_contracts import (
            CancelReportAutomationRequest,
            StopMeasurementJobRequest,
        )

        self.assertEqual(StopMeasurementJobRequest.from_dict(None).message, '')
        self.assertEqual(CancelReportAutomationRequest.from_dict({}).message, '')
        self.assertEqual(
            StopMeasurementJobRequest.from_dict({'message': ' stop '}).to_dict(),
            {'message': 'stop'},
        )

    def test_contract_snapshot_contains_stable_route_surface(self):
        from fcc_test_contracts.headless.api_contracts import ApiContractSnapshot

        snapshot = ApiContractSnapshot().to_dict()

        self.assertIn('version', snapshot)
        self.assertRegex(snapshot['version'], r'^\d+\.\d+\.\d+$')
        self.assertEqual(snapshot['compatibility_major'], 1)
        self.assertEqual(
            snapshot['provider']['contract_family'],
            'fcc-conducted-headless',
        )
        self.assertEqual(
            snapshot['routes']['health_check'],
            {'method': 'GET', 'path': '/health'},
        )
        self.assertEqual(
            snapshot['routes']['submit_measurement_job'],
            {'method': 'POST', 'path': '/headless/jobs'},
        )
        self.assertEqual(
            snapshot['routes']['provider_capabilities'],
            {'method': 'GET', 'path': '/headless/capabilities'},
        )
        # ⚠️ ``{job_uuid}``, not ``{job_id}`` (2026-09-05). The measurement job
        # is addressed by its opaque handle; the route used to take the storage
        # primary key, which no response declared under that name, which is
        # AUTOINCREMENT (so its value is the lab's job count), and which is not
        # unique across providers. See ``path_identifier_policy``.
        self.assertEqual(
            snapshot['routes']['get_measurement_job'],
            {'method': 'GET', 'path': '/headless/jobs/{job_uuid}'},
        )
        self.assertEqual(
            snapshot['routes']['list_session_results'],
            {'method': 'GET', 'path': '/headless/sessions/{session_id}/results'},
        )
        self.assertEqual(
            snapshot['routes']['list_session_artifacts'],
            {'method': 'GET', 'path': '/headless/sessions/{session_id}/artifacts'},
        )
        self.assertEqual(
            snapshot['routes']['submit_report_request'],
            {'method': 'POST', 'path': '/headless/sessions/{session_id}/reports'},
        )
        self.assertEqual(
            snapshot['routes']['get_report_request'],
            {'method': 'GET', 'path': '/headless/reports/{request_id}'},
        )
        self.assertEqual(
            snapshot['routes']['list_report_outputs'],
            {'method': 'GET', 'path': '/headless/reports/{request_id}/outputs'},
        )
        self.assertEqual(
            snapshot['routes']['cancel_report_automation_request'],
            {
                'method': 'POST',
                'path': '/report-automation/requests/{request_id}/cancel',
            },
        )
        self.assertEqual(
            snapshot['routes']['headless_api_contract'],
            {'method': 'GET', 'path': '/headless/api-contract'},
        )
        self.assertEqual(
            snapshot['operations']['submit_measurement_job']['permission'],
            'headless:control',
        )
        self.assertEqual(
            snapshot['operations']['submit_report_request']['permission'],
            'report_automation:control',
        )
        self.assertEqual(
            snapshot['operations']['health_check']['permission'],
            'public',
        )

    def test_provider_contract_v1_routes_are_machine_readable(self):
        from fcc_test_contracts.headless.api_contracts import ApiContractSnapshot

        snapshot = ApiContractSnapshot().to_dict()
        required = {
            'headless_api_contract',
            'provider_capabilities',
            'submit_measurement_job',
            'list_measurement_jobs',
            'get_measurement_job',
            'stop_measurement_job',
            'list_session_results',
            'list_session_artifacts',
            'submit_report_request',
            'get_report_request',
            'list_report_outputs',
        }

        self.assertTrue(required.issubset(snapshot['routes']))
        self.assertTrue(required.issubset(snapshot['operations']))
        self.assertIn('ProviderCapabilitiesResponse', snapshot['schemas'])
        self.assertIn('MeasurementResultEnvelope', snapshot['schemas'])
        self.assertIn('ArtifactMetadata', snapshot['schemas'])
        self.assertIn('SubmitReportRequest', snapshot['schemas'])
        self.assertIn('ReportRequestSnapshot', snapshot['schemas'])
        self.assertIn('ReportOutputMetadata', snapshot['schemas'])

    def test_response_dtos_keep_external_shape_small(self):
        from fcc_test_contracts.headless.api_contracts import (
            CancelReportAutomationResponse,
            HealthCheckResponse,
            MeasurementJobSubmitted,
            ProviderCapabilitiesResponse,
            ReportRequestSubmitted,
            ReportOutputMetadata,
            StopMeasurementJobResponse,
        )

        self.assertEqual(HealthCheckResponse().to_dict(), {'status': 'ok'})
        # ⚠️ ``id`` is now one of the internal fields this DTO drops, which is
        # exactly what this test is about — the storage primary key is not part
        # of the external shape. It used to be, alongside ``job_uuid``, leaving
        # a consumer to guess which of the two addressed the resource.
        submitted = MeasurementJobSubmitted.from_row({
            'id': 7,
            'status': 'queued',
            'excel_path': 'plan.xlsx',
            'job_uuid': 'uuid-7',
            'internal_extra': 'ignored',
        })

        self.assertEqual(
            submitted.to_dict(),
            {
                'job_uuid': 'uuid-7',
                'status': 'queued',
                'excel_path': 'plan.xlsx',
            },
        )
        self.assertEqual(
            StopMeasurementJobResponse(job_uuid='uuid-7').to_dict(),
            {'job_uuid': 'uuid-7', 'stop_requested': True},
        )
        self.assertEqual(
            CancelReportAutomationResponse(request_id=9).to_dict(),
            {'request_id': 9, 'cancelled': True},
        )
        self.assertEqual(
            ProviderCapabilitiesResponse.default().to_dict()['provider_id'],
            'fcc-unlicensed-conducted',
        )
        self.assertEqual(
            ReportRequestSubmitted(request_id=11, session_id=42).to_dict(),
            {'request_id': 11, 'session_id': 42, 'status': 'queued'},
        )
        # FE-P6-DL: raw absolute filesystem ``path`` removed from the external
        # shape — clients use relative_path + the signed download grant flow.
        self.assertEqual(
            ReportOutputMetadata(
                request_id=11,
                file_name='dts.docx',
                relative_path='dts.docx',
                exists=True,
                byte_size=123,
            ).to_dict(),
            {
                'request_id': 11,
                'file_name': 'dts.docx',
                'relative_path': 'dts.docx',
                'exists': True,
                'byte_size': 123,
                'storage_backend': 'filesystem',
            },
        )


if __name__ == '__main__':
    unittest.main()
