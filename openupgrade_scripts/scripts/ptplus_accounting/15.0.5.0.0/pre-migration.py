from openupgradelib import openupgrade


@openupgrade.migrate()
def migrate(env, version):
    # The 15.0.5.0.0 upgrade adds the stored computed field
    # account_move_line.l10n_pt_account_expected_balance. Creating the column
    # here makes the ORM skip its whole-table "Storing computed values" pass
    # (millions of rows), which cannot fit in memory during `-u all`. The
    # field is recomputed in controlled batches at the target version.
    openupgrade.logged_query(
        env.cr,
        """
        ALTER TABLE account_move_line
        ADD COLUMN IF NOT EXISTS l10n_pt_account_expected_balance numeric
        """,
    )
