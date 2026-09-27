#!/usr/bin/env python3
"""Build address-free armor labels from pinned facts and installed localization.

Input localization is a bounded decoded strings-resource snapshot with resource
SHA256 provenance. This tool never reads game memory or changes game files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def clean(text):
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('invalid localized text')
    text = re.sub(r'</?c(?:=[^>]*)?>', '', text)
    return re.sub(r'[\x00-\x1f\x7f]+', ' ', text).strip()


def number(value):
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('non-finite effect value')
    return format(value, '.7g')


def format_clause(modifier, template):
    value, operation = modifier['value'], modifier['type']
    number(value)
    if operation not in (0, 1, 2, 3):
        raise ValueError('unsupported modifier operation')
    if not template:
        operation_text = {0: '= ', 1: '+ ', 2: 'x ', 3: 'duration '}[operation]
        return ('Additional effect has no game description '
                f'({operation_text}{number(value)}).')
    text = clean(template)
    if operation == 2:
        bonus = str(math.floor(abs(value - 1.0) * 100 + 0.5)) + '%'
        sign = '-' if value < 1 else '+'
    elif operation == 3:
        bonus, sign = number(value) + ' seconds', '+'
    else:
        bonus, sign = number(value), '-' if value < 0 else '+'
    return text.replace('#BONUS', bonus).replace('#SIGN', sign)


def lua(value):
    if value is None:
        return 'nil'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        number(value)
        return repr(value)
    if isinstance(value, list):
        return '{' + ','.join(lua(item) for item in value) + '}'
    return '{' + ','.join('[' + lua(key) + ']=' + lua(item)
                          for key, item in value.items()) + '}'


def build(catalog, snapshot, catalog_sha256):
    strings = {int(key): value for key, value in snapshot['strings'].items()}
    origins = {int(key): value for key, value in snapshot['origins'].items()}
    selected_strings, resources, aliases = {}, set(), {}

    def resolve(key, required=True):
        if key == 0 or key not in strings:
            if required:
                raise ValueError(f'missing installed localization {key}')
            return None
        text = clean(strings[key])
        if not text:
            raise ValueError('empty required localization')
        selected_strings[key] = text
        resources.add(origins[key])
        return text

    kits = {}
    for kit in sorted(catalog['kits'].values(), key=lambda row: row['id']):
        if kit['category'] == 0:
            name = resolve(kit['name_cased'], required=False)
            source_key = kit['name_cased'] if name else None
            if name is None:
                name = resolve(kit['name_upper'], required=False)
                if name:
                    source_key = kit['name_upper']
                    aliases[kit['name_cased']] = source_key
                    selected_strings[kit['name_cased']] = name
            kits[kit['id']] = {
                'name': name or 'Unlocalized armor ' + kit['id'].split(':', 1)[1],
                'name_available': name is not None, 'name_loc': kit['name_cased'],
                'name_source_loc': source_key,
                'passive_variant_id': kit['passive_variant_id'],
            }
    passives = {}
    for passive in sorted(catalog['passives'].values(), key=lambda row: row['enum']):
        modifiers, clauses = [], []
        for effect in passive['modifiers']:
            template = resolve(effect['description_loc'], required=False)
            clause = format_clause(effect, template)
            modifiers.append({**effect, 'template': template,
                              'clause': clause, 'description_available': template is not None})
            clauses.append(clause)
        passives[passive['variant_id']] = {
            'name': resolve(passive['name_loc']), 'name_loc': passive['name_loc'],
            'enum': passive['enum'], 'clauses': clauses, 'modifiers': modifiers,
            'stat_modifiers': passive['stat_modifiers'], 'behavior_tag': passive['behavior_tag'],
            'effect_source': 'pinned reference values; live effects not verified',
        }
    source_resources = [row for row in snapshot['resources'] if row['resource'] in resources]
    if {row['resource'] for row in source_resources} != resources:
        raise ValueError('missing localization resource provenance')
    for row in source_resources:
        if not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('invalid localization resource hash')
    return {
        'schema_version': 1, 'language': 'en-US',
        'source': {'catalog_commit': catalog['source_commit'],
                   'catalog_json_sha256': catalog_sha256,
                   'installed_build_id': snapshot['installed_build_id'],
                   'localization_source': 'installed vanilla strings resources',
                   'localization_aliases': aliases,
                   'localization_resources': source_resources},
        'capabilities': {'live_effects_verified': False, 'native_ui_ratings_verified': False,
                         'ownership_source': False},
        'kits': kits, 'passives': passives, 'strings': selected_strings,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=ROOT/'reference/current_catalog.json')
    parser.add_argument('--localization', type=Path, default=ROOT/'.cache/stat-reference/english_snapshot.json')
    parser.add_argument('--json', type=Path, default=ROOT/'reference/armor_display.json')
    parser.add_argument('--lua', type=Path, default=ROOT/'src/catalog_labels.lua')
    args = parser.parse_args()
    raw = args.catalog.read_bytes()
    display = build(json.loads(raw), json.loads(args.localization.read_bytes()), hashlib.sha256(raw).hexdigest())
    args.json.write_text(json.dumps(display, indent=2, ensure_ascii=False) + '\n')
    # Runtime only needs templates and the provenance gate; details stay in the
    # reviewable JSON rather than duplicating the full domain catalog in Lua.
    runtime = {key: display[key] for key in ('schema_version', 'language', 'source', 'capabilities', 'strings')}
    args.lua.write_text('-- Generated by tools/armor_display.py; display fallback only, never ownership.\nreturn ' + lua(runtime) + '\n')
    print(json.dumps({'armor_names': len(display['kits']), 'passive_names': len(display['passives']),
                      'armor_names_resolved': sum(kit['name_available'] for kit in display['kits'].values()),
                      'templates': len(display['strings']), 'localization_resources': len(display['source']['localization_resources'])}))


if __name__ == '__main__':
    main()
