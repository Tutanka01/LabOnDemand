"""initial schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-23 08:50:10.986797

Baseline : schéma complet de backend/models.py au moment de l'introduction
d'Alembic, identique à ce que produisait Base.metadata.create_all().

Autogénérée contre une base vide puis relue à la main :
  - server_default=sa.func.now() (et non le texte propre à un dialecte) pour
    obtenir le même DDL que create_all sur MariaDB comme sur SQLite ;
  - index créés par op.create_index (noms ix_<table>_<colonne> de SQLAlchemy,
    donc identiques à ceux des bases existantes) ;
  - clés étrangères dans l'ordre de déclaration des modèles (celui de
    create_all, et non l'ordre alphabétique d'autogenerate) : MariaDB les nomme
    <table>_ibfk_N selon cet ordre, les noms restent donc ceux des bases
    existantes ;
  - pas de naming_convention : les noms des bases existantes sont conservés ;
  - downgrade refusé.

Les bases antérieures à Alembic ne rejouent pas cette révision : elles sont
mises à niveau par backend/migrations.py puis marquées (stamp) à cette révision
par backend/db_migrate.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Crée le schéma complet (base vierge)."""
    op.create_table('runtime_configs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=50), nullable=False),
    sa.Column('default_image', sa.String(length=200), nullable=True),
    sa.Column('target_port', sa.Integer(), nullable=True),
    sa.Column('default_service_type', sa.String(length=30), nullable=False),
    sa.Column('allowed_for_students', sa.Boolean(), nullable=True),
    sa.Column('min_cpu_request', sa.String(length=20), nullable=True),
    sa.Column('min_memory_request', sa.String(length=20), nullable=True),
    sa.Column('min_cpu_limit', sa.String(length=20), nullable=True),
    sa.Column('min_memory_limit', sa.String(length=20), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_runtime_configs_id'), 'runtime_configs', ['id'], unique=False)
    op.create_index(op.f('ix_runtime_configs_key'), 'runtime_configs', ['key'], unique=True)

    op.create_table('templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('icon', sa.String(length=100), nullable=True),
    sa.Column('deployment_type', sa.String(length=30), nullable=False),
    sa.Column('default_image', sa.String(length=200), nullable=True),
    sa.Column('default_port', sa.Integer(), nullable=True),
    sa.Column('default_service_type', sa.String(length=30), nullable=False),
    sa.Column('tags', sa.String(length=255), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_templates_id'), 'templates', ['id'], unique=False)
    op.create_index(op.f('ix_templates_key'), 'templates', ['key'], unique=True)

    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('full_name', sa.String(length=100), nullable=True),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('auth_provider', sa.String(length=20), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=True),
    sa.Column('role', sa.Enum('student', 'teacher', 'admin', name='userrole'), nullable=False),
    sa.Column('role_override', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_external_id'), 'users', ['external_id'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)

    op.create_table('classrooms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=True),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_classrooms_archived'), 'classrooms', ['archived'], unique=False)
    op.create_index(op.f('ix_classrooms_id'), 'classrooms', ['id'], unique=False)
    op.create_index(op.f('ix_classrooms_name'), 'classrooms', ['name'], unique=False)
    op.create_index(op.f('ix_classrooms_owner_id'), 'classrooms', ['owner_id'], unique=False)

    op.create_table('deployments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('deployment_type', sa.String(length=50), nullable=False),
    sa.Column('namespace', sa.String(length=100), nullable=False),
    sa.Column('stack_name', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cpu_requested', sa.String(length=20), nullable=True),
    sa.Column('mem_requested', sa.String(length=20), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deployments_created_at'), 'deployments', ['created_at'], unique=False)
    op.create_index(op.f('ix_deployments_expires_at'), 'deployments', ['expires_at'], unique=False)
    op.create_index(op.f('ix_deployments_id'), 'deployments', ['id'], unique=False)
    op.create_index(op.f('ix_deployments_name'), 'deployments', ['name'], unique=False)
    op.create_index(op.f('ix_deployments_status'), 'deployments', ['status'], unique=False)
    op.create_index(op.f('ix_deployments_user_id'), 'deployments', ['user_id'], unique=False)

    op.create_table('user_quota_overrides',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('max_apps', sa.Integer(), nullable=True),
    sa.Column('max_cpu_m', sa.Integer(), nullable=True),
    sa.Column('max_mem_mi', sa.Integer(), nullable=True),
    sa.Column('max_storage_gi', sa.Integer(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_quota_overrides_id'), 'user_quota_overrides', ['id'], unique=False)
    op.create_index(op.f('ix_user_quota_overrides_user_id'), 'user_quota_overrides', ['user_id'], unique=True)

    op.create_table('assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('classroom_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('instructions', sa.Text(), nullable=True),
    sa.Column('deliverables', sa.Text(), nullable=True),
    sa.Column('template_key', sa.String(length=50), nullable=True),
    sa.Column('cpu_preset', sa.String(length=20), nullable=True),
    sa.Column('ram_preset', sa.String(length=20), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('grading_mode', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assignments_classroom_id'), 'assignments', ['classroom_id'], unique=False)
    op.create_index(op.f('ix_assignments_id'), 'assignments', ['id'], unique=False)

    op.create_table('enrollments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('classroom_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('enrolled_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['classroom_id'], ['classrooms.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('classroom_id', 'user_id', name='uq_enrollment_classroom_user')
    )
    op.create_index(op.f('ix_enrollments_classroom_id'), 'enrollments', ['classroom_id'], unique=False)
    op.create_index(op.f('ix_enrollments_id'), 'enrollments', ['id'], unique=False)
    op.create_index(op.f('ix_enrollments_user_id'), 'enrollments', ['user_id'], unique=False)

    op.create_table('assignment_deployments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('deployment_id', sa.Integer(), nullable=True),
    sa.Column('spawn_status', sa.String(length=20), nullable=False),
    sa.Column('spawn_error', sa.String(length=500), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assignment_deployments_assignment_id'), 'assignment_deployments', ['assignment_id'], unique=False)
    op.create_index(op.f('ix_assignment_deployments_deployment_id'), 'assignment_deployments', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_assignment_deployments_id'), 'assignment_deployments', ['id'], unique=False)
    op.create_index(op.f('ix_assignment_deployments_user_id'), 'assignment_deployments', ['user_id'], unique=False)

    op.create_table('assignment_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('attempt_no', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('links', sa.Text(), nullable=True),
    sa.Column('deployment_id', sa.Integer(), nullable=True),
    sa.Column('lab_snapshot', sa.Text(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('is_late', sa.Boolean(), nullable=False),
    sa.Column('due_at_snapshot', sa.DateTime(timezone=True), nullable=True),
    sa.Column('grade', sa.String(length=20), nullable=True),
    sa.Column('feedback', sa.Text(), nullable=True),
    sa.Column('graded_by', sa.Integer(), nullable=True),
    sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['graded_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('assignment_id', 'user_id', name='uq_submission_assignment_user')
    )
    op.create_index(op.f('ix_assignment_submissions_assignment_id'), 'assignment_submissions', ['assignment_id'], unique=False)
    op.create_index(op.f('ix_assignment_submissions_deployment_id'), 'assignment_submissions', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_assignment_submissions_id'), 'assignment_submissions', ['id'], unique=False)
    op.create_index(op.f('ix_assignment_submissions_user_id'), 'assignment_submissions', ['user_id'], unique=False)

    op.create_table('grading_specs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=False),
    sa.Column('grader_image', sa.String(length=300), nullable=True),
    sa.Column('timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('checks', sa.Text(), nullable=True),
    sa.Column('custom_script', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_grading_specs_assignment_id'), 'grading_specs', ['assignment_id'], unique=True)
    op.create_index(op.f('ix_grading_specs_id'), 'grading_specs', ['id'], unique=False)

    op.create_table('grading_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('assignment_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('submission_id', sa.Integer(), nullable=True),
    sa.Column('deployment_id', sa.Integer(), nullable=True),
    sa.Column('trigger', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('total_checks', sa.Integer(), nullable=True),
    sa.Column('passed_checks', sa.Integer(), nullable=True),
    sa.Column('score_suggestion', sa.String(length=20), nullable=True),
    sa.Column('results', sa.Text(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.Column('result_token_hash', sa.String(length=64), nullable=True),
    sa.Column('token_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['submission_id'], ['assignment_submissions.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['deployment_id'], ['deployments.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_grading_runs_assignment_id'), 'grading_runs', ['assignment_id'], unique=False)
    op.create_index(op.f('ix_grading_runs_deployment_id'), 'grading_runs', ['deployment_id'], unique=False)
    op.create_index(op.f('ix_grading_runs_id'), 'grading_runs', ['id'], unique=False)
    op.create_index(op.f('ix_grading_runs_status'), 'grading_runs', ['status'], unique=False)
    op.create_index(op.f('ix_grading_runs_submission_id'), 'grading_runs', ['submission_id'], unique=False)
    op.create_index(op.f('ix_grading_runs_user_id'), 'grading_runs', ['user_id'], unique=False)


def downgrade() -> None:
    """Refusé : revenir avant la baseline supprimerait toutes les tables."""
    raise NotImplementedError(
        "La baseline ne se rétrograde pas (cela supprimerait toutes les données). "
        "Restaurez une sauvegarde de la base à la place."
    )
