# Contribuir

Abra uma issue descrevendo o comportamento esperado, o resultado observado e as versões de Python e Extrato OFX. Use um arquivo mínimo inventado: instituição, conta, FITID, datas, descrições e valores devem ser fictícios. Não envie extratos reais, mesmo com alguns campos ocultados.

Para desenvolver:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python scripts/check_oracles.py
python scripts/check_public_tree.py
python -m build
python scripts/check_installed.py --wheel dist/extrato_ofx-1.0.0-py3-none-any.whl
```

No PowerShell, ative com `.venv\Scripts\Activate.ps1`. Inclua um teste que reproduza o problema e atualize o contrato quando mudar o comportamento público. Para ampliar o perfil OFX, cite a seção da especificação e explique o tratamento de campos desconhecidos, limites e perdas de informação. Não trate uma heurística bancária como regra universal.

Prefira alterações completas e úteis. O código é original: consultar um parser independente para comparar resultados não autoriza copiar sua implementação ou seus exemplos sob outra licença.
