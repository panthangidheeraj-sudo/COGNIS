#!/usr/bin/env python3
"""Start the API on recorded fixtures (no network): lets you click through the frontend in live mode offline.

    python scripts/serve_offline.py        # then in the project root: npm run dev:live
"""
from __future__ import annotations

from _bootstrap import bootstrap


def main() -> None:
    bootstrap(quiet=True)
    import uvicorn

    from app.api.main import create_app
    from app.api.services import Services
    from app.config import get_settings, override_settings
    from app.providers.fake_provider import FakeProvider
    from app.storage.db import Database
    from app.testing.fixtures import FixtureNetwork, verified_site

    settings = get_settings().model_copy(update={"llm_provider": "fake", "brreg_account_copies_min_interval_seconds": 0})
    override_settings(settings)
    net = FixtureNetwork()
    net.load_brreg_probes()
    net.add_site("autobjorn.no", verified_site("AUTOBJØRN A/S", "810359862", jobs=["Bilselger", "Mekaniker"]))
    services = Services(settings, db=Database(":memory:"), transport=net.transport(), provider=FakeProvider(), use_provider=True)
    uvicorn.run(create_app(services), host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
