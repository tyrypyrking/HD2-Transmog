"""Readable fallback facts preserve current exact effects without claiming ownership."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('armor_display', ROOT/'tools/armor_display.py')
DISPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DISPLAY)


def test_all_records_are_preserved_with_explicit_missing_names_and_provenance():
    facts = json.loads((ROOT/'reference/armor_display.json').read_text())
    assert len(facts['kits']) == 135
    assert len(facts['passives']) == 32
    assert sum(kit['name_available'] for kit in facts['kits'].values()) == 127
    assert len(facts['source']['localization_aliases']) == 8
    assert len(facts['source']['localization_resources']) == 1
    assert len(facts['source']['localization_resources'][0]['sha256']) == 64
    assert not facts['capabilities']['live_effects_verified']
    assert not facts['capabilities']['native_ui_ratings_verified']
    assert not facts['capabilities']['ownership_source']
    for kit in facts['kits'].values():
        if not kit['name_available']:
            assert kit['name'].startswith('Unlocalized armor ')
            assert str(kit['name_loc']) not in facts['strings']


def test_native_display_clauses_do_not_replace_different_internal_stat_values():
    facts = json.loads((ROOT/'reference/armor_display.json').read_text())
    gunslinger = next(p for p in facts['passives'].values() if p['name'] == 'GUNSLINGER')
    assert '40%' in gunslinger['clauses'][0]
    assert abs(gunslinger['stat_modifiers'][0]['mul_value'] - 1.6) < 1e-6
    padding = next(p for p in facts['passives'].values() if p['name'] == 'EXTRA PADDING')
    assert padding['modifiers'][0]['value'] == 1.0
    assert '50' not in padding['clauses'][0]  # No invented armor-rating conversion.
    for passive in facts['passives'].values():
        assert len(passive['clauses']) == len(passive['modifiers'])
        assert all('<c=' not in clause and '#BONUS' not in clause and '#SIGN' not in clause
                   for clause in passive['clauses'])
        for modifier in passive['modifiers']:
            if not modifier['description_available']:
                assert 'no game description' in modifier['clause']


def test_percent_formatting_handles_current_float_precision_without_strength_drift():
    assert DISPLAY.format_clause({'type': 2, 'value': 0.699999988079071},
                                 'Resistance <c=#COLOR>#BONUS</c>.') == 'Resistance 30%.'
    assert DISPLAY.format_clause({'type': 2, 'value': 0.05000000074505806},
                                 'Resistance #BONUS.') == 'Resistance 95%.'
