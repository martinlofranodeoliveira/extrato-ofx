# Comparação independente

Todos os nomes, identificadores, valores e lançamentos usados aqui foram inventados. Não são extratos anonimizados nem derivados de uma conta real.

`examples/banco.ofx` é um extrato SGML VERSION 102, codificado em Windows-1252 conforme `ENCODING:USASCII` e `CHARSET:1252`. Tem folhas sem fechamento, conta bancária, acentos, montante com vírgula decimal, dois lançamentos, saldo contábil e saldo disponível. `examples/cartao.ofx` é um extrato de cartão XML VERSION 220 em UTF-8, com folhas fechadas e acentos. Os saldos declarados são dados independentes: não representam uma conciliação com a soma das linhas.

O extra opcional de desenvolvimento fixa **ofxtools==1.1.1**. A biblioteca principal não importa esse pacote. O adaptador original em `scripts/check_oracles.py` chama `OFXTree.parse` sobre bytes em memória e depois `convert`, usando a árvore e os modelos públicos do parser independente. Nenhum código ou arquivo de exemplo do ofxtools foi incorporado.

Execute na raiz do projeto, no ambiente que contém o extra `dev`:

```sh
python scripts/check_oracles.py
python -m unittest discover -s tests -p test_oracle.py -v
```

A comparação projeta somente campos comuns: instituição, categoria da conta, identificadores da conta, moeda, início e fim declarados, tipo e valor de cada lançamento, FITID, instante UTC, nome, memo e os valores e datas dos dois saldos. A contagem de STMTTRN na árvore original também deve concordar com a do modelo convertido. As expectativas desses campos foram escritas à mão antes da comparação; nenhum dos dois parsers gera o resultado esperado do outro.

As variantes mantêm ambos os dialetos e exercitam versões aceitas pelo oráculo, Windows-1252, Latin-1, UTF-8, folhas SGML fechadas ou abertas, bordas com espaços, ponto e vírgula decimais, sinal positivo, `.5`, `1.`, data sem horário, milissegundos e offsets inteiros. Incluem lista presente e vazia e duas contas distintas com os mesmos FITIDs, preservadas sem deduplicação entre contas. Os testes básicos verificam ainda acentos, valores brutos, totais exatos e o marcador de fim exclusivo. Não é uma suíte de validação completa dos schemas OFX, nem prova de conformidade de arquivos arbitrários. Outros testes do projeto cobrem rejeições e limites.

## Divergências deliberadas

Os três casos abaixo aparecem em `knownDivergences`; **não entram em `matchingCases` nem na contagem de concordâncias**. Se o comportamento do oráculo mudar, a verificação falha para exigir revisão explícita.

| Entrada fictícia | Extrato OFX | ofxtools 1.1.1 |
| --- | --- | --- |
| `20261104060000.250[5.5:TEST]` | Fração decimal de hora: UTC 00:30:00.250 | Rejeita a fração de uma casa |
| `20261104060000.250[5.50:TEST]` | Mesmo UTC 00:30:00.250 | Interpreta 50 como minutos e produz UTC 00:10:00.250 |
| XML com `VERSION="221"` | Aceito pelo perfil local | Rejeitado pelo cabeçalho do oráculo |

O rótulo de fuso `TEST` é fictício e informativo. O perfil local trata o número como horas decimais; não consulta um registro de fusos. Ofxparse e libofx também usam fração decimal de hora, enquanto o conversor do ofxtools separa horas e minutos. Esses comportamentos diferentes impedem usar concordância de parsers como definição normativa da data.

## Versão e licença da referência

No pacote 1.1.1, os metadados PyPI e `pyproject.toml` declaram **GPL-3.0-only**, mas o arquivo `LICENSE` contém texto de GPL versão 3 **ou posterior**. Registramos essa divergência sem mudar a licença da referência. O uso aqui é uma ferramenta externa e opcional de desenvolvimento, sem cópia de sua implementação. A licença MIT do código original deste projeto não altera a licença do ofxtools.

Fontes primárias consultadas em 08/11/2026:

- [ofxtools 1.1.1 no PyPI](https://pypi.org/project/ofxtools/1.1.1/): versão, metadados e suporte declarado a SGML e XML.
- [API oficial de parsing](https://ofxtools.readthedocs.io/en/latest/parser.html): árvore intermediária e conversão para modelos.
- [Cabeçalhos na versão 1.1.1](https://github.com/csingley/ofxtools/blob/1.1.1/ofxtools/header.py): versões XML reconhecidas.
- [Conversores da versão 1.1.1](https://github.com/csingley/ofxtools/blob/1.1.1/ofxtools/Types.py): datas, montantes e offsets.
- [Metadados fixados](https://github.com/csingley/ofxtools/blob/1.1.1/pyproject.toml) e [arquivo de licença](https://github.com/csingley/ofxtools/blob/1.1.1/LICENSE): divergência da expressão de licença.
- [FDX OFX Banking 2.3](https://financialdataexchange.org/wp-content/uploads/2025/12/OFX-Banking-Specification-v2.3.pdf), apêndices C.7–C.8: VERSION 221 e separação do schema fiscal.
- [Conversor oficial de datas do libofx](https://github.com/libofx/libofx/blob/master/lib/ofx_utilities.cpp) e [ofxparse 0.21](https://github.com/jseutter/ofxparse/blob/0.21/ofxparse/ofxparse.py): interpretações independentes de frações de hora; não são dependências destes testes.
