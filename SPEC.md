# Extrato OFX — contrato 1.0

Leitor local de extratos bancários e de cartão, com biblioteca Python, CLI e exportação. O leitor preserva os registros declarados, sem conectar-se ao banco, reconciliar saldos, eliminar duplicatas ou aplicar correções. Todos os exemplos do projeto são fictícios.

## API e representação intermediária

```python
parse_ofx(raw: bytes, *, limits=Limits()) -> dict
parse_document(raw: bytes, *, limits=Limits()) -> ParsedDocument
extract_report(document: ParsedDocument, *, limits=Limits()) -> dict
```

`parse_ofx` coordena transporte e interpretação. Falhas de estrutura, perfil ou orçamento levantam `OfxError(code, message, path=None)` e não devolvem relatório parcial. A CLI imprime apenas um código controlado e uma frase fixa, sem refletir a mensagem ou o caminho da entrada.

`model.py` define dataclasses congeladas:

- `Node(tag: str, text: str, children: tuple[Node, ...])`;
- `Header(dialect: str, version: str, encoding: str)`;
- `ParseStats(nodes: int, max_depth: int, text_characters: int)`;
- `ParsedDocument(header: Header, root: Node, stats: ParseStats)`;
- `Limits`, descrito abaixo.

O relatório público é um dicionário. Os exportadores não o modificam. O texto de folhas é decodificado; a interpretação remove espaços das bordas e preserva espaços e quebras internos. `raw` designa esse token decodificado e aparado, não uma cópia dos bytes originais.

## Orçamentos de recursos

Todos os valores de `Limits` são inteiros positivos exatos; `bool` é recusado. A CLI expõe os nomes com hífens, como `--max-input-bytes`.

| Campo | Padrão | Teto permitido | Unidade |
| --- | ---: | ---: | --- |
| `max_input_bytes` | 8.388.608 | 16.777.216 | Bytes da entrada |
| `max_nodes` | 200.000 | 400.000 | Elementos em todo o documento |
| `max_depth` | 64 | 128 | Profundidade, raiz = 1 |
| `max_statements` | 50 | 200 | Extratos interpretados |
| `max_transactions` | 10.000 | 100.000 | Transações em todos os extratos |
| `max_text_chars` | 4.096 | 65.536 | Caracteres decodificados por folha |
| `max_output_bytes` | 16.777.216 | 33.554.432 | Bytes UTF-8 do relatório |

Espaços usados para formatar agregados não constituem conteúdo de folha. Valores do cabeçalho têm um teto fixo de 4.096 caracteres, independente de `max_text_chars`. Os limites são orçamentos do leitor, não uma sandbox de memória do processo ou do Expat.

## Transporte OFX1 / SGML

O cabeçalho ASCII deve conter uma única ocorrência de cada chave: `OFXHEADER`, `DATA`, `VERSION`, `SECURITY`, `ENCODING`, `CHARSET`, `COMPRESSION`, `OLDFILEUID` e `NEWFILEUID`. Chaves extras e duplicadas são recusadas.

Valores obrigatórios: `OFXHEADER:100`, `DATA:OFXSGML`, `SECURITY:NONE` e `COMPRESSION:NONE`. Versões aceitas: `102`, `103`, `151`, `160`.

| `ENCODING` | `CHARSET` | Codificação usada |
| --- | --- | --- |
| `USASCII` | `1252` | `cp1252` |
| `USASCII` | `ISO-8859-1` ou `8859-1` | `latin-1` |
| `USASCII` | `NONE` | `ascii` estrito |
| `UTF-8` | `NONE` ou `UTF-8` | `utf-8` |

Não há detecção heurística, substituição de caracteres inválidos, suporte a `UNICODE` ou descompressão. O BOM UTF-8 é aceito somente no transporte XML.

Tags SGML são normalizadas para maiúsculas. Folhas conhecidas podem omitir o fechamento; agregados precisam fechá-lo. O scanner mantém um token de antecipação, sem gerar previamente uma lista de todos os tokens. Extensões com texto podem ser inferidas como folhas; extensões com filhos, como agregados. Uma extensão vazia sem fechamento explícito pode ser ambígua e é recusada.

## Transporte OFX2 / XML

São obrigatórias uma declaração XML 1.0 e uma instrução `<?OFX ...?>`. Esta deve conter exatamente `OFXHEADER`, `VERSION`, `SECURITY`, `OLDFILEUID` e `NEWFILEUID`, sem duplicatas. Valores: `OFXHEADER="200"`, `SECURITY="NONE"`; versões `200`, `201`, `202`, `203`, `210`, `211`, `220`, `221`.

