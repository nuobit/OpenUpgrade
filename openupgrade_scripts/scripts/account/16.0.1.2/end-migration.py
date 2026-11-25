# Copyright 2026 NuoBiT Solutions SL - Eric Antones <eantones@nuobit.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import ast
import json
import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)

# The fields 16.0 removed, by model, that held the 15.0 type of an account
# (`user_type_id.type`): `account_type` holds its 16.0 one on both models.
_REMOVED_FIELDS = {
    "account.account": "internal_type",
    "account.move.line": "account_internal_type",
}
# The 16.0 types each 15.0 type became (pre-migration fills `account_type` from
# the xml-id of the account's type); "other" became every type left.
_NEW_TYPES = {
    "receivable": ["asset_receivable"],
    "payable": ["liability_payable"],
    "liquidity": ["asset_cash", "liability_credit_card"],
}
# The context keys of a favourite that name the fields it groups by, the pivot and
# graph views' included (a measure is a number, never a type)
_GROUPING_KEYS = (
    "group_by",
    "col_group_by",
    "pivot_row_groupby",
    "pivot_column_groupby",
    "graph_groupbys",
)
# The nodes of a Python list or tuple, the shapes of a domain and its conditions
_SEQUENCES = (ast.List, ast.Tuple)


def _new_path(env, model_name, path):
    """The 16.0 path of a 15.0 one that ends on a removed type field, or None."""
    *names, last = path.split(".")
    model = env[model_name]
    for name in names:
        field = model._fields.get(name)
        if field is None or not field.relational:
            return None
        model = env[field.comodel_name]
    if _REMOVED_FIELDS.get(model._name) != last:
        return None
    return ".".join(names + ["account_type"])


def _new_condition(account_types, operator, value):
    """The 16.0 operator and value of a condition on a 15.0 type, or None."""
    if operator in ("=", "!=") and value is False:
        return operator, False
    if operator in ("=", "!=") and isinstance(value, str):
        old_types = [value]
    elif operator in ("in", "not in") and isinstance(value, list):
        old_types = value
    else:
        return None
    if any(old not in _NEW_TYPES and old != "other" for old in old_types):
        return None
    special = {new for news in _NEW_TYPES.values() for new in news}
    chosen = set()
    for old in old_types:
        chosen |= (
            set(_NEW_TYPES[old]) if old != "other" else set(account_types) - special
        )
    inside = [new for new in account_types if new in chosen]
    outside = [new for new in account_types if new not in chosen]
    positive = operator in ("=", "in")
    if outside and len(outside) < len(inside):
        positive, values = not positive, outside
    else:
        values = inside
    if len(values) == 1:
        return "=" if positive else "!=", values[0]
    return "in" if positive else "not in", values


