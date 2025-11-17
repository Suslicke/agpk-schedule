"""add_practice_table

Revision ID: a1b2c3d4e5f6
Revises: 9b2a4d5c1e9a
Create Date: 2025-11-17 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9b2a4d5c1e9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'practices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['group_id'], ['groups.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('practices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_practices_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_practices_group_id'), ['group_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('practices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_practices_group_id'))
        batch_op.drop_index(batch_op.f('ix_practices_id'))
    op.drop_table('practices')
