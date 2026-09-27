"""Tests for src/state.lua (LuaJIT 5.1 transmog domain module).

Runner strategy: use lupa.luajit21 if importable, otherwise fall back to the
system `luajit` binary via subprocess. Run with:  python3 -m pytest tests/test_state.py -q
"""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_LUA = os.path.join(ROOT, "src", "state.lua")

lupa = None
try:  # pragma: no cover - environment dependent
    import lupa.luajit21 as lupa  # noqa: F401
except Exception:
    try:
        import lupa as lupa  # noqa: F401
    except Exception:
        lupa = None

HAVE_LUPA = lupa is not None

if not HAVE_LUPA and shutil.which("luajit") is None:
    pytest.skip("no lupa.luajit21 and no luajit binary available", allow_module_level=True)

CATALOG = {
    "b01": {"appearance_id": "APP_B01", "stats_id": "STAT_B01", "passive_variant_id": "PASS_PEACEKEEPER"},
    "b24": {"appearance_id": "APP_B24", "stats_id": "STAT_B24", "passive_variant_id": "PASS_EXPERIMENTAL"},
    "b24_alt": {"appearance_id": "APP_B24", "stats_id": "STAT_B24", "passive_variant_id": "PASS_UA1"},
    "ce27": {"appearance_id": "APP_CE27", "stats_id": "STAT_CE27", "passive_variant_id": "PASS_SERVANT"},
}
OWNED = ["b01", "b24"]  # authoritative list; b24_alt + ce27 NOT owned


class Runner:
    """Executes a Lua snippet that gets `S` (the state module) in scope."""

    def run(self, code):
        raise NotImplementedError

    def eval_expr(self, expr):
        raise NotImplementedError


LUPA_RUNNER = None
SUBPROC_RUNNER = None


if HAVE_LUPA:

    class LupaRunner(Runner):
        def __init__(self):
            self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)

        def run(self, code):
            self.lua.execute("S = dofile(%r)" % STATE_LUA)
            self.lua.execute(code)

        def eval_expr(self, expr):
            self.lua.execute("S = dofile(%r)" % STATE_LUA)
            return self.lua.execute("return " + expr)

        def eval_snippet(self, code, ret_expr):
            self.lua.execute("S = dofile(%r)" % STATE_LUA)
            self.lua.execute(code)
            return self.lua.execute("return " + ret_expr)


class SubprocRunner(Runner):
    """luajit has no persistent REPL session, so we replay an accumulated
    transcript in one process each call (all test code is deterministic/fast)."""

    def __init__(self):
        self.transcript = []

    def _exec(self):
        full = ("local S = dofile(%r)\n" % STATE_LUA) + "\n".join(self.transcript) + "\n"
        p = subprocess.run(
            ["luajit", "-e", full], capture_output=True, text=True, timeout=30
        )
        if p.returncode != 0:
            raise AssertionError(
                "luajit failed:\nsource:\n%s\nstdout: %s\nstderr: %s"
                % (full, p.stdout, p.stderr)
            )
        return p.stdout

    def run(self, code):
        self.transcript.append(code)
        self._exec()

    def eval_expr(self, expr):
        return self.eval_snippet("", "tostring(%s)" % expr)

    def eval_snippet(self, code, ret_expr):
        """Execute code + return expression without persisting to transcript."""
        sep = ["-- one-shot snippet", code, "print('RESULT=' .. tostring(%s))" % ret_expr]
        self.transcript.extend(sep)
        out = self._exec()
        del self.transcript[-len(sep):]
        idx = out.find("RESULT=")
        if idx == -1:
            raise AssertionError("no result in snippet output: %r" % out)
        return out[idx + len("RESULT="):].rstrip("\n")


def call_once(runner, expr):
    """Like call() but not appended to the transcript (one-shot, huge payloads)."""
    ok, err = runner.eval_snippet(
        "local ok, err = " + expr, 'tostring(ok) .. "|" .. tostring(err or "")'
    ).split("|", 1)
    return ok == "true", (None if ok == "true" else err)


