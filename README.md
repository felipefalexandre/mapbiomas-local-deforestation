# mapbiomas-local

Reimplementação local, em Python, do algoritmo de **desmatamento e vegetação secundária**
da Coleção 11 do MapBiomas.

O método é o mesmo do repositório
[`brazil-deforestation-sec-vegetation`](https://github.com/felipefalexandre/brazil-deforestation-sec-vegetation)
(commit `ee9707a`), que roda no Google Earth Engine. Aqui as regras temporais e o filtro
espacial são aplicados diretamente sobre os GeoTIFFs anuais do MapBiomas, sem Earth Engine
em tempo de execução.

O escopo é **apenas o algoritmo**: não há biomas, municípios, elegibilidade nem qualquer
outro filtro territorial. Os produtos são os mapas anuais de transição e, opcionalmente,
idade da vegetação secundária e frequência de desmatamento.

## Produtos

| Produto | Caminho | Conteúdo |
| --- | --- | --- |
| Desmatamento anual | `outputs/deforestation/deforestation_YYYY.tif` | Um mapa por ano, classes 0–7 |
| Idade da vegetação secundária | `outputs/secondary_vegetation/secondary_vegetation_age.tif` | Anos consecutivos em classe 3/5, por ano |
| Frequência de desmatamento | `outputs/secondary_vegetation/deforestation_frequency.tif` | Número de anos com classe 4/6 |
| Relatórios | `outputs/reports/*.json` | Auditoria, resumo e parâmetros efetivos |
| Logs | `outputs/logs/run_*.log` | Execução completa |

### Legenda dos mapas anuais

| Valor | Classe |
| --- | --- |
| 0 | Sem dados |
| 1 | Antrópico |
| 2 | Vegetação primária |
| 3 | Vegetação secundária |
| 4 | Supressão de vegetação primária |
| 5 | Recuperação para vegetação secundária |
| 6 | Supressão de vegetação secundária |
| 7 | Outras transições |

## Instalação

```powershell
C:\Python315\python.exe -m pip install -e ".[filter,dev]"
```

Dependências: NumPy, Rasterio e tqdm. OpenCV (`filter`) acelera o filtro espacial; sem
ele existe um fallback em NumPy puro. `dev` instala o pytest.

## Uso para quem já tem a Coleção 11

Basta clonar o repositório e rodar o assistente:

```powershell
python run_local.py
```

Ele pergunta, em sequência:

1. a pasta onde estão os GeoTIFFs anuais (por exemplo `E:\Mapbiomas`);
2. o padrão dos nomes, se for diferente de `mapbiomas_col11_{year}.tif`;
3. a pasta de saída;
4. o período desejado (ano inicial e final).

Antes de processar, o assistente **verifica os dados**: presença de cada ano do período,
arquivos vazios ou truncados, bandas/dtype/NoData, CRS, grade idêntica entre anos,
classes amostradas e, opcionalmente, leitura completa de todos os blocos. Se faltarem
anos, ele avisa e pergunta se deve continuar com os anos disponíveis. Se houver erro
bloqueante, o processamento não começa. O relatório fica em
`outputs/reports/preflight.{json,md}`.

Em seguida gera a série anual de desmatamento, os produtos opcionais de vegetação
secundária e roda um controle de qualidade nos resultados
(`outputs/reports/product_qa.json`).

Também é possível rodar sem perguntas (útil para script ou teste):

```powershell
python run_local.py --input-dir E:\Mapbiomas --output-dir outputs `
  --start 2004 --end 2025 --yes
```

Teste rápido em poucas janelas:

```powershell
python run_local.py --input-dir E:\Mapbiomas --output-dir outputs_demo `
  --start 2004 --end 2025 --yes --window-start 2295 --max-windows 4 --no-progress
```

Alternativamente, use os subcomandos:

```powershell
python -m mapbiomas_local preflight --config configs\example.toml
python -m mapbiomas_local deforestation --config configs\example.toml
python -m mapbiomas_local secondary --config configs\example.toml
python -m mapbiomas_local qa --config configs\example.toml
```

Tudo de uma vez:

```powershell
python -m mapbiomas_local run --config configs\example.toml `
  --steps audit deforestation secondary
```

Amostragem rápida (algumas janelas):

```powershell
python -m mapbiomas_local deforestation --config configs\example.toml `
  --window-start 2295 --max-windows 4 --force
```

Qualquer opção do arquivo de configuração pode ser sobrescrita na linha de comando. Veja
`docs/usage.md` e `docs/methodology.md`.

## Configuração

TOML, JSON ou YAML (este último requer `pyyaml`). Exemplos em `configs/example.toml` e
`configs/example.json`. A configuração padrão usa janelas de 2.048 pixels, halo de 16
pixels e filtro espacial de 11 pixels. Reserve pelo menos 100 GB livres: os produtos
ocupam cerca de 1,5–3 GB por ano.

## Limitações e decisões

- **Insumo público.** O original consome o asset interno `INTEGRATION/classification-ft`
  versão `0-4-14-c84-5`. Aqui usamos a cobertura pública v3; equivalência pixel a pixel
  com o produto oficial não pode ser demonstrada (ver `docs/migration_audit.md`).
- **Overviews não são categóricos.** Os níveis 2–256 dos TIFFs foram gerados por média e
  contêm classes inexistentes. O pipeline lê sempre a resolução nativa.
- **Classe 77.** A Coleção 11 substituiu a classe 13 por 77; ambas são agregadas como
  vegetação primária (2).
- **Série útil: 2006–2025.** 2004 e 2005 são aquecimento. O projeto exige ≥ 6 anos
  como proteção local (o script original do GEE não valida o tamanho da série); com
  menos anos, a janela ancorada de 6 anos não roda e o fim da série fica incompleto.
- **Sem recorte territorial.** O produto não é mascarado por bioma, município ou
  elegibilidade; quem precisar de recorte deve aplicar sua própria máscara.
- **Processamento por janelas.** O filtro espacial usa halo de 16 pixels (maior que o
  limiar de 11) para não truncar componentes; grava-se apenas o núcleo. Nos limites do
  raster o resultado coincide com o processamento da cena inteira.

## Testes

```powershell
$env:PYTHONPATH="src"; C:\Python315\python.exe -m pytest
```

A suíte cobre a semântica das regras contra uma implementação de referência (séries de
6, 10 e 41 anos), `min_start`, blip, regras ancoradas, frequência, tail guard, filtro
espacial, janelas/halo, configuração e o pipeline completo em rasters sintéticos.

## Licença

MIT, com atribuição ao método original. Veja `LICENSE`.
