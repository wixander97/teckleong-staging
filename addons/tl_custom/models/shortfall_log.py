# -*- coding: utf-8 -*-
from odoo import models, fields


class ShortfallLog(models.Model):
    _name = "shortfall.log"
    _description = "Shortfall Log"
    _rec_name = "order_id"

    order_id = fields.Many2one('sale.order', string='Sale Order')
    details = fields.Text()
