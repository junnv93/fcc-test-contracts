"""Validate provider service deployment evidence for platform operations.

The validator checks evidence metadata only. It does not install services,
contact health endpoints, copy files, delete files, or connect to databases.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


__all__ = [
    'REQUIRED_PROVIDER_ENV',
    'ServiceDeploymentIssue',
    'is_provider_service_deployment_valid',
    'provider_service_deployment_errors',
]


REQUIRED_PROVIDER_ENV = (
    'FCC_HEADLESS_DB_PATH',
    'FCC_HEADLESS_ARTIFACT_ROOTS',
    'FCC_HEADLESS_REPORT_OUTPUT_DIR',
    'FCC_HEADLESS_LOG_DIR',
    'FCC_HEADLESS_HEALTH_URL',
)

_SECRET_KEY_MARKERS = (
    'SECRET',
    'TOKEN',
    'PASSWORD',
    'CREDENTIAL',
    'PRIVATE',
)
_REDACTED_VALUES = {
    '',
    '<redacted>',
    '***',
    'redacted',
    'REDACTED',
}


@dataclass(frozen=True)
class ServiceDeploymentIssue:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'path': self.path,
            'message': self.message,
        }


def is_provider_service_deployment_valid(manifest: Mapping) -> bool:
    return not provider_service_deployment_errors(manifest)


def provider_service_deployment_errors(manifest: Mapping) -> list[ServiceDeploymentIssue]:
    issues: list[ServiceDeploymentIssue] = []
    if manifest.get('schema_version') != 1:
        issues.append(_issue('invalid_schema_version', 'schema_version', 'schema_version must be 1'))

    _require_text(manifest, 'provider_id', 'provider_id', issues)
    _require_text(manifest, 'host_id', 'host_id', issues)
    _require_text(manifest, 'deployed_at', 'deployed_at', issues)

    service = _mapping(manifest.get('service'))
    if not service:
        issues.append(_issue('missing_service', 'service', 'service is required'))
    else:
        _validate_service(service, issues)

    environment = _mapping(manifest.get('environment'))
    if not environment:
        issues.append(_issue('missing_environment', 'environment', 'environment is required'))
    else:
        _validate_environment(environment, issues)

    health_check = _mapping(manifest.get('health_check'))
    if not health_check:
        issues.append(_issue('missing_health_check', 'health_check', 'health_check is required'))
    else:
        _validate_health_check(health_check, issues)

    logs = _mapping(manifest.get('log_collection'))
    if not logs:
        issues.append(_issue('missing_log_collection', 'log_collection', 'log_collection is required'))
    else:
        _validate_log_collection(logs, issues)

    monitoring = _mapping(manifest.get('monitoring_alert'))
    if not monitoring:
        issues.append(_issue('missing_monitoring_alert', 'monitoring_alert', 'monitoring_alert is required'))
    else:
        _validate_monitoring_alert(monitoring, issues)

    backup_scope = _mapping(manifest.get('backup_scope'))
    if not backup_scope:
        issues.append(_issue('missing_backup_scope', 'backup_scope', 'backup_scope is required'))
    else:
        _validate_backup_scope(backup_scope, issues)

    return issues


def _validate_service(service: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    _require_text(service, 'service_name', 'service.service_name', issues)
    _require_text(service, 'service_manager', 'service.service_manager', issues)
    _require_text(service, 'start_mode', 'service.start_mode', issues)

    command = service.get('command')
    command_text = _command_text(command)
    if not command_text:
        issues.append(_issue('missing_service_command', 'service.command', 'command is required'))
        return
    if 'uvicorn' not in command_text:
        issues.append(_issue('missing_uvicorn_command', 'service.command', 'command must launch uvicorn'))
    if '--factory' not in command_text:
        issues.append(_issue('missing_factory_flag', 'service.command', 'command must use --factory'))
    if 'headless_api_app:create_app' not in command_text:
        issues.append(
            _issue(
                'missing_headless_app_factory',
                'service.command',
                'command must launch headless_api_app:create_app',
            )
        )


def _validate_environment(environment: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    for key in REQUIRED_PROVIDER_ENV:
        if not _text(environment.get(key)):
            issues.append(_issue('missing_required_env', f'environment.{key}', f'{key} is required'))

    for key, value in environment.items():
        key_text = str(key or '').upper()
        if not any(marker in key_text for marker in _SECRET_KEY_MARKERS):
            continue
        value_text = _text(value)
        if value_text not in _REDACTED_VALUES:
            issues.append(
                _issue(
                    'secret_value_not_redacted',
                    f'environment.{key}',
                    'secret-like environment values must be absent or redacted',
                )
            )


def _validate_health_check(health_check: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    _require_text(health_check, 'url', 'health_check.url', issues)
    _require_text(health_check, 'checked_at', 'health_check.checked_at', issues)
    status_code = _int(health_check.get('status_code'))
    if status_code is None:
        issues.append(_issue('missing_health_status', 'health_check.status_code', 'status_code is required'))
    elif not 200 <= status_code < 300:
        issues.append(_issue('health_check_failed', 'health_check.status_code', 'status_code must be 2xx'))


def _validate_log_collection(logs: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    if logs.get('enabled') is not True:
        issues.append(_issue('log_collection_disabled', 'log_collection.enabled', 'enabled must be true'))
    _require_text(logs, 'log_dir', 'log_collection.log_dir', issues)
    _require_text(logs, 'collector', 'log_collection.collector', issues)
    retention_days = _int(logs.get('retention_days'))
    if retention_days is None:
        issues.append(_issue('missing_log_retention', 'log_collection.retention_days', 'retention_days is required'))
    elif retention_days <= 0:
        issues.append(
            _issue(
                'invalid_log_retention',
                'log_collection.retention_days',
                'retention_days must be positive',
            )
        )


def _validate_monitoring_alert(monitoring: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    if monitoring.get('enabled') is not True:
        issues.append(_issue('monitoring_disabled', 'monitoring_alert.enabled', 'enabled must be true'))
    _require_text(monitoring, 'health_url', 'monitoring_alert.health_url', issues)
    _require_text(monitoring, 'alert_channel', 'monitoring_alert.alert_channel', issues)
    _require_text(monitoring, 'alert_target', 'monitoring_alert.alert_target', issues)
    interval_seconds = _int(monitoring.get('interval_seconds'))
    if interval_seconds is None:
        issues.append(
            _issue(
                'missing_monitoring_interval',
                'monitoring_alert.interval_seconds',
                'interval_seconds is required',
            )
        )
    elif interval_seconds <= 0:
        issues.append(
            _issue(
                'invalid_monitoring_interval',
                'monitoring_alert.interval_seconds',
                'interval_seconds must be positive',
            )
        )


def _validate_backup_scope(backup_scope: Mapping, issues: list[ServiceDeploymentIssue]) -> None:
    _require_text(backup_scope, 'database_path', 'backup_scope.database_path', issues)
    _require_text(backup_scope, 'report_output_dir', 'backup_scope.report_output_dir', issues)
    artifact_roots = backup_scope.get('artifact_roots')
    if not isinstance(artifact_roots, Sequence) or isinstance(artifact_roots, (str, bytes)):
        issues.append(_issue('missing_artifact_roots', 'backup_scope.artifact_roots', 'artifact_roots must be a list'))
        return
    if not artifact_roots:
        issues.append(_issue('empty_artifact_roots', 'backup_scope.artifact_roots', 'artifact_roots must not be empty'))
        return
    for index, root in enumerate(artifact_roots):
        if not _text(root):
            issues.append(
                _issue(
                    'empty_artifact_root',
                    f'backup_scope.artifact_roots[{index}]',
                    'artifact root must not be empty',
                )
            )


def _require_text(
    mapping: Mapping,
    key: str,
    path: str,
    issues: list[ServiceDeploymentIssue],
) -> None:
    if not _text(mapping.get(key)):
        issues.append(_issue('missing_required_field', path, f'{key} is required'))


def _command_text(command) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, Sequence):
        return ' '.join(str(part) for part in command)
    return ''


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _text(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _issue(code: str, path: str, message: str) -> ServiceDeploymentIssue:
    return ServiceDeploymentIssue(code=code, path=path, message=message)
