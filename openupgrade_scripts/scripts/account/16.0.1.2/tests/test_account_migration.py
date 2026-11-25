import importlib.util
import json
import logging
import os

from odoo.tests import TransactionCase
from odoo.tools.safe_eval import datetime, dateutil, safe_eval

SPECIAL_TYPES = [
    "asset_receivable",
    "asset_cash",
    "liability_payable",
    "liability_credit_card",
]

# These tests run when account is loaded, and end-migration only once every module
# is: they run its rewrite themselves, in their transaction, on the favourites the
# data snippet created on 15.0.
_spec = importlib.util.spec_from_file_location(
    "account_16_end_migration",
    os.path.join(os.path.dirname(__file__), os.pardir, "end-migration.py"),
)
end_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(end_migration)


class _Warnings(logging.Handler):
    """The warnings end-migration logs"""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class TestAccountMigration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.warnings = _Warnings()
        end_migration._logger.addHandler(cls.warnings)
        try:
            end_migration._rewrite_favourites_account_type(cls.env)
        finally:
            end_migration._logger.removeHandler(cls.warnings)
        cls.env.invalidate_all()

    def _favourite(self, name):
        return (
            self.env["ir.filters"]
            .with_context(active_test=False)
            .search([("name", "=", "OU16 " + name)])
        )

    def _domain(self, name):
        return safe_eval(
            self._favourite(name).domain,
            {
                "context_today": datetime.datetime.now,
                "datetime": datetime,
                "relativedelta": dateutil.relativedelta.relativedelta,
            },
        )

    def _warned(self, name):
        """The warnings that name the favourite"""
        prefix = f"Favourite {self._favourite(name).id} "
        return [
            message for message in self.warnings.messages if message.startswith(prefix)
        ]

    def test_favourite_domains(self):
        """Each condition on a 15.0 type is on `account_type`, with the types it became"""
        self.assertEqual(
            self._domain("receivable"),
            [("account_id.account_type", "=", "asset_receivable")],
        )
        self.assertEqual(
            self._domain("lines"),
            [("account_type", "in", ["asset_receivable", "liability_payable"])],
        )
        self.assertEqual(
            self._domain("liquidity"),
            [("account_type", "in", ["asset_cash", "liability_credit_card"])],
        )
        self.assertEqual(
            self._domain("not other"), [("account_type", "in", SPECIAL_TYPES)]
        )
        self.assertEqual(
            self._domain("other"), [("account_type", "not in", SPECIAL_TYPES)]
        )
        self.assertEqual(self._domain("empty"), [("account_type", "in", [])])
        all_types = (
            self.env["account.account"]._fields["account_type"].get_values(self.env)
        )
        self.assertEqual(
            self._domain("every type"), [("account_type", "in", all_types)]
        )
        self.assertEqual(self._domain("unset"), [("account_type", "!=", False)])
        self.assertEqual(
            self._domain("moves"),
            [("line_ids.account_id.account_type", "=", "asset_receivable")],
        )

    def test_favourite_rest_untouched(self):
        """Only the conditions on the type change: the rest of the text, the lines it
        is written on and a sort without the type stay as they were"""
        self.assertEqual(
            self._favourite("mixed").domain,
            "['&', ('date', '>=', (context_today() - relativedelta(months=1))"
            ".strftime('%Y-%m-%d')), ('account_id.account_type', '!=', 'liability_payable')]",
        )
        self.assertEqual(
            self._favourite("same value").domain,
            "[('name', '=', 'receivable'), ('account_type', '=', 'liability_payable')]",
        )
        self.assertEqual(
            self._favourite("three").domain,
            "[('debit', '>', 0), ('account_type', '=', 'asset_receivable'), "
            "('name', 'ilike', 'x')]",
        )
        self.assertEqual(
            self._favourite("constant leaf").domain,
            "['&', (1, '=', 1), ('account_type', '=', 'asset_receivable')]",
        )
        self.assertEqual(
            self._favourite("two lines").domain,
            "[\n    '|',\n    ('account_type', '=', 'asset_receivable'),\n"
            "    ('account_type', '=', 'liability_payable'),\n]",
        )
        compact = self._favourite("compact sort")
        self.assertEqual(compact.domain, "[('account_type', '=', 'liability_payable')]")
        self.assertEqual(compact.sort, '["date desc","id"]')

    def test_favourite_text_with_accents(self):
        """A condition after a text with accents is replaced at its own place"""
        self.assertEqual(
            self._favourite("accents").domain,
            "[('name', 'ilike', 'Atenció'), "
            "('account_id.account_type', '=', 'liability_payable')]",
        )

    def test_favourite_grouping_and_sort(self):
        """The grouping and the sort on a 15.0 type field use `account_type`; the
        context's other keys stay as they were"""
        self.assertEqual(
            self._favourite("grouped").context,
            "{'group_by': ['company_id', 'account_type']}",
        )
        self.assertEqual(
            self._favourite("grouped text").context,
            "{'group_by': 'account_type', 'default_name': 'internal_type'}",
        )
        self.assertEqual(
            self._favourite("pivot").context,
            "{'pivot_measures': ['__count'], 'pivot_row_groupby': ['account_type'], "
            "'pivot_column_groupby': ['company_id', 'account_type'], "
            "'col_group_by': ['account_type']}",
        )
        self.assertEqual(
            self._favourite("graph").context,
            "{'graph_measure': '__count__', 'graph_mode': 'bar', "
            "'graph_groupbys': ['account_type']}",
        )
        sort = self._favourite("sorted").sort
        self.assertEqual(json.loads(sort), ["code", "account_type desc"])
        sort = self._favourite("sorted lines").sort
        self.assertEqual(json.loads(sort), ["account_type", "date desc"])

    def test_favourite_active_state(self):
        """No favourite is switched on or off"""
        self.assertFalse(self._favourite("inactive").active)
        self.assertEqual(
            self._domain("inactive"),
            [("account_id.account_type", "=", "liability_payable")],
        )
        for name in ("receivable", "lines", "liquidity", "mixed", "grouped", "moves"):
            self.assertTrue(self._favourite(name).active, name)

    def test_favourite_unknown_type_kept(self):
        """A condition on a value no 16.0 type stands for, or in a form the rewrite
        does not read, is left as it is, and logged"""
        self.assertEqual(
            self._domain("unknown"), [("account_id.internal_type", "=", "nonsense")]
        )
        self.assertEqual(len(self._warned("unknown")), 1)
        odd = self._favourite("odd values")
        self.assertEqual(
            odd.domain,
            "[('internal_type', '=', ['receivable']), ('internal_type', 'in', uid), "
            "('internal_type', uid, 'receivable'), ('internal_type', 'in', 'receivable'), "
            "('internal_type', 'in', False)]",
        )
        self.assertEqual(
            self._warned("odd values"),
            [
                f"Favourite {odd.id} (account.account) keeps conditions on the removed "
                "account type: ('internal_type', '=', ['receivable']); "
                "('internal_type', 'in', uid); ('internal_type', uid, 'receivable'); "
                "('internal_type', 'in', 'receivable'); ('internal_type', 'in', False)"
            ],
        )

    def test_favourite_left_as_it_is(self):
        """What the rewrite cannot read is left as it is, and the migration goes on;
        of a favourite of another model, only the domain is read"""
        self.assertEqual(
            self._favourite("broken").domain, "[('internal_type', '=', 'receivable')"
        )
        self.assertEqual(len(self._warned("broken")), 1)
        empty = self._favourite("empty text")
        self.assertEqual(empty.domain, "")
        self.assertEqual(empty.context, "{'group_by': ['internal_type']}")
        self.assertEqual(len(self._warned("empty text")), 1)
        shapes = self._favourite("odd shapes")
        self.assertEqual(shapes.domain, "[('account_type', '=', 'liability_payable')]")
        self.assertEqual(shapes.context, "dict(group_by=['internal_type'])")
        self.assertEqual(shapes.sort, '[1, "internal_type desc"]')
        self.assertFalse(self._warned("odd shapes"))
        moves = self._favourite("moves, odd texts")
        self.assertEqual(
            moves.domain,
            "[('line_ids.account_id.account_type', '=', 'liability_payable')]",
        )
        self.assertEqual(moves.context, "{'group_by': ['partner_id']")
        self.assertEqual(moves.sort, '["date desc"')
        self.assertFalse(self._warned("moves, odd texts"))
        self.assertEqual(
            self._favourite("gone model").domain,
            "[('internal_type', '=', 'payable')]",
        )
        for name, domain in (
            ("unknown path", [("x_missing.internal_type", "=", "receivable")]),
            ("char path", [("name.internal_type", "=", "receivable")]),
        ):
            self.assertEqual(self._domain(name), domain, name)
            self.assertFalse(self._warned(name), name)

    def test_favourites_search(self):
        """Every rewritten favourite searches, groups and sorts without error on 16.0"""
        for name in (
            "receivable",
            "lines",
            "liquidity",
            "not other",
            "other",
            "empty",
            "every type",
            "unset",
            "mixed",
            "same value",
            "three",
            "constant leaf",
            "two lines",
            "compact sort",
            "moves",
            "odd shapes",
            "moves, odd texts",
        ):
            favourite = self._favourite(name)
            self.env[favourite.model_id].search_count(self._domain(name))
        accounts = self.env["account.account"]
        accounts.read_group(
            self._domain("grouped"),
            ["company_id", "account_type"],
            ["company_id", "account_type"],
            lazy=False,
        )
        accounts.search(
            [], order=", ".join(json.loads(self._favourite("sorted").sort)), limit=1
        )
