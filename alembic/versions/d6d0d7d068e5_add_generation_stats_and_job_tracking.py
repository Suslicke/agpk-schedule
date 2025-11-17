"""add_generation_stats_and_job_tracking

Revision ID: d6d0d7d068e5
Revises: a1b2c3d4e5f6
Create Date: 2025-11-18 02:26:06.367917

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6d0d7d068e5'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add job_id for tracking async generation jobs
    op.add_column('generated_schedules', sa.Column('job_id', sa.String(), nullable=True))
    op.create_index('ix_generated_schedules_job_id', 'generated_schedules', ['job_id'])

    # Add generation statistics (stored as JSON)
    op.add_column('generated_schedules', sa.Column('stats', sa.JSON(), nullable=True))

    # Add error message for failed generations
    op.add_column('generated_schedules', sa.Column('error_message', sa.String(), nullable=True))

    # Add timestamps
    op.add_column('generated_schedules', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('generated_schedules', sa.Column('completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_index('ix_generated_schedules_job_id', 'generated_schedules')
    op.drop_column('generated_schedules', 'job_id')
    op.drop_column('generated_schedules', 'stats')
    op.drop_column('generated_schedules', 'error_message')
    op.drop_column('generated_schedules', 'created_at')
    op.drop_column('generated_schedules', 'completed_at')
