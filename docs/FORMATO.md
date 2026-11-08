# Entendendo o relatório

O Extrato OFX lê o que o arquivo declara. Ele separa o formato do documento, as respostas recebidas, os extratos e suas transações. O JSON é a saída mais completa; Markdown e CSV são apresentações desses dados.

Para converter um arquivo local:

```sh
extrato-ofx meu-extrato.ofx --format json --output meu-relatorio.json
```

O destino deve ser novo. Para conferir os exemplos fictícios e instalar a ferramenta, consulte o [README](../README.md). O contrato detalhado de implementação está em [SPEC.md](../SPEC.md).

## Estado e cobertura

Observe os dois indicadores no início do JSON:

| Campo | Valor | Interpretação |
| --- | --- | --- |
| `status` | `ok` | Todos os campos financeiros encontrados pertencem ao perfil e não há aviso ou erro semântico |
| `status` | `issues` | O perfil cobre o conteúdo, mas há avisos ou erros, como FITID repetido |
| `status` | `incomplete` | Há conteúdo fora do perfil ou nenhum extrato foi interpretado |
| `coverage.status` | `complete` | Os campos encontrados estão no perfil de leitura |
| `coverage.status` | `incomplete` | Parte do conteúdo não foi interpretada ou nenhum extrato foi reconhecido |

Cobertura completa descreve a interpretação deste arquivo. Ela não comprova que o banco enviou todo o histórico da conta, que o extrato está atualizado ou que os saldos foram conciliados.

Um arquivo pode ser estruturalmente válido e ter cobertura incompleta. Por exemplo, um bloco de investimentos ou um campo bancário adicional pode estar fora do perfil desta versão. O leitor registra a tag e seu caminho em `coverage.uninterpreted`, sem copiar o valor desconhecido. O restante interpretado continua disponível no JSON, com `status="incomplete"`.

Falhas de estrutura ou limites são diferentes: elas levantam `OfxError` e não geram um relatório parcial. No terminal, os códigos de saída são 0 para `ok`, 2 para relatório com `issues`/`incomplete` e 3 para falha operacional. Uma saída 2 ainda pode ter criado o relatório solicitado.

## Organização do JSON

`schemaVersion` vale `1`. Todos os índices começam em zero e campos opcionais ausentes usam `null`.

| Campo | Conteúdo |
| --- | --- |
| `format` | Dialeto `sgml`/`xml`, versão declarada e codificação usada |
| `institution` | Organização e ID declarados no sign-on, ou `null` |
| `signonStatus` | Código, severidade e mensagem do status de sign-on, ou `null` |
| `responses` | Respostas bancárias/cartão com status do provedor e ligação para o extrato |
| `statements` | Contas, moeda, janela, saldos, transações e totais |
| `coverage` | Cobertura do perfil, campos não interpretados e transporte omitido |
| `diagnostics` | Códigos informativos, avisos e erros semânticos, com localização |
| `stats` | Contagens de elementos, profundidade, texto, respostas, extratos e transações |
| `limits` | Orçamentos usados na leitura, com nomes em `snake_case` |

Cada resposta contém `index`, `kind`, `transactionId`, `status` e `statementIndex`. O status do provedor possui `code`, `severity` e `message`; a mesma estrutura aparece em `signonStatus` quando o arquivo contém sign-on. O código é mantido como string. Uma resposta de erro pode não conter extrato, deixando `statementIndex=null`; isso não significa uma conta sem movimento.

Os diagnósticos contêm `severity`, `code` e `path`. Alguns incluem `statementIndex`, `transactionIndex` ou `records` com os pares de índices envolvidos. Os caminhos usam índices de ocorrência da mesma tag, como `/OFX/BANKMSGSRSV1[0]/STMTTRNRS[1]`.

Campos conhecidos de sessão, como `USERKEY` e `SESSCOOKIE`, são omitidos. Seus caminhos aparecem em `coverage.ignoredTransportPaths`. O relatório continua contendo dados financeiros — conta, valores, nomes e descrições — e não é uma versão anônima do extrato.

## Montantes são strings exatas

Este recorte mostra a representação de um valor:

```json
{
  "raw": "-10,2500",
  "value": "-10.25"
}
```

`raw` é o token depois da decodificação do arquivo e da remoção de espaços nas bordas. Não é uma cópia byte a byte da origem: entidades XML são decodificadas e o parser XML pode normalizar quebras de linha conforme XML 1.0.

