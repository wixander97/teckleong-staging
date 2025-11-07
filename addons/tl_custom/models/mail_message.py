# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re
from collections import defaultdict

from binascii import Error as binascii_error

from odoo import _, api, Command, fields, models, modules, tools
from odoo.exceptions import AccessError
from odoo.osv import expression
from odoo.tools.misc import clean_context

_logger = logging.getLogger(__name__)
_image_dataurl = re.compile(r'(data:image/[a-z]+?);base64,([a-z0-9+/\n]{3,}=*)\n*([\'"])(?: data-filename="([^"]*)")?', re.I)


class Message(models.Model):
    _inherit = 'mail.message'

    email_cc = fields.Char('Cc')