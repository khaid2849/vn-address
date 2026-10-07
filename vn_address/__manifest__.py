{
    "name": "Vietnam Administrative Units",
    "summary": "34 provinces and 3,321 communes/wards/special zones after the 2025 reform, "
    "synchronised from the AddressKit API (source: National Statistics Office)",
    "version": "19.0.1.0.0",
    "category": "Localization",
    "license": "LGPL-3",
    "author": "Gout",
    "depends": ["base_address_extended", "contacts"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "data/res_country_data.xml",
        "data/ir_cron.xml",
        "views/res_city_views.xml",
        "views/res_country_state_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
}