`value` é a forma decimal canônica, com ponto, sem zeros desnecessários nem sinal `+`. Zero negativo vira `"0"`. O cálculo usa coeficientes inteiros e escalas; não usa ponto flutuante nem o contexto global de `Decimal`.

A gramática aceita sinal opcional e ponto **ou** vírgula decimal, com até 32 caracteres no token aparado. Não há separador de milhar nem limite artificial de duas casas.

| Entrada | `value` | Motivo |
| --- | --- | --- |
| `+0001,2300` | `1.23` | Vírgula decimal, zeros e sinal normalizados |
| `1,234` | `1.234` | A vírgula não significa milhar |
| `.5` | `0.5` | Compatibilidade explícita deste perfil |
| `1.` | `1` | Compatibilidade explícita deste perfil |
| `-0.00` | `0` | Zero canônico |
| `1,234.56` | Erro | Dois separadores / agrupamento não aceito |
| `1e3` | Erro | Notação exponencial fora do perfil |

O código de moeda do extrato é uma string de três letras maiúsculas. Não há conversão cambial nem consulta a um cadastro de moedas.

## Datas, precisão e fuso

Exemplo de data interpretada:

```json
{
  "raw": "20261018153000[-3:BRT]",
  "precision": "second",
  "iso": "2026-10-18T15:30:00-03:00",
  "utc": "2026-10-18T18:30:00Z",
  "offsetHours": "-3",
  "zoneLabel": "BRT"
}
```

São aceitos `YYYYMMDD`, `YYYYMMDDHH`, `YYYYMMDDHHMM`, `YYYYMMDDHHMMSS` e, depois dos segundos, uma fração de exatamente três dígitos. As precisões de hora e minuto são uma compatibilidade explícita para omissão à direita. O leitor preenche os componentes de horário ausentes com zero. Uma data sem offset usa GMT/UTC, não o fuso configurado no computador.

Os valores de `precision` são `date`, `hour`, `minute`, `second` e `millisecond`. A precisão declarada permanece disponível mesmo quando duas grafias representam o mesmo instante.

O offset é uma quantidade de **horas decimais**, não a notação `HH.MM`:

| Sufixo | Deslocamento |
| --- | --- |
| `[-3:BRT]` | UTC menos três horas; `BRT` é apenas um label |
| `[0.5]` | UTC mais trinta minutos |
| `[0.01]` | UTC mais trinta e seis segundos |
| `[5.5]` | UTC mais cinco horas e trinta minutos |

O valor absoluto máximo é 12 e são aceitas até duas casas decimais no offset. Labels informativos não alteram o deslocamento e não consultam regras de horário de verão. A conversão pode produzir um offset ISO que inclua segundos.

Ano zero, calendários inválidos, precisão só de ano/mês e conversão UTC fora dos anos 1–9999 são recusados. Segundo 60 recebe `unsupported_leap_second`: esta versão não representa segundos intercalares.

## Contas, janela e saldos

`statements` contém um objeto por extrato reconhecido. `kind` é `bank` ou `credit_card`. `account` possui:

```text
bankId, branchId, accountId, accountType, accountKey
```

IDs são texto: `"000001"` mantém os zeros iniciais. Campos não aplicáveis, como `bankId` em cartão, ficam nulos. O leitor não transforma esses identificadores em números.

`ledgerBalance` e `availableBalance` possuem `amount` e `asOf`. O saldo contábil é obrigatório; o disponível é opcional. O leitor não deriva um saldo inicial da soma dos lançamentos.

A presença de `BANKTRANLIST` é indicada separadamente:

| Conteúdo de origem | `transactionsProvided` | `range` | `transactions` |
| --- | --- | --- | --- |
| Lista ausente | `false` | `null` | `[]`, com aviso `transactions_not_provided` |
| Lista presente sem linhas | `true` | Início e fim declarados | `[]` |
| Lista presente com linhas | `true` | Início e fim declarados | Todas as linhas interpretadas |

A janela possui `start`, `end` e `endExclusive=true`. Ela vem de `DTSTART`/`DTEND` e descreve a busca declarada pelo provedor. O leitor confere que início não seja posterior ao fim, comparando instantes UTC, mas não elimina linhas com `DTPOSTED` fora da janela. Um lançamento adicionado depois pode ter data anterior ao início.

## Transações, correções e duplicatas

Cada transação conserva `index`, `type`, `posted`, `amount` e `fitId`, além dos opcionais:

