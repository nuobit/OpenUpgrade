env = locals().get("env")
# Favourites (ir.filters) that use the 15.0 account types, `internal_type` on the
# accounts and `account_internal_type` on the journal items, in their domain,
# grouping and sort: end-migration rewrites them to `account_type`. Each is
# (name, model, domain, context, sort); the sort is JSON, as the web client
# writes it.
favourites = [
    (
        "receivable",
        "account.move.line",
        "[('account_id.internal_type', '=', 'receivable')]",
        "{}",
        "[]",
    ),
    (
        "lines",
        "account.move.line",
        '[("account_internal_type", "in", ["receivable", "payable"])]',
        "{}",
        "[]",
    ),
    (
        "liquidity",
        "account.account",
        "[('internal_type', '=', 'liquidity')]",
        "{}",
        "[]",
    ),
    ("not other", "account.account", "[('internal_type', '!=', 'other')]", "{}", "[]"),
    ("other", "account.account", "[('internal_type', '=', 'other')]", "{}", "[]"),
    ("empty", "account.account", "[('internal_type', 'in', [])]", "{}", "[]"),
    (
        "every type",
        "account.account",
        "[('internal_type', 'in', ['receivable', 'payable', 'liquidity', 'other'])]",
        "{}",
        "[]",
    ),
    (
        "mixed",
        "account.move.line",
        "['&', ('date', '>=', (context_today() - relativedelta(months=1))"
        ".strftime('%Y-%m-%d')), ('account_id.internal_type', 'not in', ('payable',))]",
        "{}",
        "[]",
    ),
    (
        "same value",
        "account.account",
        "[('name', '=', 'receivable'), ('internal_type', '=', 'payable')]",
        "{}",
        "[]",
    ),
    (
        "three",
        "account.move.line",
        "[('debit', '>', 0), ('account_internal_type', '=', 'receivable'), "
        "('name', 'ilike', 'x')]",
        "{}",
        "[]",
    ),
    (
        "constant leaf",
        "account.account",
        "['&', (1, '=', 1), ('internal_type', '=', 'receivable')]",
        "{}",
        "[]",
    ),
    (
        "two lines",
        "account.account",
        "[\n    '|',\n    ('internal_type', '=', 'receivable'),\n"
        "    ('internal_type',\n     '=', 'payable'),\n]",
        "{}",
        "[]",
    ),
    (
        "compact sort",
        "account.move.line",
        "[('account_internal_type', '=', 'payable')]",
        "{}",
        '["date desc","id"]',
    ),
    (
        "inactive",
        "account.move.line",
        "[('account_id.internal_type', '=', 'payable')]",
        "{}",
        "[]",
    ),
    (
        "grouped",
        "account.account",
        "[('internal_type', '=', 'liquidity')]",
        "{'group_by': ['company_id', 'internal_type']}",
        "[]",
    ),
    (
        "grouped text",
        "account.account",
        "[]",
        "{'group_by': 'internal_type', 'default_name': 'internal_type'}",
        "[]",
    ),
    (
        "pivot",
        "account.account",
        "[]",
        "{'pivot_measures': ['__count'], 'pivot_row_groupby': ['internal_type'], "
        "'pivot_column_groupby': ['company_id', 'internal_type'], "
        "'col_group_by': ['internal_type']}",
        "[]",
    ),
    (
        "graph",
        "account.account",
        "[]",
        "{'graph_measure': '__count__', 'graph_mode': 'bar', "
        "'graph_groupbys': ['internal_type']}",
        "[]",
    ),
    (
        "sorted",
        "account.account",
        "[('code', '!=', False)]",
        "{}",
        '["code", "internal_type desc"]',
    ),
    (
        "sorted lines",
        "account.move.line",
        "[]",
        "{}",
        '["account_internal_type","date desc"]',
    ),
    (
        "accents",
        "account.move.line",
        "[('name', 'ilike', 'Atenció'), ('account_id.internal_type', '=', 'payable')]",
        "{}",
        "[]",
    ),
    (
        "unknown",
        "account.move.line",
        "[('account_id.internal_type', '=', 'nonsense')]",
        "{}",
        "[]",
    ),
    (
        "unknown path",
        "account.move.line",
        "[('x_missing.internal_type', '=', 'receivable')]",
        "{}",
        "[]",
    ),
    (
        "char path",
        "account.move.line",
        "[('name.internal_type', '=', 'receivable')]",
        "{}",
        "[]",
    ),
    (
        "moves",
        "account.move",
        "[('line_ids.account_id.internal_type', '=', 'receivable')]",
        "{}",
        "[]",
    ),
    ("unset", "account.account", "[('internal_type', '!=', False)]", "{}", "[]"),
    (
        "odd values",
        "account.account",
        "[('internal_type', '=', ['receivable']), ('internal_type', 'in', uid), "
        "('internal_type', uid, 'receivable'), ('internal_type', 'in', 'receivable'), "
        "('internal_type', 'in', False)]",
        "{}",
        "[]",
    ),
    (
        "odd shapes",
        "account.account",
        "[('internal_type', '=', 'payable')]",
        "dict(group_by=['internal_type'])",
        '[1, "internal_type desc"]',
    ),
    (
        "moves, odd texts",
        "account.move",
        "[('line_ids.account_id.internal_type', '=', 'payable')]",
        "{}",
        "[]",
    ),
    ("broken", "account.account", "[('internal_type', '=', 'receivable')]", "{}", "[]"),
    (
        "empty text",
        "account.account",
        "[]",
        "{'group_by': ['internal_type']}",
        "[]",
    ),
    (
        "gone model",
        "account.account",
        "[('internal_type', '=', 'payable')]",
        "{}",
        "[]",
    ),
]
for name, model, domain, context, sort in favourites:
    env["ir.filters"].create(
        {
            "name": "OU16 " + name,
            "model_id": model,
            "domain": domain,
            "context": context,
            "sort": sort,
            "active": name != "inactive",
        }
    )
# Favourites no form writes: a text that does not parse, an empty one, texts that
# do not parse where they are not read (the context and sort of a favourite of
# the moves), and one of a model no longer loaded
env.cr.execute(
    "UPDATE ir_filters SET domain = %s WHERE name = %s",
    ("[('internal_type', '=', 'receivable')", "OU16 broken"),
)
env.cr.execute(
    "UPDATE ir_filters SET domain = %s WHERE name = %s", ("", "OU16 empty text")
)
env.cr.execute(
    "UPDATE ir_filters SET context = %s, sort = %s WHERE name = %s",
    ("{'group_by': ['partner_id']", '["date desc"', "OU16 moves, odd texts"),
)
env.cr.execute(
    "UPDATE ir_filters SET model_id = %s WHERE name = %s",
    ("x_gone.model", "OU16 gone model"),
)
env.cr.commit()