XML usa UTF-8 por padrão; aceita também `encoding="US-ASCII"` e BOM UTF-8. Não aceita UTF-16. Tags XML são sensíveis à caixa e precisam estar em maiúsculas. Elementos não podem ter atributos, namespaces ou conteúdo misto. Há uma única raiz `OFX`.

A API pública de `defusedxml==0.7.1` faz a análise incremental com um target próprio. DTDs, entidades personalizadas e referências externas são bloqueadas. As cinco entidades XML predefinidas e referências numéricas válidas são decodificadas. Comentários XML são ignorados; outras instruções de processamento no corpo são recusadas. O parser não acessa rede nem arquivos referidos pela entrada.

O nome da especificação Banking 2.3 não cria uma versão de cabeçalho `230`. Este projeto declara um perfil de leitura; aceitar o cabeçalho não significa implementar todos os módulos da respectiva versão OFX.

## Montantes exatos

```python
parse_amount(text: str) -> {"raw": str, "value": str}
sum_amounts(amounts) -> str
```

O token aparado tem de 1 a 32 caracteres ASCII e obedece a:

```text
[+-]?(?:[0-9]+(?:[.,][0-9]*)?|[.,][0-9]+)
```

Ponto ou vírgula funciona como separador decimal, nunca como agrupador. São recusados expoentes, agrupadores, `NaN`, infinito e espaços internos. A aceitação de `.5`, `1.` e sinal `+` é uma escolha explícita de compatibilidade deste perfil. `1,234` significa `1.234`, e não `1234`.

`value` usa ponto e remove zeros supérfluos e sinal `+`; zero negativo vira `0`. `raw` preserva a grafia decodificada e aparada. Não se presume escala de duas casas. A soma alinha coeficientes inteiros e escalas, sem floats e sem depender do contexto global de `Decimal`.

## Datas e offsets

`parse_date(text)` devolve `raw`, `precision`, `iso`, `utc`, `offsetHours` e `zoneLabel`.

O perfil aceita 8, 10, 12 ou 14 dígitos, mais uma fração opcional de exatamente três dígitos após os segundos. As precisões de 10 e 12 dígitos são uma compatibilidade documentada para omissão à direita. Componentes de horário ausentes valem zero. Sem offset, o instante é GMT/UTC.

O sufixo opcional é `[offset]` ou `[offset:label]`. O offset contém horas decimais, sinal opcional e até duas casas, com valor absoluto máximo 12. Assim, `[0.5]` são 30 minutos e `[0.01]` são 36 segundos; não é a notação `HH.MM`. O label informativo tem de 1 a 32 caracteres de `[A-Za-z0-9_+/-]` e não consulta um registro IANA.

As precisões são `date`, `hour`, `minute`, `second`, `millisecond`. `iso` possui offset explícito; `utc` termina em `Z`. O calendário gregoriano é limitado aos anos 1 a 9999, inclusive após conversão para UTC. Segundo 60 gera `unsupported_leap_second`; não é tratado como um segundo comum. Não há uso do relógio ou do fuso da máquina.

## Relatório público

Todos os índices começam em zero. Ausências opcionais usam `null`.

```text
schemaVersion: 1
status: ok | issues | incomplete
format: {dialect, version, encoding}
institution: {organization, id} | null
signonStatus: {code, severity, message} | null
responses: [{index, kind, transactionId, status, statementIndex}]
statements: [{index, responseIndex, kind, currency, account,
              transactionsProvided, range, ledgerBalance,
              availableBalance, marketingInfo, transactions, totals}]
coverage: {status, uninterpreted, ignoredTransportPaths}
diagnostics: [{severity, code, path, ...localização opcional}]
stats: {nodes, maxDepth, textCharacters,
        responseCount, statementCount, transactionCount}
limits: {campos de Limits em snake_case}
```

`kind` é `bank` ou `credit_card`. O estado `incomplete` tem precedência quando há campos fora do perfil ou nenhum extrato interpretado. Havendo cobertura completa, diagnósticos `warning` ou `error` produzem `issues`; somente diagnósticos informativos permitem `ok`. Cobertura do perfil não comprova cobertura histórica da conta.

