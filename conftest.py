"""Fixture globali di pytest. I test che caricano allegati non devono
sporcare media/ del progetto: ogni test scrive in una cartella temporanea."""

import pytest


@pytest.fixture(autouse=True)
def _media_temporanea(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / 'media'
