import json

from odoo.tools import file_open


def load_snapshot():
    # Binary mode: json decodes UTF-8 itself, independent of the OS default encoding.
    with file_open("vn_address/data/addresskit_snapshot.json", "rb") as f:
        return json.load(f)


def post_init_hook(env):
    """Load the bundled AddressKit snapshot so the list works without internet."""
    snapshot = load_snapshot()
    env["res.city"]._vn_apply(snapshot["provinces"], snapshot["communes"])


def uninstall_hook(env):
    """Delete the administrative units loaded by the module.

    They are created without an XML id, so Odoo would otherwise leave them behind and a
    reinstall would load them a second time. Partners keep their address text: only the
    link to the commune is cleared.
    """
    env["res.city"].with_context(active_test=False).search(
        [("country_id", "=", env.ref("base.vn").id), ("vn_code", "!=", False)]
    ).unlink()
