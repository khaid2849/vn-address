# Vietnam Administrative Units (`vn_address`)

Adds the commune level of Vietnamese addresses to Odoo 20, as it stands after the 2025 administrative
reform: 34 provinces and 3,321 communes, wards and special zones (Decision 19/2025/QD-TTg), kept up to date
from the [AddressKit](https://addresskit.cas.so/) API (source: National Statistics Office of Vietnam).

## Scope

The module provides **data only**: it does not change the contact form or the way addresses are entered.
How the data is used on forms (address layout, province → commune filtering, autocompletion, default country)
is left to the modules that depend on it.

## Features

- Communes, wards and special zones are `res.city` records (from `base_address_extended`) with a 5-digit
  administrative code (`vn_code`), a level (`vn_level`), the resolution that created them (`vn_decree`) and
  an `active` flag.
- Odoo's 34 Vietnamese provinces get their 2-digit administrative code (`vn_code`) and level (`vn_level`).
- Menu *Contacts › Configuration › Vietnam: Communes / Wards*, with a **Sync from AddressKit** button
  (administrators only). The province list also shows the administrative code and level.
- To pick a commune on the contact form, enable *Enforce Cities* on Vietnam
  (*Contacts › Configuration › Countries*).

## Data and synchronisation

- The data is available right after installation, without internet access, from the bundled snapshot
  `data/addresskit_snapshot.json` (taken on 2026-09-26).
- A synchronisation (the button, or the *Vietnam: synchronise administrative units* scheduled action,
  **disabled by default**, weekly) matches units by administrative code: it creates new units, updates
  names, levels and provinces, **archives** (never deletes) units that disappeared and restores units that
  came back. Communes created by hand (without a code) are never touched.
- Commune names are proper nouns: they are stored once for every language, whatever the language of the
  user who runs the synchronisation.
- Safety net: if the API fails, returns a malformed answer, or returns fewer than 90% of the communes in
  use, the synchronisation is cancelled and nothing is written.
- API URL: `https://production.cas.so/address-kit` by default, can be overridden with the system parameter
  `vn_address.api_url`. Result of the last run: system parameter `vn_address.last_sync`.

## Good to know

- **Province names are replaced by the official short names** from the source, e.g. *Thừa Thiên - Huế*
  becomes *Huế* and *TP Hồ Chí Minh* becomes *Hồ Chí Minh*. Updating the `base` module restores Odoo's
  names until the next synchronisation.
- **Uninstalling** deletes the communes loaded by the module. Contacts keep their address text; only their
  link to the commune is cleared. Communes created by hand are kept.

## Tiếng Việt

Module bổ sung cấp xã / phường / đặc khu (3.321 đơn vị, Quyết định 19/2025/QĐ-TTg) cho địa chỉ trong Odoo 20,
có sẵn dữ liệu ngay khi cài và đồng bộ được từ API AddressKit (nguồn: Cục Thống kê). Xem menu
*Liên hệ › Cấu hình › Việt Nam: Xã / Phường*.

## License

LGPL-3
