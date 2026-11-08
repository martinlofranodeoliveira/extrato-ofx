"""Confere apenas arquivos rastreados, sem ler configurações da máquina."""
from pathlib import Path
import re
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    count = 0
    forbidden = [r"/(?:home|Users)/[A-Za-z0-9_.-]+/", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
                 r"(?:gh[pousr]|github_pat)_" + r"[A-Za-z0-9_]{20,}", r"AIza" + r"[A-Za-z0-9_-]{30,}"]
    for encoded in files:
        if not encoded:
            continue
        relative = encoded.decode("utf-8")
        path = root / relative
        assert not path.is_symlink(), "Link simbólico rastreado"
        assert not set(Path(relative).parts) & {".venv", ".git", "__pycache__", "local"}, "Arquivo local rastreado"
        assert not path.name.startswith(".env"), "Arquivo de ambiente rastreado"
        raw = path.read_bytes()
        assert len(raw) <= 2 * 1024 * 1024, "Arquivo público excessivo"
        text = raw.decode("cp1252" if path.name == "banco.ofx" else "utf-8")
        assert not any(re.search(pattern, text) for pattern in forbidden), "Conteúdo privado detectado"
        count += 1
    assert count >= 20, "Árvore pública incompleta"
    print(f"Árvore pública conferida: {count} arquivos rastreados; nenhum arquivo local ou segredo reconhecível.")


if __name__ == "__main__":
    main()
