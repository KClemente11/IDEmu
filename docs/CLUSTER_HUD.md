# Cluster, HUD, nível de funcionalidade e pasta da VM (2026-11-08)

## Cluster e HUD (iDrive 5 e 6)
Aba **Cluster e HUD** da tela Execução. Desenha o painel de instrumentos (Kombi) e o HUD com o estado do carro virtual:

| O que aparece | De onde vem |
|---|---|
| Velocímetro, conta-giros, câmbio P/R/N/D, modo de condução | Sinais do CAN virtual (`vehicle_speed`, `engine_rpm`, `gear_position`, `driving_mode`) |
| Combustível, temperatura do motor, autonomia, hodômetro, temperatura externa | CAN (`fuel_level`, `coolant_temp`, `odometer`, `outside_temp`); autonomia = litros ÷ consumo instantâneo |
| Setas e pisca-alerta (piscam), farol baixo e alto | CAN (`turn_left`, `turn_right`, `hazard`, `headlight_*`) |
| Alertas: cinto, freio de mão, porta, porta-malas, capô, motor quente ou frio, combustível baixo, pneus | Calculados dos sinais (`idemu/cluster.py`, `warnings`) |
| HUD: velocidade, câmbio, seta de curva e distância | CAN e GPS |
| Próxima curva e distância no HUD | **Calculadas pela geometria da rota do GPS virtual** (curva = mudança de rumo de 35° ou mais nos próximos 2 km). Sem rota, o HUD mostra só a velocidade e o câmbio |

`GET /api/cluster` entrega tudo isso (ver `docs/API.md`). Mude os sinais na aba CAN, ou rode um cenário, e o painel reage.

### O que o HMI manda ao cluster e ao HUD
O HMI fala com o Kombi (FBlock MOST `0xE0`) e com o HUD (`0xE1`) pelo V850 emulado. `MostBridge.seen` (`idemu/most.py`) guarda a última mensagem Set/Get de cada função; a aba lista as do Kombi e do HUD, e `GET /api/v850/seen` lista todas.

**Medido (2026-11-08, F30 com `id6_light`):** em repouso e abrindo o menu Mídia/Rádio, o HMI **não mandou nada** ao Kombi nem ao HUD. A única mensagem de saída veio do `0xE5/1` (função `0xc30`). O motivo é que o iDrive emulado não tem motor de navegação nem fonte de mídia: quem gera manobras, listas de faixas e mensagens de check control para o cluster é o próprio HMI quando tem esse conteúdo. Se algum dia ele mandar, aparece na lista da aba (com o nome da função, tirado de `idemu/data/hmi_most_map.json`), mas **o layout dos bytes não foi decodificado**: nada disso é desenhado ainda.

### Limites
* O desenho é do IDEmu, não o do cluster do carro. A aparência é genérica (dois mostradores), sem os temas Comfort, Sport e Eco Pro.
* Só existe no iDrive 5 e 6 (precisa de CAN e GPS virtuais). No iDrive 7 e 8 a aba fica oculta.

## Nível de funcionalidade por versão
No assistente **Novo ambiente**, cada versão do iDrive mostra uma barra com o percentual e a lista do que funciona (✓), funciona em parte (◐) ou não funciona (✕). Passe o mouse sobre um item para ver o que falta. O cálculo é a média de 12 itens (funciona = 1, em parte = 0,5, não funciona = 0), definida em `idemu/catalog.py` (`FEATURES`, `LEVEL_NOTES`, `level_of`) a partir de `docs/OUTRAS_GERACOES.md`, `docs/TOQUE.md`, `docs/CELULAR.md` e `docs/PENDRIVE.md`.

| Versão | Nível |
|---|---|
| iDrive 6 | 75% (Alto) |
| iDrive 5 | 54% (Médio) |
| iDrive 8 | 42% (Baixo) |
| iDrive 7 | 29% (Baixo) |

Os valores são uma avaliação do estado atual, não uma medição automática: **ao mudar o que funciona, atualize `LEVEL_NOTES`** (o teste `tests/test_cluster.py` confere só a consistência do cálculo).

## Pasta da máquina virtual
Na primeira etapa do assistente, **Onde a máquina virtual fica**: **Escolher pasta…** abre o seletor do servidor (a pasta pode estar em outro disco). O IDEmu cria `<pasta>/<id do ambiente>` e liga `environments/<id>` a ela por link simbólico; discos (`images/`), logs, estado salvo (`snapshot/`), gravações e o resto vivem lá, e o IDEmu segue usando `environments/<id>`. A escolha é lembrada para os próximos ambientes.

* Exige pasta existente, com permissão de escrita e 1 GB livre. O iDrive 5 e 6 usam cerca de 3 GB por ambiente (imagens 1,2 GB + estado salvo 1,5 GB), e a tela avisa quando o disco tem menos de 4 GB.
* **Excluir** apaga só a subpasta `<pasta>/<id>` que o IDEmu criou (e só se tiver `env.json`) e o link; a pasta escolhida nunca é apagada. **Duplicar** põe a cópia na mesma pasta da original.
* Disco externo desconectado: o ambiente some da lista (o link fica quebrado) até o disco voltar.
* iDrive 7 e 8: a imagem do sistema (alguns GB) é única e compartilhada e continua em `mgu7/` e `mgu22/`; só os dados e os logs do ambiente vão para a pasta escolhida.
* Ambientes que já existem não mudam de lugar.
