# Segurança e dados locais

O conversor não abre conexões de rede, não autentica contas e não grava a entrada. Os relatórios contêm dados financeiros interpretados; processamento local não os torna anônimos. A CLI usa diagnósticos fixos sem repetir valores ou caminhos privados na saída de erro.

A entrada tem teto de bytes. O parser limita elementos, profundidade e texto por elemento; a interpretação limita extratos e transações; os exportadores limitam bytes UTF-8. Os limites não constituem isolamento do processo ou garantia de um consumo específico de memória. Para arquivos não confiáveis, use também as restrições normais do seu ambiente.

O XML é processado com `defusedxml`, sem DTD, entidades personalizadas ou acesso externo. O SGML não executa código, não resolve entidades externas e recusa conteúdo ambíguo. Namespaces e atributos de elementos não pertencem ao perfil atual.

Para relatar uma falha, use o canal privado de [vulnerabilidades do GitHub](https://github.com/martinlofranodeoliveira/extrato-ofx/security/advisories/new), quando habilitado. Se estiver indisponível, abra uma issue pedindo um canal privado, sem publicar o material sensível. Uma demonstração sintética é suficiente; não inclua extratos, chaves ou dados pessoais.
