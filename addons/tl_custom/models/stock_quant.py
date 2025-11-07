# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging

from psycopg2 import Error, OperationalError

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.osv import expression
from odoo.tools.float_utils import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    width = fields.Float('Width', related='product_id.width')
    length = fields.Float('Length', related='product_id.length')
    kg = fields.Float('Kg', related='product_id.kg')

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None):
        if self._context.get('is_jo'):

            product_ids_parent_product_ids = self._context.get('product_ids_parent_product_ids')[0][2]

            domain += [('location_id', 'like', self._context.get('warehouse_code')), ('quantity', '>', 0), '|', ('product_id.parent_product_id', 'in', product_ids_parent_product_ids), ('product_id', 'in', product_ids_parent_product_ids)]

        return super(StockQuant, self).search_read(domain=domain, fields=fields, offset=offset, limit=limit, order=order)

    def name_get(self):
        stock_list = []

        for record in self:
            name = ''

            if record.product_id:
                if record.product_id.default_code:
                    name += '[' + record.product_id.default_code + ']'

                name += record.product_id.name

            if record.lot_id:
                name += '(' + record.lot_id.name + ')'

            stock_list.append((record.id, name))

        return stock_list

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        domain = []
        if name:
            domain = ['|', '|', ('product_id.default_code', operator, name), ('product_id.name', operator, name), ('lot_id.name', operator, name)]
        return self._search(expression.AND([domain, args]), limit=limit, access_rights_uid=name_get_uid)