from odoo.tests import TransactionCase

from odoo.addons.openupgrade_framework import openupgrade_test


@openupgrade_test
class TestStockMigration(TransactionCase):
    def _delivery(self, origin):
        return self.env["stock.picking"].search([("origin", "=", origin)])

    def test_move_quantity(self):
        """
        Test that assigned moves take their reserved quantity
        """
        picking = self.env.ref("stock.outgoing_shipment_main_warehouse4")
        self.assertEqual(picking.move_ids.quantity, 16)
        picking = self.env.ref("stock.incomming_shipment2")
        self.assertEqual(picking.move_ids.quantity, 125)

    def test_open_line_quantity(self):
        """
        Test that an open line keeps its quantity done, never the sum with the
        reserved one, and takes the reserved one when nothing was done
        """
        for origin, quantity in (
            ("ou17-reserved", 3),
            ("ou17-done-equal", 4),
            ("ou17-done-more", 8),
            ("ou17-done-less", 6),
            ("ou17-done-unreserved", 2),
            ("ou17-other-unit", 1),
            ("ou17-partially-available", 100),
            ("ou17-empty-line", 0),
        ):
            self.assertEqual(
                self._delivery(origin).move_line_ids.quantity, quantity, origin
            )
        lines = self._delivery("ou17-several-lines").move_line_ids
        self.assertEqual(sorted(lines.mapped("quantity")), [1, 3])

    def test_open_move_quantity_and_state(self):
        """
        Test that the moves of those lines get their quantity and their state
        from them
        """
        for origin, quantity, state in (
            ("ou17-reserved", 3, "assigned"),
            ("ou17-done-equal", 4, "assigned"),
            ("ou17-done-more", 8, "assigned"),
            ("ou17-done-less", 6, "partially_available"),
            ("ou17-done-unreserved", 2, "assigned"),
            ("ou17-other-unit", 1, "assigned"),
            ("ou17-partially-available", 100, "partially_available"),
            ("ou17-several-lines", 4, "assigned"),
            ("ou17-empty-line", 0, "confirmed"),
        ):
            move = self._delivery(origin).move_ids
            self.assertEqual(move.quantity, quantity, origin)
            self.assertEqual(move.state, state, origin)

    def test_no_state_tracking(self):
        """
        Test that recomputing the state of a picking in the migration doesn't
        post a tracking message
        """
        delivery = self._delivery("ou17-done-unreserved")
        self.assertEqual(delivery.state, "assigned")
        self.assertFalse(
            delivery.message_ids.tracking_value_ids.filtered(
                lambda tracking: tracking.field_id.name == "state"
                and tracking.new_value_char == "Ready"
            )
        )

    def test_returned_picking(self):
        """
        Test that we correctly link returned pickings to their origin picking
        """
        returned_picking = self.env.ref("stock.outgoing_shipment_main_warehouse1")
        self.assertTrue(returned_picking.return_ids)

    def test_return_location(self):
        """
        Test that we set the default return location for pickings from the warehouse's
        return picking type from v16
        """
        picking_type = self.env.ref("stock.picking_type_in")
        stock_location = self.env.ref("stock.stock_location_stock")
        self.assertEqual(picking_type.default_location_return_id, stock_location)