@pytest.fixture(params=["lupa", "subproc"])
def runner(request):
    if request.param == "lupa":
        if not HAVE_LUPA:
            pytest.skip("lupa not available")
        return LupaRunner()
    return SubprocRunner()


def new_state(runner, owned=OWNED, catalog=None):
    catalog = catalog or CATALOG
    runner.run(
        "st = S.reconcile_owned(S.new(), %s, %s)"
        % (lua_table(catalog), lua_list(owned))
    )
    return runner


def lua_list(items):
    return "{" + ", ".join('"%s"' % i for i in items) + "}"


def lua_table(d):
    parts = []
    for k, v in d.items():
        inner = "{appearance_id=%r, stats_id=%r, passive_variant_id=%r}" % (
            v["appearance_id"], v["stats_id"], v["passive_variant_id"])
        parts.append('["%s"] = %s' % (k, inner))
    return "{" + ", ".join(parts) + "}"


def truthy(v):
    """eval_expr returns Lua strings via subprocess ('true'/'false'); normalize."""
    if isinstance(v, str):
        return v.strip() == "true"
    return bool(v)


def call(runner, expr):
    """Return (ok, err) from a Lua call returning `true | nil, err`.
    The call is appended to the persistent transcript (selections must stick)."""
    runner.run("ok, err = %s" % expr)
    ok, err = runner.eval_snippet(
        "", 'tostring(ok) .. "|" .. tostring(err or "")'
    ).split("|", 1)
    return ok == "true", (None if ok == "true" else err)




def call_once(runner, expr):
    """Like call() but NOT appended to the transcript (one-shot / huge payloads)."""
    ok, err = runner.eval_snippet(
        "local ok, err = " + expr, 'tostring(ok) .. "|" .. tostring(err or "")'
    ).split("|", 1)
    return ok == "true", (None if ok == "true" else err)


# ---------------------------------------------------------------------------
# roundtrip
# ---------------------------------------------------------------------------

def test_roundtrip_preserves_everything(runner):
    new_state(runner)
    ok, err = call(runner, "S.select(st, 'APP_B24', 'STAT_B24', 'PASS_EXPERIMENTAL')")
    assert ok, err
    runner.run("st.presets['my ☃ preset'] = {appearance_id='APP_B01', stats_id='STAT_B01', passive_variant_id='PASS_PEACEKEEPER'}")
    runner.run("enc = S.encode(st)")
    enc1 = runner.eval_expr("enc")
    # deterministic
    assert runner.eval_expr("enc == S.encode(st)")
    runner.run("st2 = assert(S.decode(enc))")
    assert runner.eval_expr("st2.schema_version == 1")
    assert runner.eval_expr("st2.requested.appearance_id == 'APP_B24'")
    assert runner.eval_expr("st2.requested.passive_variant_id == 'PASS_EXPERIMENTAL'")
    assert runner.eval_expr("st2.selected ~= nil and st2.selected.stats_id == 'STAT_B24'")
    assert runner.eval_expr("st2.owned.b01 == true and st2.owned.b24 == true")
    assert runner.eval_expr("st2.owned.ce27 == nil")
    assert runner.eval_expr("st2.presets['my ☃ preset'] ~= nil")
    assert runner.eval_expr("S.encode(st2) == enc")


# ---------------------------------------------------------------------------
# ownership
# ---------------------------------------------------------------------------

