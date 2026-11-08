# Extrato OFX

[![Testes](https://github.com/martinlofranodeoliveira/extrato-ofx/actions/workflows/ci.yml/badge.svg)](https://github.com/martinlofranodeoliveira/extrato-ofx/actions/workflows/ci.yml)
[![Licença MIT](https://img.shields.io/badge/licença-MIT-3b7a57)](LICENSE)

**Converta extratos OFX em dados que você consegue conferir.** Uma biblioteca Python e ferramenta de terminal para extratos bancários e de cartão, com JSON, CSV e Markdown, valores decimais exatos e diagnósticos de duplicatas, correções e campos não interpretados.

O processamento é local: não há cadastro, conexão bancária, telemetria ou envio de extratos. A instalação inicial das dependências requer acesso ao índice de pacotes; a conversão funciona offline.

Um projeto aberto da [LOFRANO TECNOLOGIA](https://lofranotecnologia.com.br).

## Começar

Requer **Python 3.11 ou superior**. Clone o projeto e instale em um ambiente separado:

```bash
git clone https://github.com/martinlofranodeoliveira/extrato-ofx.git
cd extrato-ofx
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .

extrato-ofx examples/banco.ofx --format markdown
extrato-ofx examples/cartao.ofx --format csv --output cartao.csv
```

Os dois arquivos de exemplo são **inteiramente fictícios**, incluindo contas, instituições e lançamentos. Veja [a saída bancária em Markdown](examples/banco-result.md), [o JSON](examples/banco-result.json) e [o CSV do cartão](examples/cartao-result.csv).

Também é possível instalar o wheel da [release](https://github.com/martinlofranodeoliveira/extrato-ofx/releases/latest), depois de conferir `SHA256SUMS.txt`, ou executar `python -m extrato_ofx`. Este projeto não afirma estar publicado no PyPI.

## O que a ferramenta preserva

| Informação | Tratamento |
| --- | --- |
| Conta bancária ou cartão | IDs continuam como texto, com zeros à esquerda |
| Montantes | Token declarado e valor decimal canônico; sem `float` ou arredondamento |
| Datas | Token declarado, precisão, offset numérico e instante UTC |
| Saldos | Saldo contábil e disponível, cada um com sua data |
| FITID repetido | Todas as linhas permanecem; o grupo recebe diagnóstico |
| Correções `REPLACE` / `DELETE` | Registradas sem alterar ou excluir lançamentos |
| Campo fora do perfil | Caminho sinalizado e cobertura incompleta; valor desconhecido omitido |

A soma das linhas é apenas a soma dos registros recebidos, incluindo duplicatas e correções. O leitor não calcula saldo inicial, não reconcilia a conta e não conclui que a janela do arquivo contém todo o histórico. Uma lista ausente também se distingue de uma lista presente e vazia.

## Biblioteca

```python
from pathlib import Path
from extrato_ofx import parse_ofx, to_json, Limits

report = parse_ofx(
    Path("examples/banco.ofx").read_bytes(),
    limits=Limits(max_transactions=2000),
)
print(report["status"])
for statement in report["statements"]:
    for row in statement["transactions"]:
        print(row["fitId"], row["amount"]["value"], row["posted"]["utc"])

# Exportadores devolvem texto; a chamada não grava arquivos.
json_text = to_json(report)
```

`parse_ofx` recebe bytes e não modifica a origem. Falhas de estrutura, perfil ou limites levantam `OfxError`, com código estável. Os relatórios são dicionários Python comuns. Consulte [o formato e seus limites](docs/FORMATO.md) e [o contrato técnico](SPEC.md).

## Saídas e códigos de retorno

```bash
extrato-ofx extrato.ofx --format json --output extrato.json
extrato-ofx - --format markdown < extrato.ofx
extrato-ofx extrato.ofx --max-input-bytes 1048576 --max-transactions 1000
```

`--output` exige um destino novo, com diretório pai existente, e publica o arquivo completo por link exclusivo. Não sobrescreve arquivos existentes. Sem essa opção, o relatório vai para a saída padrão em UTF-8.

| Código | Significado |
| --- | --- |
| `0` | Relatório interpretado pelo perfil, sem avisos ou erros |
| `2` | Relatório válido com diagnósticos ou cobertura incompleta |
| `3` | Falha de argumentos, leitura, estrutura, perfil, orçamento ou escrita |

JSON e Markdown mostram a cobertura. **CSV contém somente as transações interpretadas** e recusa cobertura incompleta por padrão. Confira primeiro o JSON; para aceitar conscientemente essa exportação parcial:

```bash
extrato-ofx extrato.ofx --format csv --allow-incomplete-csv --output linhas-parciais.csv
```

O CSV usa aspas em todos os campos e finais CRLF. Campos textuais com possível fórmula recebem apóstrofo; valores numéricos canônicos permanecem numéricos. A API permite desativar a proteção com `spreadsheet_safe=False`. O JSON preserva os textos interpretados sem esse prefixo. As configurações de importação da sua planilha continuam determinando o tratamento de IDs e datas.

## Perfil suportado

Lê OFX1 SGML e OFX2 XML, nos conjuntos bancário e de cartão. O perfil cobre múltiplas contas, lançamentos liquidados, saldos, status de resposta e os campos opcionais descritos no contrato. SGML aceita folhas sem fechamento; agregados exigem fechamento. A codificação vem do cabeçalho, sem tentativa de adivinhação.

Investimentos, pagamentos agendados, dados pendentes, extensões proprietárias e outros campos podem ficar fora do perfil. Isso produz cobertura incompleta, em vez de uma promessa de compatibilidade universal. XML com namespaces ou atributos de elemento, estruturas ambíguas, DTDs e entidades personalizadas são recusados. Os tetos são ajustáveis dentro de limites fixos; não há leitura ou saída ilimitada.

As datas usam o offset numérico do arquivo. `5.50` representa **cinco horas e meia**, não cinco horas e cinquenta minutos. O rótulo do fuso é informativo. Não se usa o fuso da máquina. Precisões de hora e minuto são compatibilidades documentadas; segundos intercalares e ano zero ficam fora deste perfil.

## Testar e contribuir

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python scripts/check_oracles.py
python scripts/check_public_tree.py
python -m build
python scripts/check_installed.py --wheel dist/extrato_ofx-1.0.0-py3-none-any.whl
```

A comparação opcional usa `ofxtools==1.1.1` em campos comuns de extratos fictícios, com expectativas também escritas à mão. As divergências conhecidas de offset fracionário e versão 221 ficam separadas das concordâncias. Ela não prova conformidade integral com OFX. [Método e resultados](docs/ORACULOS.md).

A CI executa testes e instalação do wheel em Python 3.11–3.14 no Linux e 3.14 no Windows. [Contribuições](CONTRIBUTING.md), [segurança](SECURITY.md) e [licenças das dependências](THIRD_PARTY_NOTICES.md).

## Licença

Código original sob [MIT](LICENSE). Dependência de execução: `defusedxml==0.7.1`, sob PSF-2.0. Não foram incorporados arquivos bancários reais nem código dos parsers usados como referência independente.
