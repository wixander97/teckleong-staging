# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import tools
from odoo import api, fields, models


class SaleReport(models.Model):
    _inherit = "sale.report"

    price_unit = fields.Float(string='Unit Price', readonly=True, digits='Product Price')

    def _query(self, with_clause='', fields={}, groupby='', from_clause=''):
        fields['price_unit'] = ", l.price_unit as price_unit"
        groupby += ', l.price_unit'
        return super(SaleReport, self)._query(with_clause, fields, groupby, from_clause)