def test_cross_kit_select_and_rejections(runner):
    new_state(runner)
    # CROSS-KIT: look from b24, stats from b01, exact passive from b24 --
    # independently owned parts must compose; that is the point of transmog
    ok, err = call(runner, "S.select(st, 'APP_B24', 'STAT_B01', 'PASS_EXPERIMENTAL')")
    assert ok, err
    assert truthy(runner.eval_expr(
        "st.requested.appearance_id == 'APP_B24' and st.requested.stats_id == 'STAT_B01'"
        " and st.requested.passive_variant_id == 'PASS_EXPERIMENTAL'"))
    # select alone does not authorize; fresh reconcile activates
    assert truthy(runner.eval_expr("st.selected == nil"))
    runner.run("S.reconcile_owned(st, %s, %s)" % (lua_table(CATALOG), lua_list(OWNED)))
    assert truthy(runner.eval_expr("st.selected.stats_id == 'STAT_B01'"))

    # passive variant exists in catalog but is NOT owned (b24_alt) -> refuse
    ok, err = call(runner, "S.select(st, 'APP_B24', 'STAT_B01', 'PASS_UA1')")
    assert not ok and "passive variant not owned" in err
    # missing passive variant entirely
    ok, err = call(runner, "S.select(st, 'APP_B24', 'STAT_B01', 'PASS_NOPE')")
    assert not ok and "passive variant not owned" in err
    # unowned appearance (ce27 exists in catalog, unowned)
    ok, err = call(runner, "S.select(st, 'APP_CE27', 'STAT_B01', 'PASS_EXPERIMENTAL')")
    assert not ok and "appearance not owned" in err
    # unowned stats
    ok, err = call(runner, "S.select(st, 'APP_B24', 'STAT_CE27', 'PASS_EXPERIMENTAL')")
    assert not ok and "stats not owned" in err
    # unknown ids
    ok, err = call(runner, "S.select(st, 'APP_NOPE', 'STAT_B01', 'PASS_EXPERIMENTAL')")
    assert not ok and "appearance not owned" in err
    # invalid args
    ok, _ = call(runner, "S.select(st, '', 'STAT_B01', 'PASS_EXPERIMENTAL')")
    assert not ok
    ok, _ = call(runner, "S.select(st, 42, 'STAT_B01', 'PASS_EXPERIMENTAL')")
    assert not ok


def test_falsy_owned_grants_nothing(runner):
    # set form with an explicit false must not grant ownership
    runner.run("st = S.reconcile_owned(S.new(), %s, { b01 = false, b24 = true })"
               % lua_table(CATALOG))
    assert truthy(runner.eval_expr("st.owned.b01 == nil and st.owned.b24 == true"))
    ok, err = call(runner, "S.select(st, 'APP_B01', 'STAT_B01', 'PASS_PEACEKEEPER')")
    assert not ok and "appearance not owned" in err
    # same via S.new
    runner.run("st2 = S.new({ catalog = %s, owned = { b01 = false } })" % lua_table(CATALOG))
    assert truthy(runner.eval_expr("next(st2.owned) == nil"))


def test_reconcile_preserves_requested_when_ownership_temporarily_missing(runner):
    new_state(runner)
    assert call(runner, "S.select(st, 'APP_B24', 'STAT_B24', 'PASS_EXPERIMENTAL')")[0]
    runner.run("S.reconcile_owned(st, %s, %s)" % (lua_table(CATALOG), lua_list(OWNED)))
    # ownership lost (e.g. list refresh glitch): reconcile SAME state with
    # empty authoritative list; selected drops, requested kept
    runner.run("S.reconcile_owned(st, %s, {})" % lua_table(CATALOG))
    assert truthy(runner.eval_expr("st.selected == nil"))
    assert truthy(runner.eval_expr(
        "st.requested ~= nil and st.requested.passive_variant_id == 'PASS_EXPERIMENTAL'"))
    # ownership restored: selection re-activates automatically
    runner.run("S.reconcile_owned(st, %s, %s)" % (lua_table(CATALOG), lua_list(OWNED)))
    assert runner.eval_expr("st.selected ~= nil")
    assert runner.eval_expr("st.selected.passive_variant_id == 'PASS_EXPERIMENTAL'")


def test_no_fake_unlocks(runner):
    # owned list containing an id absent from catalog is invalid state
    runner.run("st = S.new()")
    runner.run("st.catalog = %s" % lua_table(CATALOG))
    runner.run("st.owned = { ghost_kit = true }")  # owned id absent from catalog
    ok, err = call(runner, "S.validate(st)")
    assert not ok and "not in catalog" in err
    # reconcile only trusts the supplied list
    new_state(runner, owned=["ce27"])
    ok, err = call(runner, "S.select(st, 'APP_CE27', 'STAT_CE27', 'PASS_SERVANT')")
    assert ok, err


