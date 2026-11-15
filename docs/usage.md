# Uso

## Assistente (recomendado)

Para quem já tem os GeoTIFFs anuais da Coleção 11:

```powershell
python run_local.py
```

O assistente pergunta a pasta dos dados, o padrão dos nomes, a pasta de saída e o período.
Antes de processar ele executa a verificação (`preflight`) e mostra um relatório com:

- anos encontrados e anos faltantes no período pedido;
- tamanho de cada arquivo e classes amostradas;
- dtype, bandas, NoData, CRS e consistência da grade entre anos;
- arquivos vazios, truncados ou ilegíveis;
- avisos sobre overviews (nunca usados pelo pipeline) e classes desconhecidas.

Se faltarem anos, ele avisa e pergunta se deve continuar com os disponíveis. Com menos de
6 anos, aborta. Se houver erro bloqueante, nada é processado.

Opções do assistente:

| Opção | Descrição |
| --- | --- |
| `--input-dir` | Pasta dos rasters (obrigatória no modo `--yes`) |
| `--output-dir` | Pasta de saída (padrão `outputs`) |
| `--start`, `--end` | Período da análise |
| `--filename-pattern` | Padrão dos nomes (padrão `mapbiomas_col11_{year}.tif`) |
| `--yes` | Não faz perguntas |
| `--deep-check` | Lê todos os blocos na verificação (mais lento, mais confiável) |
| `--no-secondary` | Não gera idade/frequência |
| `--window-start`, `--max-windows` | Amostragem de janelas para teste |
| `--sample-blocks` | Blocos por arquivo no QA (padrão 200; 0 = tudo) |
| `--force` | Ignora checkpoints |
| `--no-progress` | Sem barras de progresso |

## Subcomandos

Todos aceitam as mesmas opções de configuração. O `--config` pode ser combinado com
qualquer opção de linha de comando; a opção explícita vence o arquivo.

| Comando | Função |
| --- | --- |
| `audit` | Audita os rasters e grava `reports/audit_report.{json,md}` |
| `preflight` | Validação pré-processamento (bloqueia em caso de erro) |
| `deforestation` | Gera a série anual de desmatamento/vegetação secundária |
| `secondary` | Gera idade da vegetação secundária e frequência de desmatamento |
| `qa` | Confere consistência dos produtos gerados |
| `run` | Executa uma sequência de etapas (`--steps`) |

Exemplos:

```powershell
python -m mapbiomas_local preflight --config configs\example.toml --deep
python -m mapbiomas_local deforestation --config configs\example.toml
python -m mapbiomas_local secondary --config configs\example.toml
python -m mapbiomas_local qa --config configs\example.toml --sample-blocks 200
python -m mapbiomas_local run --config configs\example.toml --steps audit deforestation secondary
```

## Opções de linha de comando

### Caminhos e recorte

| Opção | Padrão | Descrição |
| --- | --- | --- |
| `--input-dir` | — | Diretório dos rasters anuais |
| `--filename-pattern` | `mapbiomas_col11_{year}.tif` | Precisa conter `{year}` |
| `--output-dir` | — | Diretório de saída |
| `--years` | todos | Subconjunto explícito de anos |
| `--deforestation-start` | — | Primeiro ano da série |
| `--deforestation-end` | — | Último ano da série |

### Processamento

| Opção | Padrão | Descrição |
| --- | --- | --- |
| `--window-size` | `2048` | Múltiplo de 512 |
| `--halo` | `16` | Pixels de contexto para o filtro espacial |
| `--spatial-filter` / `--no-spatial-filter` | ligado | Filtro de patches ≤ 11 px |
| `--group-size-filter` | `11` | Limiar do filtro |
| `--group-size-exception` | `11` | Limiar do último ano |
| `--blip-filter` / `--no-blip-filter` | ligado | Filtro de blip de 1 ano |
| `--secondary-end-rules` / `--no-secondary-end-rules` | ligado | Regras ancoradas |
| `--max-windows` | todos | Limita o número de janelas (amostragem) |
| `--window-start` | `0` | Pula as primeiras N janelas (amostragem) |
| `--checkpoint-every` | `25` | Janelas entre gravações de estado |
| `--compression` | `deflate` | Compressão dos GeoTIFFs de saída |
| `--force` | — | Ignora checkpoints e recria as saídas |
| `--no-progress` | — | Sem barras de progresso |
| `--log-level` | `INFO` | `DEBUG`, `INFO`, `WARNING` ou `ERROR` |

