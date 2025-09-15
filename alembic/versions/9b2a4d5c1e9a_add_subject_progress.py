"""add_subject_progress

Revision ID: 9b2a4d5c1e9a
Revises: 449bca05824d
Create Date: 2025-09-15 20:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b2a4d5c1e9a'
down_revision: Union[str, None] = '449bca05824d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'subject_progress',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schedule_item_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('hours', sa.Float(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_item_id'], ['schedule_items.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('subject_progress', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_subject_progress_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_subject_progress_schedule_item_id'), ['schedule_item_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('subject_progress', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_subject_progress_schedule_item_id'))
        batch_op.drop_index(batch_op.f('ix_subject_progress_id'))
    op.drop_table('subject_progress')