# ---------------------------------------------------------------------------
# validate / encode / decode negatives
# ---------------------------------------------------------------------------

def test_validate_rejects_bad_states(runner):
    new_state(runner)
    runner.run("bad = S.new()")
    runner.run("bad.schema_version = 99")
    assert not call(runner, "S.validate(bad)")[0]
    runner.run("bad.schema_version = 1; bad.catalog = { x = {appearance_id='A', stats_id='S'} }")
    assert not call(runner, "S.validate(bad)")[0]


def test_decode_rejects_corruption_and_unknown_versions(runner, tmp_path):
    new_state(runner)
    good = runner.eval_expr("S.encode(st)")

    def decodes(t):
        runner.run("d_ok, d_err = S.decode(%r)" % t)
        return truthy(runner.eval_expr("d_ok ~= nil"))

    assert decodes(good)
    for bad in [
        "", "garbage\n",
        good.replace("HD2TM 1", "HD2TM 2"),
        good.replace("HD2TM 1", "NOTTM 1"),
        good.replace("K b01", "X b01"),
        good.replace("O b01", "O ghost"),          # owned kit missing from catalog
        good + "O b01\n",                           # duplicate O line
        good + "junkline\n",
    ]:
        assert not decodes(bad), "should reject: %r" % bad

    # malformed percent escapes in labels must be rejected
    for esc in ["bad%zz", "pct%4", "trail%"]:
        bad_p = "\nP " + esc + " APP_B01 STAT_B01 PASS_PEACEKEEPER\n"
        assert not decodes(good + bad_p), "should reject escape %r" % esc
    # valid escapes still work (%25 -> '%')
    assert decodes(good + "\nP 100%25 APP_B01 STAT_B01 PASS_PEACEKEEPER\n")

    runner.run("_, d_err = S.decode(%r)" % good.replace("HD2TM 1", "HD2TM 2"))
    assert "version" in runner.eval_expr("d_err")

    # bounds: unbounded record counts rejected; >1MB input rejected
    assert not decodes("HD2TM 1\n" + ("O x%d\n" * 5000 % tuple(range(5000))))
    big = "HD2TM 1\n" + "".join("O x%d\n" % i for i in range(70000))
    big_path = tmp_path / "big.txt"
    big_path.write_text(big)
    ok, err = call_once(
        runner, "S.decode(assert(io.open(%r, 'rb')):read('*a'))" % str(big_path))
    assert not ok and ("too large" in err or "too many" in err)


def test_encode_returns_nil_err_not_throw(runner):
    new_state(runner)
    runner.run("bad = S.new(); bad.schema_version = 99")
    ok, err = call(runner, "S.encode(bad)")
    assert not ok and err and "schema" in err
    # good state still encodes
    runner.run("enc = S.encode(st)")
    assert truthy(runner.eval_expr("type(enc) == 'string' and #enc > 0"))


# ---------------------------------------------------------------------------
# utf-8 presets
# ---------------------------------------------------------------------------

def test_utf8_preset_labels_roundtrip(runner):
    new_state(runner)
    labels = ["презет", "装備セット", "snow ❄ armor", "plain"]
    for i, lbl in enumerate(labels):
        runner.run(
            "st.presets[%r] = {appearance_id='APP_B01', stats_id='STAT_B01', passive_variant_id='PASS_PEACEKEEPER'}"
            % lbl)
    enc = runner.eval_expr("S.encode(st)")
    # labels can't forge lines: every line must be a known kind
    for line in enc.split("\n"):
        if line:
            assert line.startswith(("HD2TM ", "K ", "O ", "S ", "P "))
    runner.run("st4 = assert(S.decode(%r))" % enc)
    for lbl in labels:
        assert runner.eval_expr("st4.presets[%r] ~= nil" % lbl)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
