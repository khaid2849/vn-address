import copy
from collections import Counter
from unittest.mock import MagicMock, patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.service.model import call_kw
from odoo.tests import TransactionCase, new_test_user, tagged

from ..hooks import load_snapshot, uninstall_hook

REQUESTS_GET = "odoo.addons.vn_address.models.res_city.requests.get"


@tagged("post_install", "-at_install")
class TestVnAddress(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.snapshot = load_snapshot()
        cls.vn = cls.env.ref("base.vn")
        cls.City = cls.env["res.city"]

    def _vn_cities(self, active_test=True):
        return self.City.with_context(active_test=active_test).search(
            [("country_id", "=", self.vn.id), ("vn_code", "!=", False)]
        )

    def _state(self, code):
        return self.env["res.country.state"].search([("country_id", "=", self.vn.id), ("vn_code", "=", code)])

    def _mock_api(self, provinces, communes):
        def get(url, timeout):
            response = MagicMock()
            response.json.return_value = (
                {"provinces": provinces} if url.endswith("/provinces") else {"communes": communes}
            )
            return response

        return patch(REQUESTS_GET, side_effect=get)

    # ---- data loaded at install ------------------------------------------------------------------
    def test_all_provinces_have_an_administrative_code(self):
        states = self.env["res.country.state"].search([("country_id", "=", self.vn.id)])
        self.assertEqual(len(states), 34)
        codes = states.mapped("vn_code")
        self.assertTrue(all(codes))
        self.assertEqual(set(codes), {p["code"] for p in self.snapshot["provinces"]})

    def test_province_names_follow_the_official_list(self):
        hue = self.env.ref("base.state_vn_VN-26")
        self.assertEqual((hue.name, hue.vn_level), ("Huế", "city"))
        self.assertEqual(self.env.ref("base.state_vn_VN-22").vn_level, "province")

    def test_snapshot_is_loaded_at_install(self):
        cities = self._vn_cities()
        self.assertEqual(len(cities), 3321)
        self.assertEqual(Counter(cities.mapped("vn_level")), {"commune": 2621, "ward": 687, "special_zone": 13})
        self.assertTrue(all(cities.mapped("state_id")))

    # ---- applying a new list ---------------------------------------------------------------------
    def test_apply_creates_updates_archives_and_restores(self):
        manual = self.City.create({"name": "Manual place", "country_id": self.vn.id})
        communes = copy.deepcopy(self.snapshot["communes"])
        removed = communes.pop(0)
        communes[0]["name"] = "Phường Đổi Tên"
        moved_to = "24" if communes[1]["provinceCode"] != "24" else "01"
        communes[1]["provinceCode"] = moved_to
        communes.append({"code": "99999", "name": "Phường Mới", "administrativeLevel": "Phường", "provinceCode": "24"})

        stats = self.City._vn_apply(self.snapshot["provinces"], communes)

        self.assertEqual(stats, {"created": 1, "updated": 2, "archived": 1, "restored": 0})
        by_code = {c.vn_code: c for c in self._vn_cities(active_test=False)}
        self.assertFalse(by_code[removed["code"]].active, "Disappeared communes are archived, not deleted")
        self.assertEqual(by_code[communes[0]["code"]].name, "Phường Đổi Tên")
        self.assertEqual(by_code[communes[1]["code"]].state_id, self._state(moved_to))
        self.assertEqual(by_code["99999"].state_id, self._state("24"))
        self.assertEqual(by_code["99999"].vn_level, "ward")
        self.assertTrue(manual.exists() and manual.active, "Communes created by hand are left alone")

        stats = self.City._vn_apply(self.snapshot["provinces"], self.snapshot["communes"])
        self.assertEqual(stats, {"created": 0, "updated": 2, "archived": 1, "restored": 1})
        self.assertTrue(by_code[removed["code"]].active)

    def test_names_are_cleaned(self):
        names = self._vn_cities().mapped("name") + self.env["res.country.state"].search(
            [("country_id", "=", self.vn.id)]
        ).mapped("name")
        self.assertEqual([n for n in names if n != " ".join(n.split())], [])
        self.assertEqual(self._vn_cities().filtered(lambda c: c.vn_code == "00070").name, "Phường Hoàn Kiếm")

    def test_apply_is_idempotent(self):
        stats = self.City._vn_apply(self.snapshot["provinces"], self.snapshot["communes"])
        self.assertEqual(stats, {"created": 0, "updated": 0, "archived": 0, "restored": 0})

    def test_partial_or_malformed_list_changes_nothing(self):
        before = len(self._vn_cities())
        for communes in (self.snapshot["communes"][:100], [], [{"code": "1"}]):
            with self.assertRaises(UserError):
                self.City._vn_apply(self.snapshot["provinces"], communes)
        for provinces in ([], [{"code": "01"}], ["01"]):
            with self.assertRaises(UserError):
                self.City._vn_apply(provinces, self.snapshot["communes"])
        self.assertEqual(len(self._vn_cities()), before)

    def test_rename_applies_to_every_language(self):
        self.env["res.lang"]._activate_lang("vi_VN")
        city = self._vn_cities().filtered(lambda c: c.vn_code == "00070")
        city.update_field_translations("name", {"vi_VN": "Bản dịch cũ"})
        communes = copy.deepcopy(self.snapshot["communes"])
        next(row for row in communes if row["code"] == "00070")["name"] = "Phường Đổi Tên"

        self.City.with_context(lang="vi_VN")._vn_apply(self.snapshot["provinces"], communes)

        for lang in ("en_US", "vi_VN"):
            self.assertEqual(city.with_context(lang=lang).name, "Phường Đổi Tên")

    # ---- synchronisation from the API ------------------------------------------------------------
    def test_sync_button(self):
        communes = copy.deepcopy(self.snapshot["communes"])
        communes[0]["name"] = "Phường Từ API"
        with self._mock_api(self.snapshot["provinces"], communes) as get:
            # the way the web client calls a list header button (empty id list)
            action = call_kw(self.City, "action_vn_sync", [[]], {})
        self.assertEqual(get.call_count, 2)
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(self._vn_cities().filtered(lambda c: c.vn_code == communes[0]["code"]).name, "Phường Từ API")

    def test_sync_failure_changes_nothing(self):
        with patch(REQUESTS_GET, side_effect=requests.ConnectionError("offline")), self.assertRaises(UserError):
            self.City.action_vn_sync()
        with self._mock_api(self.snapshot["provinces"], {"unexpected": True}), self.assertRaises(UserError):
            self.City.action_vn_sync()
        with patch(REQUESTS_GET, return_value=MagicMock(**{"json.return_value": []})), self.assertRaises(UserError):
            self.City.action_vn_sync()
        self.assertEqual(len(self._vn_cities()), 3321)

    def test_sync_requires_an_administrator(self):
        user = new_test_user(self.env, login="vn_user", groups="base.group_user,base.group_partner_manager")
        with self.assertRaises(AccessError):
            self.City.with_user(user).action_vn_sync()

    # ---- uninstall -------------------------------------------------------------------------------
    def test_uninstall_removes_loaded_units(self):
        manual = self.City.create({"name": "Manual place", "country_id": self.vn.id})
        hoan_kiem = self._vn_cities().filtered(lambda c: c.vn_code == "00070")
        partner = self.env["res.partner"].create(
            {"name": "Customer", "country_id": self.vn.id, "city_id": hoan_kiem.id, "city": hoan_kiem.name}
        )

        uninstall_hook(self.env)

        self.assertFalse(self._vn_cities(active_test=False))
        self.assertTrue(manual.exists(), "Communes created by hand are left alone")
        self.assertFalse(partner.city_id)
        self.assertEqual(partner.city, "Phường Hoàn Kiếm")