def _literal(node):
    """The value of a constant, or of a list or tuple of strings, else None."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, _SEQUENCES) and all(
        isinstance(elt, ast.Constant) and isinstance(elt.value, str)
        for elt in node.elts
    ):
        return [elt.value for elt in node.elts]
    return None


def _splice(text, edits):
    """The text with the source of each node of `edits` replaced by its new one.

    The nodes come from ``ast.parse(text)``, whose offsets count UTF-8 bytes.
    """
    data = text.encode()
    line_starts = [0]
    for line in data.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    for node, source in sorted(
        edits, key=lambda edit: (edit[0].lineno, edit[0].col_offset), reverse=True
    ):
        start = line_starts[node.lineno - 1] + node.col_offset
        end = line_starts[node.end_lineno - 1] + node.end_col_offset
        data = data[:start] + source.encode() + data[end:]
    return data.decode()


def _new_domain(env, model_name, domain, account_types):
    """The domain with its conditions on a removed type field rewritten.

    Returns the new domain (None when nothing changed) and the conditions on a
    removed type field it could not rewrite.
    """
    edits, kept = [], []
    for node in ast.walk(ast.parse(domain, mode="eval")):
        if not isinstance(node, _SEQUENCES) or len(node.elts) != 3:
            continue
        path, operator, value = (_literal(elt) for elt in node.elts)
        if not isinstance(path, str):
            continue
        new_path = _new_path(env, model_name, path)
        if not new_path:
            continue
        condition = _new_condition(account_types, operator, value)
        if not condition:
            kept.append(ast.get_source_segment(domain, node))
            continue
        opening, closing = "[]" if isinstance(node, ast.List) else "()"
        new_operator, new_value = condition
        edits.append(
            (
                node,
                f"{opening}{new_path!r}, {new_operator!r}, {new_value!r}{closing}",
            )
        )
    return (_splice(domain, edits) if edits else None), kept


def _new_grouping(model_name, context):
    """The context with its grouping on a removed type field rewritten, or None."""
    removed = _REMOVED_FIELDS.get(model_name)
    if not removed:
        return None
    tree = ast.parse(context, mode="eval")
    if not isinstance(tree.body, ast.Dict):
        return None
    edits = []
    for index, key in enumerate(tree.body.keys):
        if _literal(key) not in _GROUPING_KEYS:
            continue
        value = tree.body.values[index]
        for node in value.elts if isinstance(value, _SEQUENCES) else [value]:
            if _literal(node) == removed:
                edits.append((node, repr("account_type")))
    return _splice(context, edits) if edits else None


def _new_sort(model_name, sort):
    """The sort with its orders on a removed type field rewritten, or None.

    The web client reads a favourite's sort with ``JSON.parse``, and drops one
    that is not JSON: the new sort is written as JSON.
    """
    removed = _REMOVED_FIELDS.get(model_name)
    if not removed:
        return None
    orders = _literal(ast.parse(sort, mode="eval").body)
    if not isinstance(orders, list):
        return None
    new_orders = []
    for order in orders:
        field, space, direction = order.partition(" ")
        if field == removed:
            order = "account_type" + space + direction
        new_orders.append(order)
    return json.dumps(new_orders) if new_orders != orders else None


def _rewrite_favourites_account_type(env):
    """15.0's favourites (ir.filters) that use a removed type field,
    `account.account.internal_type` or `account.move.line.account_internal_type`,
    use `account_type` instead, with the 16.0 types each old type became: in
    their domain (also through a path that ends on an account), in their
    context's grouping and in their sort. A condition that cannot be rewritten
    stays as it is and is logged, and so does a favourite with a text that does
    not parse, an empty one included; no favourite's active state is touched.
    """
    account_types = env["account.account"]._fields["account_type"].get_values(env)
    env.cr.execute(
        """
        SELECT id, model_id, domain, context, sort
        FROM ir_filters
        WHERE domain LIKE %(term)s OR context LIKE %(term)s OR sort LIKE %(term)s
        ORDER BY id
        """,
        {"term": "%internal_type%"},
    )
    for favourite_id, model_name, domain, context, sort in env.cr.fetchall():
        if model_name not in env:
            continue
        try:
            new_domain, kept = _new_domain(env, model_name, domain, account_types)
            new_context = _new_grouping(model_name, context)
            new_sort = _new_sort(model_name, sort)
        except SyntaxError as error:
            _logger.warning(
                "Favourite %s (%s) left as it is: its text does not parse (%s)",
                favourite_id,
                model_name,
                error,
            )
            continue
        if kept:
            _logger.warning(
                "Favourite %s (%s) keeps conditions on the removed account type: %s",
                favourite_id,
                model_name,
                "; ".join(kept),
            )
        if new_domain is None and new_context is None and new_sort is None:
            continue
        openupgrade.logged_query(
            env.cr,
            "UPDATE ir_filters SET domain = %s, context = %s, sort = %s WHERE id = %s",
            (
                new_domain or domain,
                new_context or context,
                new_sort or sort,
                favourite_id,
            ),
        )


@openupgrade.migrate()
def migrate(env, version):
    _rewrite_favourites_account_type(env)
