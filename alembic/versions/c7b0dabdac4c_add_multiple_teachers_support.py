"""add_multiple_teachers_support

Revision ID: c7b0dabdac4c
Revises: d6d0d7d068e5
Create Date: 2025-11-18 02:58:59.105922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7b0dabdac4c'
down_revision: Union[str, None] = 'd6d0d7d068e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create association table for schedule_item <-> teacher (many-to-many)
    op.create_table(
        'schedule_item_teachers',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('schedule_item_id', sa.Integer(), sa.ForeignKey('schedule_items.id'), nullable=False, index=True),
        sa.Column('teacher_id', sa.Integer(), sa.ForeignKey('teachers.id'), nullable=False, index=True),
        sa.Column('slot_number', sa.Integer(), default=1, nullable=False),  # 1, 2, 3... for ordering
        sa.Column('is_primary', sa.Boolean(), default=True, nullable=False)  # Primary teacher flag
    )
    op.create_index('ix_schedule_item_teachers_item_id', 'schedule_item_teachers', ['schedule_item_id'])
    op.create_index('ix_schedule_item_teachers_teacher_id', 'schedule_item_teachers', ['teacher_id'])

    # Add teacher_slots field to schedule_items (how many teacher slots this item needs)
    op.add_column('schedule_items', sa.Column('teacher_slots', sa.Integer(), default=1, nullable=False))

    # Migrate existing data: copy teacher_id from schedule_items to schedule_item_teachers
    op.execute("""
        INSERT INTO schedule_item_teachers (schedule_item_id, teacher_id, slot_number, is_primary)
        SELECT id, teacher_id, 1, true
        FROM schedule_items
        WHERE teacher_id IS NOT NULL
    """)

    # Note: We keep teacher_id in schedule_items for backwards compatibility (will be deprecated later)


def downgrade() -> None:
    op.drop_index('ix_schedule_item_teachers_teacher_id', 'schedule_item_teachers')
    op.drop_index('ix_schedule_item_teachers_item_id', 'schedule_item_teachers')
    op.drop_table('schedule_item_teachers')
    op.drop_column('schedule_items', 'teacher_slots')
