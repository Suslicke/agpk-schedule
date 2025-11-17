"""add_multiple_teachers_to_day_schedule_entry

Revision ID: a41df36fca7a
Revises: c7b0dabdac4c
Create Date: 2025-11-18 03:28:04.690919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a41df36fca7a'
down_revision: Union[str, None] = 'c7b0dabdac4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create association table for multiple teachers per day schedule entry
    op.create_table(
        'day_schedule_entry_teachers',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('entry_id', sa.Integer(), sa.ForeignKey('day_schedule_entries.id', ondelete='CASCADE'), nullable=False),
        sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('teachers.id'), nullable=False),
        sa.Column('slot_number', sa.Integer(), default=1, nullable=False),
        sa.Column('is_primary', sa.Boolean(), default=True, nullable=False)
    )

    # Add indexes for performance
    op.create_index('ix_day_schedule_entry_teachers_entry_id', 'day_schedule_entry_teachers', ['entry_id'])
    op.create_index('ix_day_schedule_entry_teachers_teacher_id', 'day_schedule_entry_teachers', ['teacher_id'])

    # Migrate existing data: populate association table from existing teacher_id
    # For entries with existing teacher_id, create a record in the association table
    op.execute("""
        INSERT INTO day_schedule_entry_teachers (entry_id, teacher_id, slot_number, is_primary)
        SELECT id, teacher_id, 1, true
        FROM day_schedule_entries
        WHERE teacher_id IS NOT NULL
    """)


def downgrade() -> None:
    # Drop association table
    op.drop_index('ix_day_schedule_entry_teachers_teacher_id', table_name='day_schedule_entry_teachers')
    op.drop_index('ix_day_schedule_entry_teachers_entry_id', table_name='day_schedule_entry_teachers')
    op.drop_table('day_schedule_entry_teachers')