`coverage.uninterpreted` contém objetos `{path, tag}` sem os valores das extensões. Uma subárvore desconhecida é registrada pela raiz. Caminhos usam índices de ocorrência da mesma tag. `ignoredTransportPaths` informa campos de transporte conhecidos que foram omitidos. Diagnósticos podem incluir `statementIndex`, `transactionIndex` ou uma lista `records` de pares `{statement, transaction}`.

### Sign-on e respostas

A instituição vem de `SIGNONMSGSRSV1/SONRS/FI`, com `ORG` e `FID` opcionais. Quando há `SONRS`, `STATUS` é obrigatório e seu conteúdo interpretado fica em `signonStatus`; sem sign-on, esse campo é nulo. `DTSERVER`, `LANGUAGE`, `DTPROFUP`, `DTACCTUP`, `USERKEY`, `TSKEYEXPIRE`, `SESSCOOKIE`, `ACCESSKEY` e `INTU.BID` são reconhecidos como transporte, mas seus valores não são exportados.

São interpretadas respostas `BANKMSGSRSV1/STMTTRNRS` e `CREDITCARDMSGSRSV1/CCSTMTTRNRS`. Cada resposta requer `TRNUID` e `STATUS`. O status contém `code`, `severity` e `message`; `CODE` usa dígitos ASCII sem sinal e `SEVERITY` é `INFO`, `WARN` ou `ERROR`. Código não zero ou severidade diferente de `INFO` gera `provider_status`.

Com código zero, o respectivo `STMTRS` ou `CCSTMTRS` é obrigatório; nos demais códigos, é opcional. `CLTCOOKIE` é omitido como transporte. Status de sign-on com problema também gera diagnóstico; seu código, severidade e mensagem são preservados em `signonStatus`, sem exportar a resposta de sign-on inteira.

### Contas, listas e saldos

Cada extrato exige `CURDEF`, uma conta de origem e `LEDGERBAL`. A moeda tem três letras ASCII maiúsculas; o leitor não valida um cadastro ISO nem converte moedas.

`BANKACCTFROM` requer `BANKID`, `ACCTID`, `ACCTTYPE`, aceitando `BRANCHID` e `ACCTKEY` opcionais. `CCACCTFROM` requer `ACCTID`, com `ACCTKEY` opcional. O relatório normaliza ambos para `account` com `bankId`, `branchId`, `accountId`, `accountType`, `accountKey`; campos não aplicáveis ficam nulos.

`ledgerBalance` e `availableBalance` contêm `{amount: Money, asOf: Date}`. O primeiro é obrigatório; o segundo é opcional. `MKTGINFO` é opcional e vira `marketingInfo`. Nenhum saldo inicial é calculado.

`BANKTRANLIST` é opcional. Ausente, produz `transactionsProvided=false`, `range=null`, lista vazia e o aviso `transactions_not_provided`. Presente, exige `DTSTART` e `DTEND`, com início não posterior ao fim em UTC, e admite zero ou mais `STMTTRN`. Nesse caso, `transactionsProvided=true` e `range={start, end, endExclusive:true}`.

`DTEND` é o fim exclusivo da janela de busca declarada. O leitor não filtra transações pela janela: um registro retornado pode ter data de lançamento anterior ao início. Lista vazia e lista ausente permanecem distintas.

### Transações

São obrigatórios `TRNTYPE`, `DTPOSTED`, `TRNAMT` e `FITID`. O objeto interpretado contém:

```text
index, type, posted, amount, fitId, name, memo,
userDate, availableDate, checkNumber, referenceNumber,
serverId, sic, payeeId, correction
```

Os campos opcionais vêm de `NAME`, `MEMO`, `DTUSER`, `DTAVAIL`, `CHECKNUM`, `REFNUM`, `SRVRTID`, `SIC` e `PAYEEID`. IDs são strings aparadas de até 255 caracteres; zeros iniciais e caixa são preservados. IDs, montantes e datas opcionais presentes não podem estar vazios. Singletons conhecidos repetidos são erros.

Tipos conhecidos: `CREDIT`, `DEBIT`, `INT`, `DIV`, `FEE`, `SRVCHG`, `DEP`, `ATM`, `POS`, `XFER`, `CHECK`, `PAYMENT`, `CASH`, `DIRECTDEP`, `DIRECTDEBIT`, `REPEATPMT`, `OTHER`. Um tipo desconhecido é preservado, mas torna a cobertura incompleta. Não se infere o sinal do valor pelo tipo.

