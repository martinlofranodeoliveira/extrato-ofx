# Extrato OFX

Resumo dos registros declarados no arquivo. Nenhum saldo inicial foi deduzido; correções e duplicatas permanecem no resultado.

Estado: **ok** · Cobertura do perfil: **complete**

Formato: sgml / 102 · Codificação: cp1252

Instituição: Banco Fictício Exemplo · ID: FICTICIO\-001

Status de sessão: 0 / INFO · —

Resposta 0: 0 / INFO · —

## Extrato 1 — bank

Conta: CONTA\-FICTICIA\-001 · Banco: 000000001 · Agência: 0001 · Tipo: CHECKING · Moeda: BRL

Janela solicitada: 2026\-11\-01T00\:00\:00\+00\:00 até 2026\-12\-01T00\:00\:00\+00\:00, fim exclusivo. Ela não comprova o histórico completo da conta.

Saldo contábil: 2474\.5 em 2026\-11\-05T18\:00\:00\-03\:00.

Saldo disponível: 2400\.25 em 2026\-11\-05T18\:00\:00\-03\:00.

Linhas declaradas: 2 · Soma das linhas: 1474\.5. Esta soma inclui correções e duplicatas; não é conciliação de saldo.

| Data declarada | Tipo | Valor | FITID | Nome / memo | Correção |
| --- | --- | --- | --- | --- | --- |
| 20261102093000\.125\[\-3\:BRT\] | CREDIT | 1500\.25 | FIC\-BANCO\-001 | Depósito fictício \/ Exemplo sem vínculo bancário | — |
| 20261103121500\[\-3\:BRT\] | DEBIT | \-25\.75 | FIC\-BANCO\-002 | Café de demonstração \/ Pagamento fictício | — |

## Diagnósticos

Nenhum diagnóstico neste perfil.


O JSON contém os campos opcionais e metadados completos interpretados por este leitor. Este relatório contém dados financeiros; trate-o como privado.
