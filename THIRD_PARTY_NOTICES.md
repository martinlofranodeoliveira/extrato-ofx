# Origem e dependências

O parser, a interpretação, os tipos de montantes/datas e os exportadores deste projeto são código original sob a licença MIT deste repositório.

O publicador exclusivo de arquivos e o tratamento de saída padrão da CLI foram adaptados de [Recorrência Civil](https://github.com/martinlofranodeoliveira/recorrencia-civil), também MIT, copyright 2026 Contribuidores da LOFRANO TECNOLOGIA. A licença e essa atribuição são preservadas neste projeto.

## Execução

- **defusedxml 0.7.1** — PSF-2.0. Instalado como dependência, sem código vendorizado. [Pacote](https://pypi.org/project/defusedxml/0.7.1/), [licença da versão](https://github.com/tiran/defusedxml/blob/v0.7.1/LICENSE).
- **Python / Expat** — fornecidos pelo ambiente Python do usuário, com suas respectivas licenças. O limite global de bytes atua antes da análise; callbacks de profundidade/texto não são uma sandbox para as alocações nativas do Expat.

## Ferramentas opcionais de desenvolvimento

- **ofxtools 1.1.1** — utilizado exclusivamente como comparação independente em arquivos fictícios; não é importado pela biblioteca ou CLI. Seus metadados declaram GPL-3.0-only e o arquivo LICENSE contém a redação GPLv3 ou posterior. Registramos essa diferença sem relicenciar a ferramenta. Não há cópia de seu código ou de seus exemplos. [Pacote](https://pypi.org/project/ofxtools/1.1.1/), [origem e licença](https://github.com/csingley/ofxtools/tree/1.1.1).
- **markdown-it-py 4.0.0** — MIT; interpreta a saída Markdown nos testes de escape. Dependência transitiva `mdurl`, MIT. [Pacote](https://pypi.org/project/markdown-it-py/4.0.0/).
- **build 1.5.0** — MIT; criação das distribuições. Suas dependências são instaladas pelo gerenciador de pacotes.
- **setuptools 84.2.1** — MIT; backend de build, instalado no ambiente isolado de construção.

Não há fontes, imagens ou amostras bancárias de terceiros no produto. Todos os exemplos OFX e resultados versionados foram inventados para este projeto.

## Referências de formato

[FDX Banking 2.3](https://financialdataexchange.org/wp-content/uploads/2025/12/OFX-Banking-Specification-v2.3.pdf) e [DTD do libofx](https://github.com/libofx/libofx/blob/master/dtd/ofx160.dtd) foram consultados para regras e nomes de campos. A publicação não redistribui esses documentos e não declara certificação OFX.
