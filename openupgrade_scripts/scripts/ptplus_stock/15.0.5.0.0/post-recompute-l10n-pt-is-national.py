import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)

# Kept small so each browse+compute+flush cycle stays within the container
# memory budget: the cache is dropped between chunks (invalidate_cache), so
# peak memory is one chunk, not the whole table. No commit inside the loop:
# @openupgrade.migrate() wraps the script in a savepoint (a commit would
# destroy it -> RELEASE SAVEPOINT crashes on exit) and the module upgrade
# must stay transactional; flushed rows live in the module's transaction.
CHUNK = 5000


def _batched_recompute(env, model_name, fname):
    """Recompute one stored computed field over the whole table, in
    memory-safe chunks, using the model's OWN compute method via the ORM.

    The column was pre-created empty in pre-migration to skip the ORM's
    whole-table mass init (which OOM-kills the upgrade). Here we fill it: the
    compute is triggered through the ORM (add_to_compute + flush), so the
    vendor's real compute logic runs — we never need to read or reimplement
    it. Self-contained: the field is created AND filled within this same hop.
    """
    model = env[model_name].with_context(active_test=False, prefetch_fields=False)
    field = model._fields[fname]
    env.cr.execute('SELECT id FROM "%s" ORDER BY id' % model._table)
    ids = [row[0] for row in env.cr.fetchall()]
    total = len(ids)
    _logger.info(
        "recompute %s.%s over %s rows (chunk %s)", model_name, fname, total, CHUNK
    )
    for start in range(0, total, CHUNK):
        recs = model.browse(ids[start : start + CHUNK])
        env.add_to_compute(field, recs)
        recs.flush([fname], recs)
        recs.invalidate_cache()
        if start and start % (CHUNK * 20) == 0:
            _logger.info("  ... %s/%s", start, total)
    _logger.info("recompute %s.%s done", model_name, fname)


@openupgrade.migrate()
def migrate(env, version):
    _batched_recompute(env, "stock.picking", "l10n_pt_is_national")
