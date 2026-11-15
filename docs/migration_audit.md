# Auditoria da migração GEE → local

Este documento registra o que foi migrado, o que mudou e quais evidências sustentam a
equivalência (ou a divergência declarada).

## 1. Fonte

- Repositório: `https://github.com/felipefalexandre/brazil-deforestation-sec-vegetation`
- Commit de referência: `ee9707a`
- Licença original: ausente; este projeto adota MIT com atribuição (ver `LICENSE`).

Arquivos usados como referência:

| Arquivo | Papel |
| --- | --- |
| `collection11/mapbiomas_brazil_deforestation_secondary_vegetation.py` | Pipeline Earth Engine completo (regras, filtro, exportação) |
| `collection11/deforestation_secondary_vegetation.py` | Classe de kernels e `min_start` |
| `collection11/docs/temporal-rules.md` | Semântica das regras e ordem de aplicação |
| `collection11/docs/products.md` | Definição dos produtos originais |
| `collection11/tests/test_rules.py` | ~50 testes de semântica |

## 2. Mapa de funções

| Original (GEE) | Local | Observação |
| --- | --- | --- |
| `CLASS_LOOKUP` | `rules.CLASS_LOOKUP` / `build_lookup` | Mesmos pares; LUT de 256 posições |
| `aggregate` / `remap` | `rules.aggregate` | Indexação NumPy |
| `apply_rule_kernel` | `rules.apply_rule_kernel` | Janela deslizante sequencial, `min_start` |
| `apply_rules` | `rules.apply_rules` | Valida tamanho do kernel |
| `get_class_frequency` | `rules.class_frequency` | Soma cumulativa inclusiva |
| correção de frequência | `rules.apply_frequency_correction` | Mesmas duas condições |
| tail guard | `rules.apply_tail_guard` | Últimos 3 anos |
| `export_deforestation` | `deforestation.run_deforestation` | Janelas + halo |
| filtro de patches | `rules.filter_small_patches` / `apply_spatial_filter` | 8-conectado, limiar 11 |
| exportação por blocos CIM | — | Não migrada: não faz parte do algoritmo |
| máscara de biomas | — | Fora de escopo por decisão do projeto |
| estatísticas municipais | — | Fora de escopo por decisão do projeto |

## 3. Diferenças declaradas

1. **Insumo.** O GEE consome `INTEGRATION/classification-ft` versão `0-4-14-c84-5`
   (asset interno). Os GeoTIFFs locais são a cobertura pública v3
   (`collection_id=11`, `version=v3`). Não é possível demonstrar equivalência pixel a
   pixel; a validação é feita por semântica, testes e amostragem.
2. **Remapeamento 13 → 77.** A Coleção 11 renomeou a classe 13 para 77. Ambas são
   agregadas como vegetação primária (2). Sem isso, ~5,5 milhões de pixels por ano
   (formação herbácea-arbustiva) seriam tratados como sem dados.
3. **Overviews.** Os níveis 2–256 dos TIFFs são médias e contêm classes inválidas. O
   código local nunca lê overviews; o GEE trabalha em escala nativa por padrão.
4. **Conectividade.** O GEE usa operações de vizinhança/distância; o código local usa
   rotulagem 8-conectada (OpenCV ou union-find por runs). O resultado é equivalente para
   o critério de área ≤ 11 pixels.
5. **Bordas de janela.** O GEE processa a cena inteira. O código local usa janelas com
   halo de 16 pixels (> limiar 11) e grava apenas o núcleo. O halo garante que nenhum
   componente seja truncado; nos limites do raster o comportamento coincide com a cena
   inteira. Há teste comparando processamento por janelas com a cena inteira.
6. **Escopo.** O original também exporta por blocos CIM, aplica máscara de biomas e
   calcula estatísticas municipais. Este repositório implementa **somente** as regras
   temporais e o filtro espacial.
7. **Série.** O original publica 1985–2025. Aqui o insumo começa em 2004; a série útil é
   2006–2025, com 2004–2005 como aquecimento. O projeto exige ≥ 6 anos por proteção
   local (o script original não valida o tamanho); com menos, a janela ancorada de 6
   anos é pulada e o fim da série não segue o método oficial.
8. **Configuração.** O GEE usa constantes no script; aqui tudo é parametrizável por
   TOML/JSON/YAML e CLI, com assinatura de estado para retomada.

## 4. Evidências

### 4.1 Testes automatizados

`python -m pytest` (42 testes):

- regras comparadas com uma implementação de referência fiel ao script original para
  séries aleatórias de 6, 10 e 41 anos;
- `min_start`, blip, regras ancoradas, frequência, tail guard e filtro espacial;
- equivalência do fallback de rotulagem com OpenCV;
- janelas, halo, recorte de núcleo, descoberta de anos e validação de grade;
- pipeline completo em rasters sintéticos, incluindo igualdade entre processamento por
  janelas e cena inteira e produtos secundários;
- verificação de insumos (anos faltantes, grade divergente, arquivo truncado) e controle
  de qualidade dos produtos.

### 4.2 Amostras em dados reais

Desmatamento (2 janelas, 22 anos):

- execução em ~52 s com a versão anterior, que ainda aplicava máscara vetorial;
- classes 0–7 presentes na janela amazônica; 255 apenas nas bordas da máscara (comportamento
  removido neste escopo);
- denominador medido: ~5,3 s por janela sem máscara (dados reais, 2.080²).

## 5. Riscos residuais

- Divergência entre a cobertura pública e o asset interno pode alterar transições
  individuais; os totais devem ser comparados com o produto oficial antes de publicação.
- O filtro espacial com OpenCV é mais rápido; sem ele, janelas grandes podem ficar
  significativamente mais lentas (o resultado é o mesmo).
- Sem recorte territorial, o produto cobre todo o raster de entrada. Quem precisar de
  Amazônia/Cerrado deve aplicar a própria máscara fora do pipeline.