```text
name, memo, userDate, availableDate, checkNumber,
referenceNumber, serverId, sic, payeeId, correction
```

O sinal vem de `TRNAMT`. O leitor não troca sinais com base em nomes como `DEBIT` ou `CREDIT`. Tipos desconhecidos são preservados, mas tornam a cobertura incompleta.

`CORRECTFITID` e `CORRECTACTION` precisam aparecer juntos. Quando presentes, formam, por exemplo:

```json
{
  "targetFitId": "FICTICIO-ANTERIOR-001",
  "action": "REPLACE"
}
```

As ações aceitas são `REPLACE` e `DELETE`. Elas geram o diagnóstico informativo `correction_declared`, mas não substituem nem removem linhas. A transação-alvo pode estar em outro arquivo; o leitor não a procura nem decide uma reconciliação.

`FITID` é comparado dentro do escopo da conta, considerando tipo de extrato, banco, agência, conta e tipo de conta. A comparação é sensível à caixa e atravessa os extratos do mesmo arquivo. `accountKey` não muda esse escopo.

Um grupo repetido gera `duplicate_fitid` e mantém todas as linhas. Se a moeda ou os campos interpretados diferirem, recebe também `conflicting_fitid`. A comparação usa valores canônicos e instantes UTC: `1,00` e `1.0`, ou duas datas equivalentes com offsets diferentes, não criam conflito apenas por sua grafia. Campos desconhecidos não são comparados.

`totals.reportedCount` conta as linhas reportadas. `totals.reportedAmountSum` soma todas elas, inclusive duplicatas e correções. Essa soma não é o saldo nem um resultado já reconciliado.

## Escolhendo JSON, Markdown ou CSV

**JSON** inclui campos opcionais, status, cobertura e diagnósticos. É a melhor opção para integração e inspeção completa do perfil.

**Markdown** apresenta contas, janela, saldos, transações e diagnósticos. Nomes, memos e demais textos são escapados para não virarem HTML ou instruções de Markdown. O JSON conserva os metadados completos interpretados.

**CSV** possui uma linha por transação, com células entre aspas e final de linha CRLF. A conta, a moeda, o estado e a cobertura acompanham cada linha. Extratos sem transações e respostas sem extrato não geram linhas especiais; use JSON para conservar esses casos e os diagnósticos completos.

Por padrão, cobertura incompleta impede a exportação CSV. Para aceitar conscientemente apenas as linhas interpretadas:

```sh
extrato-ofx meu-extrato.ofx --format csv --allow-incomplete-csv --output linhas-parciais.csv
```

Isso não altera a cobertura nem o código de saída 2. Na biblioteca, use `to_csv(report, allow_incomplete=True)`.

Textos cujo primeiro caractere após espaços seja `=`, `+`, `-` ou `@` recebem um apóstrofo de proteção para planilhas. Montantes canônicos e índices permanecem numéricos. O JSON preserva o texto interpretado sem esse prefixo. A opção de biblioteca `spreadsheet_safe=False` desativa a proteção explicitamente. O comportamento de importação e de zeros iniciais depende do aplicativo de planilhas; aspas em CSV não obrigam o Excel a usar um tipo específico.

## Codificações e limites

No transporte SGML, `USASCII/1252` usa Windows-1252; `USASCII/ISO-8859-1` e `USASCII/8859-1` usam Latin-1; `USASCII/NONE` exige ASCII estrito; `UTF-8/NONE` e `UTF-8/UTF-8` usam UTF-8. No XML, aceita-se UTF-8 ou US-ASCII. Não há tentativa silenciosa de adivinhar codificação ou substituir bytes inválidos.

O padrão permite 8 MiB de entrada, 200.000 elementos, profundidade 64, 50 extratos, 10.000 transações, 4.096 caracteres decodificados por folha e 16 MiB de saída UTF-8. Os tetos configuráveis são, respectivamente, 16 MiB, 400.000, 128, 200, 100.000, 65.536 e 32 MiB. Valores do cabeçalho têm um teto fixo de 4.096 caracteres, independente do limite por folha. Consulte a tabela de [SPEC.md](../SPEC.md) para os nomes exatos.

Aumentar um limite não amplia o perfil OFX aceito. Estruturas desconhecidas continuam marcadas como incompletas; estruturas ambíguas ou inseguras continuam sendo recusadas. As recusas a DTDs, entidades externas, namespaces e atributos fazem parte do perfil desta versão.
