# Metodologia

Este documento descreve o que o `mapbiomas-local` calcula e por que cada etapa existe.
A referência conceitual é o repositório
`brazil-deforestation-sec-vegetation` (commit `ee9707a`), em especial
`collection11/mapbiomas_brazil_deforestation_secondary_vegetation.py` e
`collection11/docs/temporal-rules.md`.

O escopo é somente o algoritmo de desmatamento/vegetação secundária. Não há biomas,
municípios, elegibilidade nem máscara territorial.

## 1. Insumos

- 22 GeoTIFFs anuais (`mapbiomas_col11_2004.tif` … `2025.tif`), Coleção 11, cobertura
  pública v3.
- Grade idêntica em todos os anos: EPSG:4326, 154.468 × 146.235 pixels
  (22.588.627.980 pixels), resolução 0,00026949458523585647°, `uint8`, 1 banda,
  NoData = 0, blocos 512 × 512, DEFLATE, BigTIFF.
- A grade comum é verificada antes do processamento (`check_grids`). Divergência de CRS,
  tamanho ou transform aborta a execução.

**Overviews:** os níveis 2–256 foram construídos por média e contêm classes que não
existem na legenda. Nenhuma leitura categórica usa overviews; todas as leituras são feitas
em resolução nativa com reamostragem *nearest*.

## 2. Agregação de classes

A legenda bruta é agregada para quatro códigos antes das regras temporais:

- 0 → 0 (sem dados)
- 1, 3, 4, 5, 6, 7, 10, 11, 12, 13, 49, 50, 66, 70, 77, 84 → 2 (vegetação primária)
- 9, 14, 15, 18, 19, 20, 21, 22, 24, 25, 30, 31, 35, 36, 39, 40, 41, 46, 47, 48, 62,
  72, 75, 91 → 1 (antrópico)
- 23, 26, 29, 32, 33, 34, 61, 68, 69 → 7 (outras transições)
- 27 → 0

Observações:

- A Coleção 11 renomeou a classe 13 para **77**. As duas são mapeadas para 2.
- O LUT tem 256 posições; qualquer valor bruto não listado cai em 0.
- As classes 3–6 da legenda final **não existem no insumo**: são criadas pelas regras
  temporais.

## 3. Regras temporais

Cada série de pixel é processada na seguinte ordem:

1. **Filtro de blip (3 anos)** — `[1,2,1] → [1,1,1]`. Remove um único ano de vegetação
   entre dois anos antrópicos.
2. **Regras ancoradas no fim da série (6 anos)** — três janelas:
   - `[1,1,1,1,2,2] → [1,1,1,1,5,3]`
   - `[1,1,1,1,1,2] → [1,1,1,1,1,5]`
   - `[2,1,1,1,1,2] → [2,1,1,1,1,5]`
3. **Reversão ancorada (4 anos)** — `[1,2,2,1] → [1,1,1,1]`.
4. **Estabelecimento de supressão primária (4 anos)** — `[2,2,1,1] → [2,2,4,1]`.
5. **Regras de vegetação secundária (4 anos, 8 regras)** — cobrem transições como
   `[1,2,2,2] → [1,5,3,3]`, `[3,2,2,4] → [3,3,3,4]`, `[3,3,2,4] → [3,3,3,6]`, entre
   outras.
6. **Supressão secundária (3 anos)** — `[3,4,1] → [3,6,1]`.
7. **Regras de fim de série (últimos 4 anos)** — `[2,2,2,1] → [2,2,2,4]` e
   `[3,3,3,1] → [3,3,3,6]`.
8. **Correção por frequência** — frequência é a soma cumulativa de anos antrópicos
   (inclusive o ano corrente):
   - `freq > 1` e classe 4 → 6
   - `freq > 0` e classe 2 → 3
9. **Tail guard** — remove vegetação secundária induzida pela frequência quando o ano
   imediatamente anterior é antrópico, nos dois últimos anos da série.

`min_start = 1` bloqueia a primeira janela em que a regra apareceria, evitando aplicar
regras no início da série sem contexto suficiente (equivalente aos anos de aquecimento).

### Definições resultantes

- **Desmatamento** é a supressão de vegetação primária (classe 4) ou secundária
  (classe 6), incluindo as regras de fim de série. Não é "classe 3/4 → qualquer classe".
- **Vegetação secundária** é a classe 3; **recuperação** é a classe 5.
- **Outras transições** (7) recebem os patches pequenos removidos pelo filtro espacial.

## 4. Processamento por janelas e halo

- Janelas padrão de 2.048 × 2.048 pixels; qualquer múltiplo de 512 é aceito.
- O filtro espacial é aplicado por ano e depende do tamanho do componente conexo. Para
  não truncar componentes na borda da janela, cada janela é lida com **halo de 16 pixels**
  (maior que o limiar de 11). O resultado gravado é apenas o núcleo.
- O halo é recortado nos limites do raster; nesse caso o comportamento coincide com o
  processamento da cena inteira.
- A leitura é feita ano a ano com `Resampling.nearest` na resolução nativa.
- Janelas totalmente sem dados são marcadas como concluídas sem escrita (ficam em 0).

## 5. Filtro espacial

Para cada ano, em ordem:

1. pixels 4 ou 6: componentes 8-conectados com área ≤ 11 pixels são convertidos em 7;
2. pixels 3 ou 5: componentes 8-conectados com área ≤ 11 pixels são convertidos em 7.

O limiar e o ano de exceção são configuráveis (`group_size_filter`,
`group_size_exception`). A implementação usa OpenCV quando disponível e um fallback puro
em NumPy/Python (union-find por runs) caso contrário.

## 6. Verificação dos insumos

Antes de processar, o `preflight` confere cada ano do período: arquivo existente e não
vazio, legibilidade dos blocos, uma banda, `uint8`, NoData, CRS, largura/altura/transform
idênticos ao ano de referência e classes amostradas. Anos faltantes dentro do período são
reportados; com menos de 6 anos o processamento é bloqueado. A verificação é amostral por
padrão (12 blocos por ano) e pode ser completa (`--deep-check`), lendo todos os blocos.

## 7. Série e produtos


- Anos disponíveis: 2004–2025.
- **Aquecimento:** 2004 e 2005. O primeiro ano recomendado para análise é **2006** (dois
  anos de contexto antes do primeiro produto).
- A série exige pelo menos 6 anos neste projeto. Isso **não** é uma validação do
  script original do GEE (que assume 1985–2025 e não checa o tamanho): é uma proteção
  local. O maior kernel é de 6 anos (regras ancoradas de fim de série) e os dois
  primeiros anos são aquecimento. Com menos de 6 anos essa janela não roda, então o
  fim da série não seria classificado como no método oficial.
- Um arquivo por ano, `uint8`, mesma grade e georreferência dos insumos. O NoData de
  saída é 0; não há máscara territorial.
- Produtos opcionais derivados da série:
  - `secondary_vegetation_age.tif`: número de anos consecutivos em classe 3 ou 5, por ano;
  - `deforestation_frequency.tif`: número de anos com classe 4 ou 6 no período.

Esses produtos são derivados da série de desmatamento e não substituem os produtos
oficiais.