`CORRECTFITID` e `CORRECTACTION` devem aparecer juntos. A ação aceita `REPLACE` ou `DELETE`, gerando `correction={targetFitId, action}` e um diagnóstico informativo `correction_declared`. O leitor não procura, modifica ou exclui automaticamente a transação-alvo.

### Duplicatas e totais

O agrupamento de `FITID` usa `(kind, bankId, branchId, accountId, accountType)` como escopo, inclusive entre extratos. `accountKey` não compõe a identidade. Todas as linhas são mantidas e um diagnóstico `duplicate_fitid` identifica os índices do grupo.

Um `conflicting_fitid` adicional é emitido se a moeda do extrato ou o payload interpretado diferir. Montantes canônicos e instantes UTC são comparados sem considerar grafias em `raw`, precisão declarada, labels de fuso ou índices. Campos desconhecidos não são comparados.

`totals.reportedCount` conta todas as linhas e `totals.reportedAmountSum` soma todos os seus valores, incluindo duplicatas e correções. Essa soma não representa uma conciliação ou a diferença entre saldos.

## Exportadores e CLI

```python
to_json(report, *, limits=Limits()) -> str
to_markdown(report, *, limits=Limits()) -> str
to_csv(report, *, limits=Limits(),
       allow_incomplete=False, spreadsheet_safe=True) -> str
```

Todas as saídas são UTF-8 e limitadas durante a construção. JSON preserva o relatório completo, sem floats ou `NaN`. Markdown escapa sintaxe de entrada e apresenta um resumo; o JSON mantém os campos opcionais completos. CSV usa CRLF, todas as células entre aspas e uma linha por transação interpretada. Não contém linhas especiais para extratos vazios ou respostas sem extrato.

CSV com cobertura incompleta é recusado por padrão. `allow_incomplete=True` ou `--allow-incomplete-csv` permite exportar as linhas interpretadas, sem alterar o estado de cobertura. Textos que começam, após espaços, com `=`, `+`, `-` ou `@` recebem um apóstrofo de proteção por padrão. Valores numéricos e índices não recebem esse prefixo. O JSON preserva os textos originais interpretados. Não há promessa de que o Excel reconhecerá automaticamente tipos ou zeros iniciais.

```text
extrato-ofx FILE|- --format json|markdown|csv --output NOVO
```

Sem `--output`, o relatório vai para stdout. `-` é necessário para stdin explícito; caminhos devem apontar para arquivos regulares, não FIFOs ou dispositivos. A leitura usa limite mais um byte para detectar excesso. O arquivo de destino deve ser novo: publicação por temporário, `flush`, `fsync` e link exclusivo, sem sobrescrever destinos existentes.

| Saída | Significado |
| ---: | --- |
| 0 | Relatório `ok`, ajuda ou versão |
| 2 | Relatório válido com `issues` ou `incomplete` |
| 3 | Falha de argumentos, perfil, estrutura, limite ou I/O |

Erros de escrita e pipes fechados são controlados. Diagnósticos da CLI não incluem caminhos da entrada nem valores financeiros. Os próprios relatórios contêm dados financeiros e devem receber o tratamento de privacidade adequado.

## Fontes e verificação

A interpretação foi baseada em fontes primárias:

- [FDX Banking 2.3](https://financialdataexchange.org/wp-content/uploads/2025/12/OFX-Banking-Specification-v2.3.pdf), especialmente §§3.2.3, 3.2.7–9, 11.4.4 e apêndices C.7–8;
- [DTD OFX1.6 no projeto libofx](https://raw.githubusercontent.com/libofx/libofx/master/dtd/ofx160.dtd);
- [API pública do defusedxml 0.7.1](https://raw.githubusercontent.com/tiran/defusedxml/v0.7.1/defusedxml/ElementTree.py).

O código do leitor é original e MIT. `defusedxml==0.7.1` é dependência de execução sob PSF-2.0. `ofxtools==1.1.1` e `markdown-it-py==4.0.0` são ferramentas opcionais de verificação, sem cópia de implementação.

As comparações usam fixtures fictícias e um subconjunto comum de campos. Divergências de offset fracionário e a recusa de `VERSION=221` pelo oráculo são registradas separadamente, sem contabilizá-las como concordâncias. Há testes de montantes exatos, limites, SGML/XML, semântica, CLI e instalação do wheel. O perfil completo e seus limites são os declarados neste contrato, não uma alegação de suporte integral a todos os módulos OFX.
