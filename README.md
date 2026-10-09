# Filmes em Português → SS IPTV (fontes autorizadas)

Projeto Python para gerar `playlist.m3u` com filmes e documentários **com indícios de idioma português** e **licença aberta identificável** no Internet Archive. A busca consulta metadados de idioma `por`/`Portuguese` e termos como áudio em português, filmes dublados/dublagem brasileira, cinema brasileiro e filmes portugueses; cada item ainda precisa passar pela validação dos metadados, licença e arquivo de vídeo.

> Importante: a marca BoskuFilm não é usada como fonte de streams. O projeto busca vídeos no Internet Archive; só adiciona itens com indícios de português, licença aberta permitida nos metadados e arquivo de vídeo direto. Metadados de idioma podem estar incompletos ou incorretos, então a lista resultante precisa ser conferida.

## Arquivos

- `gerar_m3u.py` — pesquisa filmes em português, verifica licenças/arquivos de vídeo e gera a playlist.
- `catalogo.json` — estado incremental persistente entre execuções.
- `playlist.m3u` — playlist resultante para o SS IPTV.
- `.github/workflows/atualizar.yml` — execução automática a cada 6 horas.
- `tests/` — testes offline das regras de merge e geração M3U.

## Instalação no GitHub

1. Crie um repositório, por exemplo `boskufilm-ssiptv`.
2. Envie todos os arquivos deste ZIP para a raiz do repositório, mantendo `.github/workflows/`.
3. Abra **Settings → Actions → General** e permita que Actions leia e grave conteúdo do repositório.
4. Abra **Actions** e execute `Atualizar playlist M3U` manualmente uma vez.
5. Use o endereço Raw do arquivo `playlist.m3u` no SS IPTV, por exemplo:
   `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPOSITORIO/main/playlist.m3u`

O GitHub Actions usa UTC. O cron `0 */6 * * *` executa a cada seis horas; o GitHub pode atrasar execuções em períodos de alta demanda.

## Política incremental e proteção

- Novos itens são adicionados sem duplicar a mesma URL.
- Itens anteriores permanecem se o link estiver ativo.
- Falhas transitórias de rede não causam remoção: o item é mantido se o estado for desconhecido.
- Um link só é removido por indisponibilidade quando a resposta indicar claramente `404` ou `410`, em duas verificações consecutivas.
- Se a pesquisa falhar, retornar zero resultados inesperadamente ou produzir uma lista vazia, os arquivos anteriores não são substituídos.
- `catalogo.json` e `playlist.m3u` são versionados pelo próprio workflow.

## Licenças consideradas

Por padrão, o script aceita somente URLs de licença reconhecidas como CC0, domínio público/Mark, CC BY e CC BY-SA (versões 2.0, 2.5, 3.0 ou 4.0), além de exigir sinais explícitos de idioma português nos metadados. Não aceita automaticamente CC BY-NC, CC BY-ND, “All rights reserved” nem metadata sem licença. A presença de uma licença na metadata não é garantia jurídica absoluta; confira os termos de cada obra antes de redistribuir.

## Limitações técnicas

O SS IPTV precisa receber URL direta compatível (normalmente MP4/H.264/AAC). Páginas HTML de filmes, manifestos protegidos, links temporários, DRM e vídeos que exigem autenticação não são adicionados. A seleção de arquivos prioriza MP4; outros formatos são ignorados por compatibilidade.

## Teste local

Requer Python 3.11+ e apenas bibliotecas padrão:

```bash
python -m unittest discover -s tests -v
python gerar_m3u.py --max-items 80 --verbose
```

A busca também considera sinais de dublagem em português (por exemplo, “dublado em português”, “dublagem brasileira” e “Portuguese dub”). Isso depende dos metadados publicados: o projeto não analisa a faixa de áudio para confirmar automaticamente a dublagem. A primeira execução pode encontrar poucos itens, pois a filtragem de idioma e licença é conservadora. A documentação do Internet Archive descreve o campo `language` como idioma principal e `licenseurl`/`rights` como metadados de direitos; esses campos são declarações dos remetentes e não uma garantia absoluta de titularidade. Não se deve desativar a validação de direitos apenas para aumentar a quantidade de canais/títulos.