### Específicas

- `audit --blocks N`: blocos nativos amostrados por raster (padrão 12).
- `preflight --blocks N`: blocos por raster na verificação (padrão 12).
- `preflight --deep`: lê todos os blocos de todos os anos (pode levar dezenas de minutos).
- `qa --sample-blocks N`: blocos por arquivo; `0` faz varredura completa.
- `run --steps ...`: subconjunto de `audit deforestation secondary`.
- `run --write-audit`: inclui a auditoria mesmo sem `audit` em `--steps`.

## Configuração

Formato TOML (recomendado), JSON ou YAML. O bloco `[run]` é achatado na leitura; um
arquivo JSON pode usar `{"run": {...}}` ou o objeto direto. Chaves desconhecidas são
preservadas em `extra`, o que permite anotar execuções sem quebrar a validação.

Prioridade: linha de comando > arquivo de configuração > valores padrão.

## Retomada e checkpoints

- O estado fica em `outputs/intermediate/deforestation_state.json`.
- A assinatura inclui anos, tamanho de janela, halo, opções de filtro e a grade. Se
  qualquer parâmetro mudar, o estado é descartado.
- Sem `--force`, se o estado existe **e** os produtos existem, as janelas já concluídas
  são puladas e os arquivos não são truncados.
- Com `--force`, o estado é ignorado, as saídas são recriadas e tudo é reprocessado.

## Amostragem e validação

```powershell
python run_local.py --input-dir E:\Mapbiomas --output-dir outputs_demo `
  --start 2004 --end 2025 --yes --window-start 2295 --max-windows 4 --no-progress
```

As janelas são numeradas em ordem de linha (76 janelas por linha com o tamanho padrão).
Com `--window-start`/`--max-windows`, o QA confere exatamente essas janelas.

Checklist antes de uma execução completa:

1. `preflight` sem erros (e, de preferência, `--deep`);
2. conjunto de classes amostradas compatível com a legenda e presença de 77;
3. uma janela de desmatamento com classes esperadas (1, 2, 3, 4, 5, 6, 7);
4. `qa` consistente nos produtos gerados;
5. totais anuais plausíveis quando comparados ao produto oficial.

## Estimativas de custo

- 22,59 bilhões de pixels por ano; ~22,6 GB descomprimidos por ano.
- janela 2048²: ~5.472 janelas na grade completa.
- memória de pico por janela: < 1 GB.
- desmatamento completo: ~5,5 s por janela sem máscara → cerca de 8 h no total,
  dependendo do disco e do OpenCV.
- verificação completa (`--deep-check`): leitura de ~500 GB descomprimidos.
- saídas: ~1,5–3 GB por ano (22–66 GB na série completa), dependendo da entropia.
- recomenda-se ≥ 100 GB livres no disco de saída.

## Saídas para inspeção

- `outputs/deforestation/deforestation_YYYY.tif`: abra no QGIS com a paleta 0–7.
- `outputs/secondary_vegetation/secondary_vegetation_age.tif`: 22 bandas (uma por ano).
- `outputs/secondary_vegetation/deforestation_frequency.tif`: contagem de eventos.
- `outputs/reports/preflight.md`: laudo da verificação dos insumos.
- `outputs/reports/product_qa.json`: contagens por classe e consistência dos produtos.
- `outputs/logs/run_*.log`: log completo.

## Solução de problemas

- Erro de grade: confira se todos os anos usam a mesma grade; o pipeline aborta em vez de
  reamostrar.
- Arquivo truncado: o `preflight` aponta o ano e o bloco; baixe novamente o arquivo.
- Lentidão no filtro espacial: instale `opencv-python-headless` (`.[filter]`).
- `PyYAML is required`: use TOML/JSON ou instale `pyyaml`.
- Aviso do pip sobre scripts fora do PATH: os comandos devem ser chamados com
  `python -m mapbiomas_local` ou pelo caminho completo do executável.
