from odoo import fields, models


class ResCountryState(models.Model):
    _inherit = "res.country.state"

    vn_code = fields.Char(
        string="Administrative Code",
        size=2,
        index=True,
        help="Vietnamese administrative unit code (Decision 19/2025/QD-TTg).",
    )
    vn_level = fields.Selection(
        [("province", "Province"), ("city", "Centrally-run City")],
        string="Administrative Level",
    )
