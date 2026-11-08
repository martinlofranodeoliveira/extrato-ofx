"""Instala o wheel em ambiente novo e exercita API e CLI fora de src."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import venv


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    wheel = parser.parse_args(argv).wheel.resolve(strict=True)
    sample = (Path(__file__).resolve().parents[1] / "examples" / "cartao.ofx").read_bytes()
    with tempfile.TemporaryDirectory(prefix="ofx-installed-") as temporary:
        work = Path(temporary)
        environment = work / "environment"
        venv.EnvBuilder(with_pip=True).create(environment)
        binaries = environment / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        entry = binaries / ("extrato-ofx.exe" if os.name == "nt" else "extrato-ofx")
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        subprocess.run([str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", str(wheel)], cwd=work, env=env, check=True)
        source = work / "synthetic.ofx"
        source.write_bytes(sample)
        child = '''import json, pathlib, sys
import extrato_ofx as ofx
report = ofx.parse_ofx(pathlib.Path('synthetic.ofx').read_bytes())
assert report['status'] == 'ok' and report['stats']['transactionCount'] == 2
assert report['statements'][0]['totals']['reportedAmountSum'] == '-79.8'
assert 'ofxtools' not in sys.modules and 'markdown_it' not in sys.modules
assert pathlib.Path(ofx.__file__).is_relative_to(pathlib.Path(sys.prefix))
print(json.dumps({name: function(report) for name, function in (
 ('json', ofx.to_json), ('markdown', ofx.to_markdown), ('csv', ofx.to_csv))}))
'''
        api = subprocess.run([str(python), "-I", "-c", child], cwd=work, env=env, capture_output=True, check=True)
        assert not api.stderr
        reference = {key: text.encode("utf-8") for key, text in json.loads(api.stdout).items()}
        def command(*args, raw=None):
            return subprocess.run([str(entry), *args], input=raw, cwd=work, env=env, capture_output=True, timeout=30)
        for fmt in ("json", "markdown", "csv"):
            result = command(str(source), "--format", fmt)
            assert result.returncode == 0 and not result.stderr
            assert result.stdout == reference[fmt], "stdout difere da API instalada"
            target = work / ("result." + fmt)
            published = command(str(source), "--format", fmt, "--output", str(target))
            assert published.returncode == 0 and not published.stdout and not published.stderr
            assert target.read_bytes() == reference[fmt]
            assert command(str(source), "--format", fmt, "--output", str(target)).returncode == 3
            assert target.read_bytes() == reference[fmt]
        for fmt in ("json", "markdown"):
            assert b"\r" not in reference[fmt] and reference[fmt].endswith(b"\n")
        assert reference["csv"].endswith(b"\r\n")
        assert b"\n" not in reference["csv"].replace(b"\r\n", b"")
        rows = list(csv.DictReader(io.StringIO(reference["csv"].decode("utf-8"), newline="")))
        assert [row["amount"] for row in rows] == ["-89.9", "10.1"]
        assert [row["fit_id"] for row in rows] == ["FIC-CARTAO-001", "FIC-CARTAO-002"]
        partial = sample.replace(b"</CCSTMTRS>", b"<EXTENSION>unknown</EXTENSION></CCSTMTRS>")
        result = command("-", raw=partial)
        assert result.returncode == 2 and json.loads(result.stdout)["coverage"]["status"] == "incomplete"
        assert command("-", "--format", "csv", raw=partial).returncode == 3
        assert command("-", "--format", "csv", "--allow-incomplete-csv", raw=partial).returncode == 2
        assert command("--version").stdout.strip() == b"extrato-ofx 1.0.0"
        assert source.read_bytes() == sample
        print(json.dumps({"installedDistribution": True, "outsideSourceTree": True, "runtimeDependency": "defusedxml==0.7.1", "formats": 3, "exactStdoutBytes": True, "exclusiveOutput": True, "incompleteCsvGate": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
