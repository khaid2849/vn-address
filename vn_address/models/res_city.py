import json
import logging
import re

import requests

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://production.cas.so/address-kit"
TIMEOUT = 30
# Cancel when the source returns fewer communes than this share of those in use:
# a partial answer must never archive half of the country.
MIN_RATIO = 0.9

PROVINCE_LEVELS = {"Tỉnh": "province", "Thành phố Trung ương": "city"}
COMMUNE_LEVELS = {"Xã": "commune", "Phường": "ward", "Đặc khu": "special_zone"}
PROVINCE_KEYS = {"code", "name", "administrativeLevel"}
COMMUNE_KEYS = PROVINCE_KEYS | {"provinceCode"}


def clean_name(name):
    """Collapse stray whitespace: the source has names like 'Phường \\nHoàn Kiếm' or 'Xã  Vĩnh Tường'."""
    return " ".join(name.split())


def short_province_name(name):
    """'Thành phố Hà Nội' -> 'Hà Nội', 'Tỉnh An Giang' -> 'An Giang' (the level is kept in vn_level)."""
    return re.sub(r"^(Tỉnh|Thành phố) ", "", clean_name(name))


class ResCity(models.Model):
    _inherit = "res.city"

    vn_code = fields.Char(
        string="Administrative Code",
        size=5,
        index=True,
        help="Vietnamese administrative unit code (Decision 19/2025/QD-TTg).",
    )
    vn_level = fields.Selection(
        [("commune", "Commune"), ("ward", "Ward"), ("special_zone", "Special Zone")],
        string="Administrative Level",
    )
    vn_decree = fields.Char(string="Resolution")
    active = fields.Boolean(default=True)

    _vn_code_uniq = models.Constraint(
        "unique (country_id, vn_code)",
        "The administrative code must be unique per country.",
    )

    # ---- synchronisation -------------------------------------------------------------------------
    def action_vn_sync(self):
        """List header button (called with the selected ids, possibly none): fetch the latest
        list from AddressKit and apply it."""
        if not self.env.is_system():
            raise AccessError(self.env._("Only administrators can synchronise administrative units."))
        try:
            stats = self._vn_sync()
        except (requests.RequestException, ValueError) as e:
            raise UserError(self.env._("Synchronisation failed, nothing was changed:\n%s", e)) from e
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Administrative units synchronised"),
                "message": self.env._(
                    "%(created)s created, %(updated)s updated, %(archived)s archived, %(restored)s restored.",
                    **stats,
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }

    @api.model
    def _cron_vn_sync(self):
        try:
            self._vn_sync()
        except (requests.RequestException, ValueError, UserError) as e:
            _logger.warning("vn_address: synchronisation failed, nothing was changed: %s", e)

    @api.model
    def _vn_sync(self):
        base = self.env["ir.config_parameter"].sudo().get_str("vn_address.api_url") or DEFAULT_API_URL
        base = base.rstrip("/")
        provinces = self._vn_fetch(f"{base}/latest/provinces", "provinces")
        communes = self._vn_fetch(f"{base}/latest/communes", "communes")
        return self.sudo()._vn_apply(provinces, communes)

    @api.model
    def _vn_fetch(self, url, key):
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        rows = data.get(key) if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"unexpected answer from {url}: no '{key}' list")
        return rows

    @api.model
    def _vn_apply(self, provinces, communes):
        """Apply a full AddressKit list (provinces + communes), matched by administrative code.

        Communes missing from the list are archived, never deleted, so existing addresses keep
        their value. Communes created by hand (without a code) are left alone.

        Names are proper nouns, identical in every language: they are written in en_US and any
        other translation is dropped, whatever the language of the user who runs the sync.
        """
        self = self.with_context(lang="en_US")
        country = self.env.ref("base.vn")
        states = self.env["res.country.state"].search([("country_id", "=", country.id), ("vn_code", "!=", False)])
        state_by_code = {s.vn_code: s for s in states}
        existing = self.with_context(active_test=False).search(
            [("country_id", "=", country.id), ("vn_code", "!=", False)]
        )
        city_by_code = {c.vn_code: c for c in existing}
        other_langs = [code for code, _name in self.env["res.lang"].get_installed() if code != "en_US"]

        self._vn_check(provinces, communes, existing)

        for row in provinces:
            state = state_by_code.get(row["code"])
            if not state:
                _logger.warning("vn_address: unknown province %s %s, skipped", row["code"], row["name"])
                continue
            vals = {
                "name": short_province_name(row["name"]),
                "vn_level": PROVINCE_LEVELS.get(row["administrativeLevel"], False),
            }
            if any(state[k] != v for k, v in vals.items()):
                state.write(vals)

        stats = {"created": 0, "updated": 0, "archived": 0, "restored": 0}
        to_create, seen = [], set()
        for row in communes:
            state = state_by_code.get(row["provinceCode"])
            if not state:
                _logger.warning(
                    "vn_address: commune %s has an unknown province %s, skipped", row["code"], row["provinceCode"]
                )
                continue
            seen.add(row["code"])
            vals = {
                "name": clean_name(row["name"]),
                "vn_level": COMMUNE_LEVELS.get(row["administrativeLevel"], False),
                "vn_decree": row.get("decree") or False,
                "state_id": state.id,
            }
            city = city_by_code.get(row["code"])
            if not city:
                to_create.append(dict(vals, vn_code=row["code"], country_id=country.id))
                continue
            changed = {k: v for k, v in vals.items() if (city.state_id.id if k == "state_id" else city[k]) != v}
            if not city.active:
                changed["active"] = True
                stats["restored"] += 1
            elif changed:
                stats["updated"] += 1
            name = changed.pop("name", None)
            if changed:
                city.write(changed)
            if name:
                city.update_field_translations("name", dict.fromkeys(other_langs, False) | {"en_US": name})
        if to_create:
            self.create(to_create)
            stats["created"] = len(to_create)

        gone = existing.filtered(lambda c: c.active and c.vn_code not in seen)
        if gone:
            gone.write({"active": False})
            stats["archived"] = len(gone)

        self.env["ir.config_parameter"].sudo().set_str(
            "vn_address.last_sync",
            json.dumps(dict(stats, date=fields.Datetime.to_string(fields.Datetime.now()))),
        )
        _logger.info("vn_address: administrative units applied: %s", stats)
        return stats

    @api.model
    def _vn_check(self, provinces, communes, existing):
        for rows, keys in ((provinces, PROVINCE_KEYS), (communes, COMMUNE_KEYS)):
            if not rows or any(not isinstance(row, dict) or not keys <= row.keys() for row in rows):
                raise UserError(self.env._("The administrative unit list is empty or malformed."))
        in_use = len(existing.filtered("active"))
        if in_use and len(communes) < MIN_RATIO * in_use:
            raise UserError(
                self.env._(
                    "The source returned only %(got)s communes while %(in_use)s are in use; "
                    "the synchronisation was cancelled.",
                    got=len(communes),
                    in_use=in_use,
                )
            )
